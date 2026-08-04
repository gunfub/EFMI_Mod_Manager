import os

from PIL import Image, ImageOps

from modules.local_preview_cache import LocalPreviewCache


def _make_image(path, color=(200, 20, 30), size=(80, 40)):
    Image.new("RGB", size, color).save(path)


def test_cache_matches_existing_fit_and_persists(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    cache_dir = tmp_path / "cache"
    _make_image(source)
    target = (30, 30)

    cache = LocalPreviewCache(str(cache_dir))
    first = cache.load(str(source), target)
    with Image.open(source) as original:
        expected = ImageOps.fit(
            original.convert("RGB"), target, method=Image.LANCZOS)

    assert first.size == target
    assert first.tobytes() == expected.tobytes()
    assert len(list(cache_dir.glob("*.png"))) == 1
    assert not list(cache_dir.glob(".local-preview-*.tmp"))

    def fail_source(_path, _target):
        raise AssertionError("disk cache should avoid opening the source image")

    second_cache = LocalPreviewCache(str(cache_dir))
    monkeypatch.setattr(second_cache, "_load_source", fail_source)
    second = second_cache.load(str(source), target)
    assert second.tobytes() == first.tobytes()


def test_cache_invalidates_for_source_change_and_target_size(tmp_path):
    source = tmp_path / "source.png"
    cache_dir = tmp_path / "cache"
    _make_image(source, color=(255, 0, 0))
    cache = LocalPreviewCache(str(cache_dir))

    red = cache.load(str(source), (20, 20))
    _make_image(source, color=(0, 0, 255), size=(81, 40))
    os.utime(source, None)
    blue = cache.load(str(source), (20, 20))
    wide = cache.load(str(source), (30, 20))

    assert red.getpixel((10, 10)) == (255, 0, 0)
    assert blue.getpixel((10, 10)) == (0, 0, 255)
    assert wide.size == (30, 20)
    assert len(list(cache_dir.glob("*.png"))) == 3


def test_corrupt_disk_cache_falls_back_to_source(tmp_path):
    source = tmp_path / "source.png"
    cache_dir = tmp_path / "cache"
    _make_image(source)
    cache = LocalPreviewCache(str(cache_dir))
    cache.load(str(source), (20, 20))
    cache_file = next(cache_dir.glob("*.png"))
    cache_file.write_bytes(b"broken")

    fresh_cache = LocalPreviewCache(str(cache_dir))
    recovered = fresh_cache.load(str(source), (20, 20))

    assert recovered is not None
    with Image.open(cache_file) as image:
        assert image.size == (20, 20)


def test_missing_or_broken_source_returns_none(tmp_path):
    cache = LocalPreviewCache(str(tmp_path / "cache"))
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")

    assert cache.load(str(tmp_path / "missing.png"), (20, 20)) is None
    assert cache.load(str(broken), (20, 20)) is None
