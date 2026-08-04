import json
import zipfile

import pytest

from modules import update_manager
from modules.archive_installer import InstallSelection, inspect_zip
from modules.update_manager import restore_backup, update_from_zip


def make_zip(path, content):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Updated/main.ini", content)


def test_update_backs_up_and_replaces(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(update_manager, "APP_DIR", str(app_dir))
    archive = tmp_path / "update.zip"
    make_zip(archive, b"new")
    inspection = inspect_zip(str(archive))
    target = tmp_path / "Mods" / "Managed"
    target.mkdir(parents=True)
    (target / "main.ini").write_bytes(b"old")
    record = {"instance_id": "one", "path": str(target)}

    backup = update_from_zip(inspection, inspection.candidates[0], str(target), record)

    assert (target / "main.ini").read_bytes() == b"new"
    assert (tmp_path / "app" / "data" / "backups" / "one").is_dir()
    assert (tmp_path / "app" / "data" / "backups" / "one" / backup.split("\\")[-1] / "main.ini").read_bytes() == b"old"


def test_restore_backup_restores_previous_content(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(update_manager, "APP_DIR", str(app_dir))
    target = tmp_path / "Mods" / "Managed"
    target.mkdir(parents=True)
    (target / "main.ini").write_bytes(b"old")
    record = {"instance_id": "two", "path": str(target)}
    archive = tmp_path / "update.zip"
    make_zip(archive, b"new")
    inspection = inspect_zip(str(archive))
    update_from_zip(inspection, inspection.candidates[0], str(target), record)

    restore_backup(record)

    assert (target / "main.ini").read_bytes() == b"old"


def test_update_rejects_archive_replaced_after_inspection(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(update_manager, "APP_DIR", str(app_dir))
    archive = tmp_path / "update.zip"
    make_zip(archive, b"new")
    inspection = inspect_zip(str(archive))
    make_zip(archive, b"replaced")
    target = tmp_path / "Mods" / "Managed"
    target.mkdir(parents=True)
    (target / "main.ini").write_bytes(b"old")

    with pytest.raises(Exception, match="发生变化"):
        update_from_zip(
            inspection, inspection.candidates[0], str(target),
            {"instance_id": "three", "path": str(target)})

    assert (target / "main.ini").read_bytes() == b"old"
