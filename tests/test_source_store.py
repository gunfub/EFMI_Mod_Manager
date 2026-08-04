import os

import pytest

from modules import config
from modules.source_store import save_gamebanana_cover


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))
    return config_path


class FakeFetcher:
    def __init__(self, content=b"\x89PNG-cov"):
        self.content = content
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.content


def test_saves_cover_and_sets_relative_preview(
        tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)
    fetcher = FakeFetcher()

    target = save_gamebanana_cover(
        fetcher, "https://images.gamebanana.com/img/ss/mods/123.png",
        str(mod_path), "MyMod")

    assert fetcher.calls == [
        "https://images.gamebanana.com/img/ss/mods/123.png"]
    assert target == str(mod_path / ".efmi_mod_manager" / "cover.png")
    assert (mod_path / ".efmi_mod_manager" / "cover.png").read_bytes() == fetcher.content
    stored = config.ConfigManager.get_mod_images()["MyMod"]
    assert os.path.normpath(os.path.join(str(mod_path), stored)) == target
    assert not list((mod_path / ".efmi_mod_manager").glob("cover.png.tmp"))


def test_skips_when_preview_already_set(tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)
    config.ConfigManager.set_mod_image("MyMod", "custom.jpg")
    fetcher = FakeFetcher()

    result = save_gamebanana_cover(
        fetcher, "https://images.gamebanana.com/img/ss/mods/123.png",
        str(mod_path), "MyMod")

    assert result is None
    assert fetcher.calls == []
    assert config.ConfigManager.get_mod_images()["MyMod"] == "custom.jpg"


def test_overwrite_replaces_existing_cover(tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)
    cover = mod_path / ".efmi_mod_manager" / "cover.png"
    cover.parent.mkdir()
    cover.write_bytes(b"old")
    fetcher = FakeFetcher(b"new")

    target = save_gamebanana_cover(
        fetcher, "https://images.gamebanana.com/img/ss/mods/123.png",
        str(mod_path), "MyMod", overwrite=True)

    assert target == str(cover)
    assert cover.read_bytes() == b"new"


def test_unknown_extension_falls_back_to_jpg(tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)

    target = save_gamebanana_cover(
        FakeFetcher(), "https://images.gamebanana.com/img/ss/mods/123",
        str(mod_path), "MyMod")

    assert target == str(mod_path / ".efmi_mod_manager" / "cover.jpg")
    assert (mod_path / ".efmi_mod_manager" / "cover.jpg").is_file()
    stored = config.ConfigManager.get_mod_images()["MyMod"]
    assert stored == ".efmi_mod_manager" + os.sep + "cover.jpg"


@pytest.mark.parametrize("extension", [".png", ".jpeg", ".gif", ".webp", ".bmp"])
def test_keeps_known_extensions(tmp_path, isolated_config, extension):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)

    target = save_gamebanana_cover(
        FakeFetcher(), "https://images.gamebanana.com/img/ss/mods/123{}".format(extension),
        str(mod_path), "MyMod")

    assert target == str(mod_path / ".efmi_mod_manager" / ("cover" + extension))


def test_fetch_failure_raises_and_leaves_no_file(tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)

    def fail(_url):
        raise OSError("network down")

    with pytest.raises(OSError, match="network down"):
        save_gamebanana_cover(
            fail, "https://images.gamebanana.com/img/ss/mods/123.png",
            str(mod_path), "MyMod")

    assert not (mod_path / ".efmi_mod_manager" / "cover.png").exists()
