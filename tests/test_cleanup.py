# -*- coding: utf-8 -*-
"""缓存清理模块测试（临时目录，不触碰真实 data）。"""

import os

from modules.cleanup import (
    clean_all,
    clean_target,
    cleanup_targets,
    format_size,
    measure_all,
    measure_target,
)


def _make_target(tmp_path, name, files):
    """在 tmp_path/name 下创建 files: {相对路径: 字节数}，返回目标 dict。"""
    root = tmp_path / name
    root.mkdir(parents=True)
    for rel, size in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return {"key": name, "label_key": name, "paths": [str(root)], "patterns": ()}


def test_measure_target_and_clean(tmp_path):
    target = _make_target(tmp_path, "cache_a", {
        "a.png": 100,
        "sub/b.png": 200,
        "sub/deep/c.png": 300,
    })
    assert measure_target(target) == 600

    freed, failed = clean_target(target)
    assert freed == 600
    assert failed == 0
    assert measure_target(target) == 0
    assert os.path.isdir(str(tmp_path / "cache_a"))  # 目录本身保留


def test_clean_target_keeps_missing_dirs(tmp_path):
    target = {"key": "x", "label_key": "x",
              "paths": [str(tmp_path / "not_exist")], "patterns": ()}
    assert measure_target(target) == 0
    assert clean_target(target) == (0, 0)


def test_patterns_only_match_suffixes(tmp_path):
    root = tmp_path / "dl"
    root.mkdir()
    (root / "keep.zip").write_bytes(b"a" * 50)
    (root / "a.part").write_bytes(b"b" * 30)
    (root / "b.crdownload").write_bytes(b"c" * 20)
    (root / "c.tmp").write_bytes(b"d" * 10)
    target = {"key": "t", "label_key": "t", "paths": [str(root)],
              "patterns": (".part", ".crdownload", ".tmp")}
    assert measure_target(target) == 60
    freed, failed = clean_target(target)
    assert (freed, failed) == (60, 0)
    assert (root / "keep.zip").exists()
    assert not (root / "a.part").exists()


def test_clean_all_returns_per_key(tmp_path):
    a = _make_target(tmp_path, "a", {"f1": 10})
    b = _make_target(tmp_path, "b", {"f2": 20})
    results = clean_all([a, b])
    assert results["a"] == (10, 0)
    assert results["b"] == (20, 0)


def test_measure_all(tmp_path):
    a = _make_target(tmp_path, "a", {"f1": 10})
    b = _make_target(tmp_path, "b", {"f2": 20})
    assert measure_all([a, b]) == {"a": 10, "b": 20}


def test_cleanup_targets_shape(monkeypatch, tmp_path):
    monkeypatch.setattr("modules.cleanup.get_data_dir", lambda: str(tmp_path))
    targets = cleanup_targets()
    assert len(targets) == 5
    keys = {t["key"] for t in targets}
    assert keys == {"gb_cache", "patreon_images", "local_previews",
                    "patreon_browser", "downloads_temp"}
    for target in targets:
        assert target["label_key"].startswith("cleanup.")
        assert isinstance(target["paths"], list)
        assert all(isinstance(p, str) for p in target["paths"])
        assert isinstance(target["patterns"], tuple)


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(2048) == "2.0 KB"
    assert format_size(3 * 1024 * 1024) == "3.0 MB"
    assert format_size(2.5 * 1024 * 1024 * 1024) == "2.5 GB"
