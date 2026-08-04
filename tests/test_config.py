import json
import os

import pytest

from modules import config


def test_atomic_save_replaces_config_and_leaves_no_temp_file(tmp_path, monkeypatch):
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    config.ConfigManager.save({"game_path": "C:/Game"})

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["game_path"] == "C:/Game"
    assert saved["schema_version"] == config.CONFIG_SCHEMA_VERSION
    assert not list(tmp_path.glob(".mod-manager-config-*.tmp"))


def test_writable_probe_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))

    config.ConfigManager.ensure_app_dir_writable()

    assert not list(tmp_path.glob(".efmi-write-test-*"))


def test_writable_probe_raises_for_missing_directory(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setattr(config, "APP_DIR", str(missing))

    with pytest.raises(OSError):
        config.ConfigManager.ensure_app_dir_writable()


def test_atomic_save_failure_preserves_old_config(tmp_path, monkeypatch):
    config_path = tmp_path / "mod_manager_config.json"
    config_path.write_text('{"game_path": "old"}', encoding="utf-8")
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(config.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected"):
        config.ConfigManager.save({"game_path": "new"})

    assert config_path.read_text(encoding="utf-8") == '{"game_path": "old"}'
    assert not list(tmp_path.glob(".mod-manager-config-*.tmp"))


def test_corrupt_config_is_preserved_before_returning_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "mod_manager_config.json"
    config_path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    loaded = config.ConfigManager.load()

    assert loaded == {}
    assert not config_path.exists()
    backups = list(tmp_path.glob("mod_manager_config.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{broken"


@pytest.mark.parametrize(
    ("legacy", "expected"), [("list", "compact"), ("card", "card")])
def test_legacy_local_view_mode_migrates_on_read(
        tmp_path, monkeypatch, legacy, expected):
    config_path = tmp_path / "mod_manager_config.json"
    config_path.write_text(json.dumps({"view_mode": legacy}), encoding="utf-8")
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.get_view_mode("local") == expected
    assert config.ConfigManager.get_view_mode("online") == "detailed"


@pytest.mark.parametrize("mode", ["compact", "card", "detailed"])
def test_local_and_online_view_modes_are_saved_independently(
        tmp_path, monkeypatch, mode):
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.set_view_mode("local", mode)
    assert config.ConfigManager.set_view_mode("online", "detailed")

    assert config.ConfigManager.get_view_mode("local") == mode
    assert config.ConfigManager.get_view_mode("online") == "detailed"
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["view_modes"] == {"local": mode, "online": "detailed"}


def test_invalid_view_mode_falls_back_without_overwriting_other_config(
        tmp_path, monkeypatch):
    config_path = tmp_path / "mod_manager_config.json"
    config_path.write_text(json.dumps({
        "game_path": "C:/Game",
        "view_modes": {"local": "invalid", "online": "compact"},
    }), encoding="utf-8")
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.get_view_mode("local") == "compact"
    assert config.ConfigManager.get_view_mode("online") == "compact"
    assert not config.ConfigManager.set_view_mode("local", "invalid")
    assert config.ConfigManager.load()["game_path"] == "C:/Game"


def test_sensitive_content_setting_defaults_true_and_persists(
        tmp_path, monkeypatch):
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.get_hide_sensitive_content() is True
    config.ConfigManager.set_hide_sensitive_content(False)
    assert config.ConfigManager.get_hide_sensitive_content() is False
