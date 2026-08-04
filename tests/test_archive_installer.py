import json
import os
import stat
import zipfile

import pytest

from modules import archive_installer
from modules.archive_installer import (
    ArchiveInstallError,
    InstallCancelled,
    InstallSelection,
    inspect_zip,
    install_zip,
    unique_target_name,
    validate_mod_name,
)


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)


def test_single_wrapper_directory_becomes_one_candidate(tmp_path):
    archive_path = tmp_path / "example.zip"
    make_zip(archive_path, [
        ("Cool Mod/main.ini", b"ini"),
        ("Cool Mod/Textures/a.dds", b"texture"),
    ])

    inspection = inspect_zip(str(archive_path))

    assert inspection.file_count == 2
    assert len(inspection.candidates) == 1
    candidate = inspection.candidates[0]
    assert candidate.suggested_name == "Cool Mod"
    assert candidate.relative_root == "Cool Mod"


def test_multiple_top_directories_become_separate_candidates(tmp_path):
    archive_path = tmp_path / "bundle.zip"
    make_zip(archive_path, [
        ("First/main.ini", b"1"),
        ("Second/main.ini", b"2"),
    ])

    inspection = inspect_zip(str(archive_path))

    assert [item.suggested_name for item in inspection.candidates] == ["First", "Second"]


def test_root_file_keeps_archive_as_single_candidate(tmp_path):
    archive_path = tmp_path / "Root Bundle.zip"
    make_zip(archive_path, [
        ("README.txt", b"readme"),
        ("First/main.ini", b"1"),
    ])

    inspection = inspect_zip(str(archive_path))

    assert len(inspection.candidates) == 1
    assert inspection.candidates[0].suggested_name == "Root Bundle"
    assert inspection.candidates[0].relative_root == "."


@pytest.mark.parametrize("unsafe_name", [
    "../escape.txt",
    "/absolute.txt",
    "C:/drive.txt",
    "safe/../../escape.txt",
    "safe/CON/file.txt",
    "safe/trailing./file.txt",
])
def test_rejects_unsafe_member_paths(tmp_path, unsafe_name):
    archive_path = tmp_path / "unsafe.zip"
    make_zip(archive_path, [(unsafe_name, b"bad")])

    with pytest.raises(ArchiveInstallError):
        inspect_zip(str(archive_path))


def test_rejects_symlink_member(tmp_path):
    archive_path = tmp_path / "link.zip"
    info = zipfile.ZipInfo("Mod/link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "../../outside")

    with pytest.raises(ArchiveInstallError, match="链接"):
        inspect_zip(str(archive_path))


def test_rejects_case_insensitive_collision(tmp_path):
    archive_path = tmp_path / "collision.zip"
    make_zip(archive_path, [
        ("Mod/File.ini", b"1"),
        ("mod/file.INI", b"2"),
    ])

    with pytest.raises(ArchiveInstallError, match="冲突"):
        inspect_zip(str(archive_path))


def test_installs_selected_candidate_and_writes_manifest(tmp_path, monkeypatch):
    archive_path = tmp_path / "bundle.zip"
    make_zip(archive_path, [
        ("First/main.ini", b"first"),
        ("Second/main.ini", b"second"),
    ])
    game = tmp_path / "game"
    mods = game / "Mods"
    disabled = game / "Disabled_Mods"
    mods.mkdir(parents=True)
    disabled.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))
    inspection = inspect_zip(str(archive_path))
    selection = InstallSelection(inspection.candidates[1], "Chosen", enabled=False)

    results = install_zip(inspection, [selection], str(mods), str(disabled))

    assert len(results) == 1
    assert results[0].success
    installed = disabled / "Chosen"
    assert (installed / "main.ini").read_bytes() == b"second"
    assert not (installed / "Second").exists()
    manifest = json.loads(
        (installed / ".efmi_mod_manager" / "source.json").read_text(encoding="utf-8"))
    assert manifest["provider"] == "local"
    assert manifest["folder_name"] == "Chosen"


def test_rejects_existing_name_in_either_mod_root(tmp_path, monkeypatch):
    archive_path = tmp_path / "mod.zip"
    make_zip(archive_path, [("Mod/main.ini", b"ini")])
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    (disabled / "Taken").mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))
    inspection = inspect_zip(str(archive_path))

    with pytest.raises(ArchiveInstallError, match="同名"):
        install_zip(
            inspection,
            [InstallSelection(inspection.candidates[0], "Taken")],
            str(mods), str(disabled))


def test_cancel_cleans_staging_and_hidden_target(tmp_path, monkeypatch):
    archive_path = tmp_path / "mod.zip"
    make_zip(archive_path, [("Mod/main.ini", b"content")])
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))
    inspection = inspect_zip(str(archive_path))

    class CancelDuringTargetCopy:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls >= 6

    with pytest.raises(InstallCancelled):
        install_zip(
            inspection,
            [InstallSelection(inspection.candidates[0], "Cancelled")],
            str(mods), str(disabled),
            cancel_event=CancelDuringTargetCopy())

    assert not (mods / "Cancelled").exists()
    assert not list(mods.glob(".efmi-install-*"))
    staging = app_dir / "data" / "staging"
    assert not staging.exists() or not list(staging.glob("install-*"))


