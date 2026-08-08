# -*- coding: utf-8 -*-
"""缓存/垃圾清理：按类别统计占用与清理（多选式，不影响登录态）。

每个可清理类别 = 若干目录（清空内容但保留目录本身，避免各缓存模块
依赖目录存在）+ 可选的文件后缀模式（如下载临时残留 *.part）。
Patreon 浏览器清理仅删除 WebView2 的纯缓存子目录，不触碰
Network/Cookies 等登录态数据。
"""

import os

from modules.config import get_data_dir

_TEMP_SUFFIXES = (".part", ".crdownload", ".tmp")

# Patreon 浏览器（WebView2 profile）中纯缓存子目录；
# 不包含 Network（Cookies）、Local Storage、Session Storage 等数据目录
_PATREON_WEBVIEW_CACHE_DIRS = (
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnGraphiteCache",
    "Default/DawnWebGPUCache",
    "Default/Shared Dictionary",
    "ShaderCache",
    "GrShaderCache",
    "GraphiteDawnCache",
    "BrowserMetrics",
    "component_crx_cache",
    "Crashpad",
)


def cleanup_targets():
    """可清理类别列表。每项含 key / label_key / paths / patterns。"""
    data = get_data_dir()
    return [
        {
            "key": "gb_cache",
            "label_key": "cleanup.gb_cache",
            "paths": [os.path.join(data, "cache", "gamebanana")],
            "patterns": (),
        },
        {
            "key": "patreon_images",
            "label_key": "cleanup.patreon_images",
            "paths": [
                os.path.join(data, "cache", "patreon_raw"),
                os.path.join(data, "cache", "patreon_thumbs"),
            ],
            "patterns": (),
        },
        {
            "key": "local_previews",
            "label_key": "cleanup.local_previews",
            "paths": [os.path.join(data, "cache", "local_previews")],
            "patterns": (),
        },
        {
            "key": "patreon_browser",
            "label_key": "cleanup.patreon_browser",
            "paths": [
                os.path.join(data, "patreon_profile", "EBWebView", name)
                for name in _PATREON_WEBVIEW_CACHE_DIRS
            ],
            "patterns": (),
        },
        {
            "key": "downloads_temp",
            "label_key": "cleanup.downloads_temp",
            "paths": [os.path.join(data, "downloads")],
            "patterns": _TEMP_SUFFIXES,
        },
    ]


def _iter_files(paths, patterns):
    """遍历目标内的文件；patterns 非空时仅匹配其后缀。"""
    for path in paths:
        if not os.path.isdir(path):
            continue
        for root, _dirs, files in os.walk(path):
            for name in files:
                full = os.path.join(root, name)
                if not patterns or name.lower().endswith(patterns):
                    yield full


def measure_target(target):
    """统计单个目标占用字节数。"""
    total = 0
    for full in _iter_files(target["paths"], target["patterns"]):
        try:
            total += os.path.getsize(full)
        except OSError:
            pass
    return total


def measure_all(targets):
    """统计所有目标，返回 {key: 字节数}。"""
    return {target["key"]: measure_target(target) for target in targets}


def clean_target(target):
    """清理单个目标，返回 (释放字节数, 失败文件数)。目录本身保留。"""
    freed = 0
    failed = 0
    for full in _iter_files(target["paths"], target["patterns"]):
        try:
            size = os.path.getsize(full)
            os.remove(full)
            freed += size
        except OSError:
            failed += 1
    return freed, failed


def clean_all(targets):
    """清理所选目标，返回 {key: (释放字节数, 失败文件数)}。"""
    return {
        target["key"]: clean_target(target)
        for target in targets
    }


def format_size(value):
    """人类可读大小（B/KB/MB/GB/TB）。"""
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return "{:.0f} B".format(value)
            return "{:.1f} {}".format(value, unit)
        value /= 1024
    return "{:.1f} B".format(value)
