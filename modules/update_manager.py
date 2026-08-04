# -*- coding: utf-8 -*-
"""Transactional replacement and rollback for managed Mod directories."""

import os
import shutil
import tempfile
import time
import uuid

from modules.archive_installer import (
    ArchiveInstallError,
    InstallCancelled,
    _candidate_members,
    _check_cancel,
    _copy_file,
    _sha256_file,
    _validate_member,
    inspect_zip,
)
from modules.config import APP_DIR


def update_from_zip(inspection, candidate, target_path, source_record,
                    progress_callback=None, cancel_event=None):
    """Prepare, backup, swap, and persist one managed Mod update."""
    target_path = os.path.abspath(target_path)
    if not os.path.isdir(target_path):
        raise ArchiveInstallError("待更新的 Mod 目录不存在: {}".format(target_path))
    if _sha256_file(inspection.archive_path) != inspection.archive_digest:
        raise ArchiveInstallError("更新 ZIP 在确认后发生变化，请重新下载")

    operation_parent = os.path.join(APP_DIR, "data", "staging")
    backup_parent = os.path.join(APP_DIR, "data", "backups", source_record["instance_id"])
    os.makedirs(operation_parent, exist_ok=True)
    os.makedirs(backup_parent, exist_ok=True)
    operation_dir = tempfile.mkdtemp(prefix="update-", dir=operation_parent)
    prepared = os.path.join(operation_dir, "prepared")
    pinned_archive = os.path.join(operation_dir, "source.zip")
    backup_path = os.path.join(backup_parent, str(int(time.time())))
    temp_backup = backup_path + ".partial"
    old_target = target_path + ".update-old"
    temp_target = os.path.join(
        os.path.dirname(target_path), ".efmi-update-{}".format(uuid.uuid4().hex))
    try:
        _copy_file(inspection.archive_path, pinned_archive, cancel_event)
        if _sha256_file(pinned_archive) != inspection.archive_digest:
            raise ArchiveInstallError("更新 ZIP 在确认后发生变化，请重新下载")
        pinned_inspection = inspect_zip(
            pinned_archive, archive_name=inspection.archive_name)
        pinned_candidate = next(
            (item for item in pinned_inspection.candidates
             if item.candidate_id == candidate.candidate_id), None)
        if pinned_candidate != candidate:
            raise ArchiveInstallError("更新 ZIP 在确认后发生变化，请重新下载")
        os.makedirs(prepared)
        with __import__("zipfile").ZipFile(pinned_archive, "r") as archive:
            validated = [(info, tuple(_validate_member(info))) for info in archive.infolist()]
            members = _candidate_members(validated, pinned_candidate.relative_root)
            total = max(1, len([item for item in members if not item[0].is_dir()]))
            done = 0
            for info, relative_parts in members:
                _check_cancel(cancel_event)
                if info.is_dir():
                    os.makedirs(os.path.join(prepared, *relative_parts), exist_ok=True)
                    continue
                destination = os.path.join(prepared, *relative_parts)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with archive.open(info, "r") as source, open(destination, "xb") as output:
                    while True:
                        _check_cancel(cancel_event)
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                done += 1
                if progress_callback:
                    progress_callback(done, total, "prepare")
        _check_cancel(cancel_event)

        if os.path.exists(temp_target):
            shutil.rmtree(temp_target, ignore_errors=True)
        shutil.copytree(prepared, temp_target)
        shutil.copytree(target_path, temp_backup)
        os.replace(temp_backup, backup_path)
        os.replace(target_path, old_target)
        try:
            os.replace(temp_target, target_path)
        except Exception:
            os.replace(old_target, target_path)
            raise
        shutil.rmtree(old_target, ignore_errors=True)
        _prune_backups(backup_parent, keep=1)
        return backup_path
    except Exception:
        shutil.rmtree(temp_target, ignore_errors=True)
        if os.path.exists(old_target) and not os.path.exists(target_path):
            os.replace(old_target, target_path)
        shutil.rmtree(temp_backup, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(operation_dir, ignore_errors=True)


def restore_backup(source_record):
    """Restore the newest backup for one source record with a safe swap."""
    target_path = os.path.abspath(source_record["path"])
    backup_dir = os.path.join(APP_DIR, "data", "backups", source_record["instance_id"])
    backups = sorted(
        os.path.join(backup_dir, item) for item in os.listdir(backup_dir)
        if os.path.isdir(os.path.join(backup_dir, item))) if os.path.isdir(backup_dir) else []
    if not backups:
        raise ArchiveInstallError("没有找到可恢复的备份")
    latest = backups[-1]
    current_backup = target_path + ".restore-current"
    restore_temp = target_path + ".restore-prepared"
    shutil.copytree(latest, restore_temp)
    os.replace(target_path, current_backup)
    try:
        os.replace(restore_temp, target_path)
    except Exception:
        os.replace(current_backup, target_path)
        raise
    shutil.rmtree(current_backup, ignore_errors=True)
    return target_path


def _prune_backups(backup_dir, keep=1):
    backups = sorted(
        (os.path.join(backup_dir, name) for name in os.listdir(backup_dir)
         if os.path.isdir(os.path.join(backup_dir, name))),
        key=os.path.getmtime, reverse=True)
    for path in backups[keep:]:
        shutil.rmtree(path, ignore_errors=True)
