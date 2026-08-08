# -*- coding: utf-8 -*-
"""Safe ZIP inspection and transactional Mod installation."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, List, Optional, Sequence, Tuple

from modules.config import APP_DIR


MAX_ENTRIES = 50_000
MAX_PATH_DEPTH = 32
MAX_COMPRESSION_RATIO = 1_000
COMPRESSION_RATIO_MIN_SIZE = 100 * 1024 * 1024
DISK_SAFETY_BYTES = 256 * 1024 * 1024
COPY_CHUNK_SIZE = 1024 * 1024

_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *("COM{}".format(index) for index in range(1, 10)),
    *("LPT{}".format(index) for index in range(1, 10)),
    "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³",
}


class ArchiveInstallError(Exception):
    """Raised when an archive cannot be safely inspected or installed."""


class InstallCancelled(ArchiveInstallError):
    """Raised when the caller cancels an installation."""


@dataclass(frozen=True)
class ArchiveCandidate:
    candidate_id: str
    suggested_name: str
    relative_root: str
    file_count: int
    total_size: int


@dataclass(frozen=True)
class ArchiveInspection:
    archive_path: str
    archive_name: str
    file_count: int
    total_size: int
    candidates: Tuple[ArchiveCandidate, ...]
    archive_digest: str


@dataclass(frozen=True)
class InstallSelection:
    candidate: ArchiveCandidate
    target_name: str
    enabled: bool = True


@dataclass(frozen=True)
class InstallResult:
    target_name: str
    target_path: str
    enabled: bool
    success: bool
    error: str = ""


def validate_mod_name(name: str) -> str:
    """Validate a single Windows-safe directory name and return it stripped."""
    clean = name.strip()
    if not clean or clean in (".", ".."):
        raise ArchiveInstallError("Mod 文件夹名称不能为空")
    if clean != name or clean.endswith((".", " ")):
        raise ArchiveInstallError("Mod 文件夹名称不能以空格或句点结尾")
    if _INVALID_WINDOWS_CHARS.search(clean) or "/" in clean or "\\" in clean:
        raise ArchiveInstallError("Mod 文件夹名称包含 Windows 不允许的字符")
    stem = clean.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_NAMES:
        raise ArchiveInstallError("Mod 文件夹名称是 Windows 保留名称")
    return clean


def unique_target_name(preferred: str, target_roots: Sequence[str]) -> str:
    """Return a validated name not present in any supplied target root."""
    preferred = validate_mod_name(preferred)
    existing = set()
    for root in target_roots:
        if os.path.isdir(root):
            existing.update(name.casefold() for name in os.listdir(root))
    if preferred.casefold() not in existing:
        return preferred
    index = 2
    while True:
        candidate = "{} ({})".format(preferred, index)
        if candidate.casefold() not in existing:
            return candidate
        index += 1


def inspect_zip(archive_path: str, archive_name: Optional[str] = None) -> ArchiveInspection:
    """Validate a ZIP directory and derive installable top-level candidates."""
    archive_path = os.path.abspath(archive_path)
    archive_name = archive_name or os.path.basename(archive_path)
    if not os.path.isfile(archive_path):
        raise ArchiveInstallError("ZIP 文件不存在")
    if not zipfile.is_zipfile(archive_path):
        raise ArchiveInstallError("所选文件不是有效的 ZIP 压缩包")

    files = []
    directories = set()
    output_types = {}
    total_size = 0
    total_compressed_size = 0

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise ArchiveInstallError(
                    "ZIP 条目过多（{}，上限 {}）".format(len(infos), MAX_ENTRIES))
            for info in infos:
                parts = _validate_member(info)
                key = "/".join(part.casefold() for part in parts)
                entry_type = "dir" if info.is_dir() else "file"
                previous = output_types.get(key)
                if previous is not None:
                    raise ArchiveInstallError("ZIP 包含重复或大小写冲突路径: {}".format(info.filename))

                for index in range(1, len(parts)):
                    parent_key = "/".join(part.casefold() for part in parts[:index])
                    if output_types.get(parent_key) == "file":
                        raise ArchiveInstallError("ZIP 中的文件与目录路径冲突: {}".format(info.filename))
                if entry_type == "file":
                    prefix = key + "/"
                    if any(existing.startswith(prefix) for existing in output_types):
                        raise ArchiveInstallError("ZIP 中的文件与目录路径冲突: {}".format(info.filename))

                output_types[key] = entry_type
                if entry_type == "dir":
                    directories.add(tuple(parts))
                    continue

                files.append((info, tuple(parts)))
                total_size += info.file_size
                total_compressed_size += info.compress_size
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        if isinstance(exc, ArchiveInstallError):
            raise
        raise ArchiveInstallError("无法读取 ZIP 文件: {}".format(exc)) from exc

    if not files:
        raise ArchiveInstallError("ZIP 中没有可安装的文件")
    if (total_size >= COMPRESSION_RATIO_MIN_SIZE and
            total_size > max(1, total_compressed_size) * MAX_COMPRESSION_RATIO):
        raise ArchiveInstallError("ZIP 总压缩比异常，可能是压缩炸弹")

    top_files = [item for item in files if len(item[1]) == 1]
    top_dirs = sorted({parts[0] for _, parts in files if len(parts) > 1}, key=str.casefold)
    archive_stem = os.path.splitext(archive_name)[0]
    if top_files or not top_dirs:
        candidates = (_build_candidate(".", archive_stem, files),)
    elif len(top_dirs) == 1:
        root = top_dirs[0]
        candidates = (_build_candidate(root, root, files),)
    else:
        candidates = tuple(_build_candidate(root, root, files) for root in top_dirs)

    return ArchiveInspection(
        archive_path=archive_path,
        archive_name=archive_name,
        file_count=len(files),
        total_size=total_size,
        candidates=candidates,
        archive_digest=_sha256_file(archive_path),
    )


def install_zip(
        inspection: ArchiveInspection,
        selections: Sequence[InstallSelection],
        mods_dir: str,
        disabled_dir: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event=None) -> List[InstallResult]:
    """Extract selected candidates and atomically commit each target folder."""
    if not selections:
        return []
    roots = (os.path.abspath(mods_dir), os.path.abspath(disabled_dir))
    for root in roots:
        if not os.path.isdir(root):
            raise ArchiveInstallError("目标 Mod 目录不存在: {}".format(root))

    selected_ids = set()
    target_keys = set()
    for selection in selections:
        if selection.candidate not in inspection.candidates:
            raise ArchiveInstallError("安装候选不属于当前 ZIP")
        if selection.candidate.candidate_id in selected_ids:
            raise ArchiveInstallError("同一个候选不能重复安装")
        selected_ids.add(selection.candidate.candidate_id)
        name = validate_mod_name(selection.target_name)
        target_key = name.casefold()
        if target_key in target_keys:
            raise ArchiveInstallError("多个候选使用了相同目标名称: {}".format(name))
        target_keys.add(target_key)
        if any(os.path.exists(os.path.join(root, name)) for root in roots):
            raise ArchiveInstallError("Mods 或 Disabled_Mods 中已存在同名目录: {}".format(name))

    staging_parent = os.path.join(APP_DIR, "data", "staging")
    os.makedirs(staging_parent, exist_ok=True)
    operation_dir = tempfile.mkdtemp(prefix="install-", dir=staging_parent)
    # Progress covers both extraction to app staging and copy to the target volume.
    total_files = sum(selection.candidate.file_count for selection in selections) * 2
    completed_files = 0
    prepared = []

    try:
        pinned_archive = os.path.join(operation_dir, "source.zip")
        selected_size = sum(
            selection.candidate.total_size for selection in selections)
        selected_files = sum(
            selection.candidate.file_count for selection in selections)
        _require_disk_space(
            operation_dir,
            os.path.getsize(inspection.archive_path) +
            _estimated_disk_bytes(selected_size, selected_files))
        _copy_file(inspection.archive_path, pinned_archive, cancel_event)
        if _sha256_file(pinned_archive) != inspection.archive_digest:
            raise ArchiveInstallError("ZIP 文件在确认后发生变化，请重新选择并检查")
        current_inspection = inspect_zip(
            pinned_archive, archive_name=inspection.archive_name)
        if current_inspection.candidates != inspection.candidates:
            raise ArchiveInstallError("ZIP 文件在确认后发生变化，请重新选择并检查")

        required = _estimated_disk_bytes(selected_size, selected_files)
        _require_disk_space(operation_dir, required)
        with zipfile.ZipFile(pinned_archive, "r") as archive:
            validated = [(info, tuple(_validate_member(info))) for info in archive.infolist()]
            for index, selection in enumerate(selections):
                _check_cancel(cancel_event)
                candidate_dir = os.path.join(operation_dir, "candidate-{}".format(index))
                os.makedirs(candidate_dir)
                members = _candidate_members(validated, selection.candidate.relative_root)
                for info, relative_parts in members:
                    _check_cancel(cancel_event)
                    if info.is_dir():
                        os.makedirs(os.path.join(candidate_dir, *relative_parts), exist_ok=True)
                        continue
                    destination = os.path.join(candidate_dir, *relative_parts)
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    with archive.open(info, "r") as source, open(destination, "xb") as output:
                        while True:
                            _check_cancel(cancel_event)
                            chunk = source.read(COPY_CHUNK_SIZE)
                            if not chunk:
                                break
                            output.write(chunk)
                    completed_files += 1
                    if progress_callback:
                        progress_callback(completed_files, total_files, selection.target_name)

                target_root = roots[0] if selection.enabled else roots[1]
                _require_disk_space(
                    target_root,
                    _estimated_disk_bytes(
                        selection.candidate.total_size,
                        selection.candidate.file_count))
                target_path = os.path.join(target_root, selection.target_name)
                temp_target = os.path.join(
                    target_root, ".efmi-install-{}".format(uuid.uuid4().hex))
                try:
                    os.makedirs(temp_target)
                    for source_path, relative_parts in _iter_tree_files(candidate_dir):
                        _check_cancel(cancel_event)
                        destination = os.path.join(temp_target, *relative_parts)
                        os.makedirs(os.path.dirname(destination), exist_ok=True)
                        _copy_file(source_path, destination, cancel_event)
                        completed_files += 1
                        if progress_callback:
                            progress_callback(
                                completed_files, total_files, selection.target_name)
                    _write_local_manifest(temp_target, inspection, selection)
                    _check_cancel(cancel_event)
                    prepared.append((selection, temp_target, target_path))
                except InstallCancelled:
                    shutil.rmtree(temp_target, ignore_errors=True)
                    raise
                except Exception as exc:
                    shutil.rmtree(temp_target, ignore_errors=True)
                    raise ArchiveInstallError(
                        "准备 Mod {} 失败: {}".format(selection.target_name, exc)) from exc

        _check_cancel(cancel_event)
        committed = []
        try:
            for selection, temp_target, target_path in prepared:
                if os.path.exists(target_path):
                    raise ArchiveInstallError(
                        "提交前发现同名目录: {}".format(selection.target_name))
                os.replace(temp_target, target_path)
                committed.append((selection, temp_target, target_path))
        except Exception as exc:
            rollback_errors = []
            for selection, temp_target, target_path in reversed(committed):
                try:
                    if os.path.exists(target_path):
                        os.replace(target_path, temp_target)
                except OSError as rollback_exc:
                    rollback_errors.append(
                        "{}: {}".format(selection.target_name, rollback_exc))
            if rollback_errors:
                raise ArchiveInstallError(
                    "安装提交失败且部分回滚失败: {}; {}".format(
                        exc, "; ".join(rollback_errors))) from exc
            raise ArchiveInstallError("安装提交失败，已回滚: {}".format(exc)) from exc

        return [
            InstallResult(selection.target_name, target_path, selection.enabled, True)
            for selection, _, target_path in committed
        ]
    except InstallCancelled:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ArchiveInstallError("安装 ZIP 失败: {}".format(exc)) from exc
    finally:
        for _, temp_target, _ in prepared:
            shutil.rmtree(temp_target, ignore_errors=True)
        shutil.rmtree(operation_dir, ignore_errors=True)


def install_loose_file(
        source_path: str, mods_dir: str, disabled_dir: str, preferred_name: str,
        enabled: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event=None) -> InstallResult:
    """Install a single loose file into a new Mod folder (non-archive install).

    Returns InstallResult with the created folder path; raises
    ArchiveInstallError on failure, InstallCancelled on user cancel.
    """
    source_path = os.path.abspath(source_path)
    if not os.path.isfile(source_path):
        raise ArchiveInstallError("文件不存在: {}".format(source_path))
    roots = (os.path.abspath(mods_dir), os.path.abspath(disabled_dir))
    for root in roots:
        if not os.path.isdir(root):
            raise ArchiveInstallError("目标 Mod 目录不存在: {}".format(root))

    name = validate_mod_name(preferred_name)
    target_name = unique_target_name(name, roots)
    target_root = roots[0] if enabled else roots[1]
    _require_disk_space(target_root, _estimated_disk_bytes(os.path.getsize(source_path), 1))

    inner_name = os.path.basename(source_path).strip().strip(".")
    inner_name = _INVALID_WINDOWS_CHARS.sub("_", inner_name) or "file"

    target_path = os.path.join(target_root, target_name)
    temp_target = os.path.join(target_root, ".efmi-install-{}".format(uuid.uuid4().hex))
    try:
        os.makedirs(temp_target)
        _copy_file(source_path, os.path.join(temp_target, inner_name), cancel_event)
        if progress_callback:
            progress_callback(1, 1, target_name)
        os.replace(temp_target, target_path)
    except InstallCancelled:
        shutil.rmtree(temp_target, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temp_target, ignore_errors=True)
        raise ArchiveInstallError(
            "安装文件 {} 失败: {}".format(preferred_name, exc)) from exc
    return InstallResult(target_name, target_path, enabled, True)


def cleanup_staging(max_age_seconds: int = 24 * 60 * 60) -> None:
    """Remove abandoned installer staging directories older than one day."""
    staging_parent = os.path.join(APP_DIR, "data", "staging")
    if not os.path.isdir(staging_parent):
        return
    cutoff = time.time() - max_age_seconds
    for name in os.listdir(staging_parent):
        path = os.path.join(staging_parent, name)
        try:
            if name.startswith("install-") and os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def cleanup_target_temporaries(
        target_roots: Sequence[str], max_age_seconds: int = 24 * 60 * 60) -> None:
    """Remove abandoned pre-commit directories from Mod target roots."""
    cutoff = time.time() - max_age_seconds
    for root in target_roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            path = os.path.join(root, name)
            try:
                if (name.startswith(".efmi-install-") and os.path.isdir(path) and
                        os.path.getmtime(path) < cutoff):
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_member(info: zipfile.ZipInfo) -> List[str]:
    raw = info.filename.replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("//"):
        raise ArchiveInstallError("ZIP 包含绝对路径: {}".format(info.filename))
    if re.match(r"^[A-Za-z]:", raw):
        raise ArchiveInstallError("ZIP 包含盘符路径: {}".format(info.filename))
    path = PurePosixPath(raw.rstrip("/"))
    parts = list(path.parts)
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ArchiveInstallError("ZIP 包含不安全路径: {}".format(info.filename))
    if len(parts) > MAX_PATH_DEPTH:
        raise ArchiveInstallError("ZIP 目录层级过深: {}".format(info.filename))
    for part in parts:
        validate_mod_name(part)
    if info.flag_bits & 0x1:
        raise ArchiveInstallError("ZIP 包含加密条目，首版不支持: {}".format(info.filename))
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ArchiveInstallError("ZIP 包含链接或特殊文件: {}".format(info.filename))
    if (info.external_attr & 0x400) != 0:
        raise ArchiveInstallError("ZIP 包含 Windows 重解析点: {}".format(info.filename))
    if (info.file_size >= COMPRESSION_RATIO_MIN_SIZE and
            info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO):
        raise ArchiveInstallError("ZIP 条目压缩比异常: {}".format(info.filename))
    return parts


def _build_candidate(root: str, name: str, files) -> ArchiveCandidate:
    if root == ".":
        selected = files
    else:
        selected = [item for item in files if item[1][0] == root]
    return ArchiveCandidate(
        candidate_id=root,
        suggested_name=validate_mod_name(name),
        relative_root=root,
        file_count=len(selected),
        total_size=sum(info.file_size for info, _ in selected),
    )


def _candidate_members(validated, relative_root: str):
    result = []
    for info, parts in validated:
        if relative_root == ".":
            relative_parts = parts
        elif parts[0] == relative_root:
            relative_parts = parts[1:]
        else:
            continue
        if relative_parts:
            result.append((info, relative_parts))
    return result


def _require_disk_space(path: str, required_bytes: int) -> None:
    free = shutil.disk_usage(path).free
    required_with_margin = required_bytes + min(DISK_SAFETY_BYTES, max(16 * 1024 * 1024, free // 20))
    if free < required_with_margin:
        raise ArchiveInstallError(
            "磁盘空间不足，需要至少 {}，当前可用 {}".format(
                format_bytes(required_with_margin), format_bytes(free)))


def _estimated_disk_bytes(payload_bytes: int, file_count: int) -> int:
    # Allow for allocation units and metadata when a ZIP contains many tiny files.
    return payload_bytes + file_count * 8192


def _check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise InstallCancelled("安装已取消")


def _iter_tree_files(root):
    for current_root, directory_names, file_names in os.walk(root):
        directory_names.sort(key=str.casefold)
        file_names.sort(key=str.casefold)
        for file_name in file_names:
            source_path = os.path.join(current_root, file_name)
            relative_path = os.path.relpath(source_path, root)
            yield source_path, tuple(relative_path.split(os.sep))


def _copy_file(source_path, destination, cancel_event):
    with open(source_path, "rb") as source, open(destination, "xb") as output:
        while True:
            _check_cancel(cancel_event)
            chunk = source.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            output.write(chunk)
    shutil.copystat(source_path, destination)


def _write_local_manifest(target_dir, inspection, selection) -> None:
    metadata_dir = os.path.join(target_dir, ".efmi_mod_manager")
    os.makedirs(metadata_dir, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "provider": "local",
        "archive_name": inspection.archive_name,
        "candidate_id": selection.candidate.candidate_id,
        "installed_at": int(time.time()),
        "folder_name": selection.target_name,
    }
    path = os.path.join(metadata_dir, "source.json")
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return "{:.1f} {}".format(value, unit)
        value /= 1024
    return "{} B".format(size)
