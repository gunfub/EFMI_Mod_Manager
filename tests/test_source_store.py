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


def test_unknown_extension_sniffs_content_format(tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)

    target = save_gamebanana_cover(
        FakeFetcher(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"),
        "https://images.patreonusercontent.com/1/abc123",
        str(mod_path), "MyMod")

    assert target == str(mod_path / ".efmi_mod_manager" / "cover.png")
    assert (mod_path / ".efmi_mod_manager" / "cover.png").is_file()
    stored = config.ConfigManager.get_mod_images()["MyMod"]
    assert stored == ".efmi_mod_manager" + os.sep + "cover.png"


@pytest.mark.parametrize("content,expected", [
    (b"\xff\xd8\xff\xe0jpeg-bytes", ".jpg"),
    (b"GIF89a\x01\x00\x01\x00", ".gif"),
    (b"RIFF\x10\x00\x00\x00WEBPVP8 ", ".webp"),
    (b"BM\x36\x00\x00\x00", ".bmp"),
])
def test_sniffs_various_image_formats(tmp_path, isolated_config, content, expected):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)

    target = save_gamebanana_cover(
        FakeFetcher(content), "https://images.patreonusercontent.com/1/abc123",
        str(mod_path), "MyMod")

    assert target == str(mod_path / ".efmi_mod_manager" / ("cover" + expected))


def test_unknown_extension_unknown_content_falls_back_to_jpg(tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyMod"
    mod_path.mkdir(parents=True)

    target = save_gamebanana_cover(
        FakeFetcher(b"not-an-image"), "https://images.patreonusercontent.com/1/abc123",
        str(mod_path), "MyMod")

    assert target == str(mod_path / ".efmi_mod_manager" / "cover.jpg")
    assert (mod_path / ".efmi_mod_manager" / "cover.jpg").is_file()


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
