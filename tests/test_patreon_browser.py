# -*- coding: utf-8 -*-
"""Patreon 浏览页轻量测试（不创建 Tk 窗口、不触网）。"""

from modules.catalog_view import CARD, COMPACT, DETAILED, VIEW_MODE_ORDER
from modules.config import VIEW_MODE_DEFAULTS, VIEW_MODES
from modules.patreon_browser import (
    COMPACT_PREVIEW,
    DETAILED_PREVIEW,
    filter_posts_by_access,
    split_creators_by_hidden,
)


def test_preview_sizes_are_16_9():
    for size in (COMPACT_PREVIEW, DETAILED_PREVIEW):
        ratio = size[0] / float(size[1])
        assert abs(ratio - 16.0 / 9.0) / (16.0 / 9.0) < 0.005, size


def test_patreon_view_mode_default_and_order():
    assert VIEW_MODE_DEFAULTS["patreon"] == DETAILED
    assert set(VIEW_MODE_ORDER) == {COMPACT, DETAILED, CARD}
    assert set(VIEW_MODE_ORDER) <= set(VIEW_MODES)


def test_frame_class_importable():
    from modules.patreon_browser import PatreonBrowserFrame
    assert callable(PatreonBrowserFrame)


def test_saved_creators_config_roundtrip(tmp_path, monkeypatch):
    from modules import config
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    creators = [{"campaign_id": 1, "name": "Creator A", "url": "", "avatar_url": None}]
    config.ConfigManager.set_patreon_creators(creators)
    assert config.ConfigManager.get_patreon_creators() == creators


def test_hidden_creators_config_roundtrip(tmp_path, monkeypatch):
    from modules import config
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.get_patreon_hidden_creators() == []
    config.ConfigManager.set_patreon_hidden_creators(["14830458", "999999"])
    assert config.ConfigManager.get_patreon_hidden_creators() == [
        "14830458", "999999"]


def test_split_creators_by_hidden():
    creators = [
        {"campaign_id": 111111, "name": "A"},
        {"campaign_id": 14830458, "name": "DannTheMann"},
        {"campaign_id": "222222", "name": "C"},
    ]
    visible, blocked = split_creators_by_hidden(creators, [111111, "222222"])
    assert [c["name"] for c in visible] == ["DannTheMann"]
    assert [c["name"] for c in blocked] == ["A", "C"]

    visible, blocked = split_creators_by_hidden(creators, [])
    assert len(visible) == 3
    assert blocked == []


def test_hide_unentitled_config_roundtrip(tmp_path, monkeypatch):
    from modules import config
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.get_patreon_hide_unentitled() is False
    config.ConfigManager.set_patreon_hide_unentitled(True)
    assert config.ConfigManager.get_patreon_hide_unentitled() is True
    config.ConfigManager.set_patreon_hide_unentitled(False)
    assert config.ConfigManager.get_patreon_hide_unentitled() is False


def test_filter_posts_by_access():
    posts = [
        {"post_id": "p1", "can_view": True},
        {"post_id": "p2", "can_view": False},
        {"post_id": "p3", "can_view": True},
        {"post_id": "p4"},
    ]
    assert [p["post_id"] for p in filter_posts_by_access(posts, True)] == [
        "p1", "p3"]
    assert filter_posts_by_access(posts, False) is posts
    assert filter_posts_by_access([], True) == []


def test_patreon_view_mode_config_roundtrip(tmp_path, monkeypatch):
    from modules import config
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.get_view_mode("patreon") == DETAILED
    assert config.ConfigManager.set_view_mode("patreon", CARD) is True
    assert config.ConfigManager.get_view_mode("patreon") == CARD