def test_unique_target_name_checks_both_roots(tmp_path):
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    (mods / "Name").mkdir()
    (disabled / "Name (2)").mkdir()

    assert unique_target_name("Name", [str(mods), str(disabled)]) == "Name (3)"


def test_rejects_same_planned_name_across_enabled_states(tmp_path, monkeypatch):
    archive_path = tmp_path / "bundle.zip"
    make_zip(archive_path, [
        ("First/main.ini", b"1"),
        ("Second/main.ini", b"2"),
    ])
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))
    inspection = inspect_zip(str(archive_path))

    with pytest.raises(ArchiveInstallError, match="相同目标名称"):
        install_zip(
            inspection,
            [
                InstallSelection(inspection.candidates[0], "Same", enabled=True),
                InstallSelection(inspection.candidates[1], "Same", enabled=False),
            ],
            str(mods), str(disabled))


def test_rejects_archive_replaced_after_inspection(tmp_path, monkeypatch):
    archive_path = tmp_path / "mod.zip"
    make_zip(archive_path, [("Mod/main.ini", b"original")])
    inspection = inspect_zip(str(archive_path))
    make_zip(archive_path, [
        ("Mod/main.ini", b"replacement"),
        ("Mod/extra.ini", b"unexpected"),
    ])
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))

    with pytest.raises(ArchiveInstallError, match="发生变化"):
        install_zip(
            inspection,
            [InstallSelection(inspection.candidates[0], "Mod")],
            str(mods), str(disabled))

    assert not (mods / "Mod").exists()


def test_root_file_archive_keeps_original_name_during_install(tmp_path, monkeypatch):
    archive_path = tmp_path / "Root Bundle.zip"
    make_zip(archive_path, [
        ("README.txt", b"readme"),
        ("Nested/main.ini", b"content"),
    ])
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))
    inspection = inspect_zip(str(archive_path))

    results = install_zip(
        inspection,
        [InstallSelection(inspection.candidates[0], "Root Bundle")],
        str(mods), str(disabled))

    assert results[0].success
    assert (mods / "Root Bundle" / "README.txt").is_file()
    assert (mods / "Root Bundle" / "Nested" / "main.ini").is_file()


def test_commit_failure_rolls_back_all_candidates(tmp_path, monkeypatch):
    archive_path = tmp_path / "bundle.zip"
    make_zip(archive_path, [
        ("First/main.ini", b"1"),
        ("Second/main.ini", b"2"),
    ])
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))
    inspection = inspect_zip(str(archive_path))
    real_replace = archive_installer.os.replace

    def fail_second_commit(source, destination):
        if destination == str(mods / "Second"):
            raise OSError("injected commit failure")
        return real_replace(source, destination)

    monkeypatch.setattr(archive_installer.os, "replace", fail_second_commit)

    with pytest.raises(ArchiveInstallError, match="已回滚"):
        install_zip(
            inspection,
            [
                InstallSelection(inspection.candidates[0], "First"),
                InstallSelection(inspection.candidates[1], "Second"),
            ],
            str(mods), str(disabled))

    assert not (mods / "First").exists()
    assert not (mods / "Second").exists()
    assert not list(mods.glob(".efmi-install-*"))


def test_cancel_from_final_progress_prevents_commit(tmp_path, monkeypatch):
    archive_path = tmp_path / "mod.zip"
    make_zip(archive_path, [("Mod/main.ini", b"content")])
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(archive_installer, "APP_DIR", str(app_dir))
    inspection = inspect_zip(str(archive_path))

    class CancelEvent:
        cancelled = False

        def is_set(self):
            return self.cancelled

    cancel = CancelEvent()

    def progress(current, total, _name):
        if current == total:
            cancel.cancelled = True

    with pytest.raises(InstallCancelled):
        install_zip(
            inspection,
            [InstallSelection(inspection.candidates[0], "Cancelled")],
            str(mods), str(disabled),
            progress_callback=progress,
            cancel_event=cancel)

    assert not (mods / "Cancelled").exists()
    assert not list(mods.glob(".efmi-install-*"))


@pytest.mark.parametrize("name", ["COM¹", "COM².txt", "LPT³"])
def test_validate_mod_name_rejects_superscript_device_names(name):
    with pytest.raises(ArchiveInstallError, match="保留名称"):
        validate_mod_name(name)


@pytest.mark.parametrize("name", ["", " CON", "bad/name", "bad.", "bad?"])
def test_validate_mod_name_rejects_invalid_names(name):
    with pytest.raises(ArchiveInstallError):
        validate_mod_name(name)
