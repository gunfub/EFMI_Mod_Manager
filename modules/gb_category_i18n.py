# -*- coding: utf-8 -*-
"""GameBanana 分类名翻译（独立翻译文件，手动热更新）。

- 内置文件随软件分发（离线兜底），路径与 GitHub 仓库中一致：
  locales/category_translations/gb_category_names.json
- 更新完全手动：点击在线浏览页的「更新分类翻译」按钮时从 GitHub
  raw 拉取最新翻译；启动时只读本地文件，绝不自动联网。
- 翻译缺失（分类 ID 未收录，或该语言没有键）时回退英文原名。
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

import httpx

from modules.config import APP_DIR

BUNDLED_PATH = os.path.join(
    APP_DIR, "locales", "category_translations", "gb_category_names.json")
CACHE_PATH = os.path.join(APP_DIR, "data", "cache", "gb_category_names.json")
DEFAULT_URL = ("https://raw.githubusercontent.com/gunfub/EFMI_Mod_Manager/"
               "main/locales/category_translations/gb_category_names.json")
ALLOWED_HOST = "raw.githubusercontent.com"
MAX_BYTES = 1024 * 1024
TIMEOUT = 20.0


class GBCategoryI18n:
    """分类名翻译字典（category_id -> {lang: name}），线程安全读取。"""

    def __init__(self, bundled_path=BUNDLED_PATH, cache_path=CACHE_PATH,
                 url=DEFAULT_URL):
        self._bundled_path = bundled_path
        self._cache_path = cache_path
        self.url = url
        self._data: Dict[str, Dict[str, str]] = {}
        self.load()

    def load(self):
        """读取本地翻译：上次更新缓存优先，其次内置文件，失败则为空。"""
        for path in (self._cache_path, self._bundled_path):
            data = self._read_file(path)
            if data is not None:
                self._data = data
                return
        self._data = {}

    def refresh(self, client=None):
        """从 GitHub 拉取最新翻译并热切换；失败返回错误信息，不抛异常。"""
        host_ok = False
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.url)
            host_ok = parsed.scheme == "https" and parsed.hostname == ALLOWED_HOST
        except Exception:
            host_ok = False
        if not host_ok:
            return "翻译下载地址不受信任: {}".format(self.url)
        own_client = client is None
        if own_client:
            client = httpx.Client(
                timeout=TIMEOUT, headers={"User-Agent": "EFMI-Mod-Manager/1.0"})
        try:
            chunks = []
            size = 0
            with client.stream("GET", self.url, follow_redirects=False) as response:
                if response.status_code != 200:
                    return "翻译下载失败: HTTP {}".format(response.status_code)
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        return "翻译文件超过允许大小"
                    chunks.append(chunk)
            data = json.loads(b"".join(chunks).decode("utf-8"))
            if not isinstance(data, dict):
                return "翻译文件格式错误"
            for key, value in data.items():
                if not isinstance(value, dict) or not all(
                        isinstance(v, str) for v in value.values()):
                    return "翻译文件格式错误"
            self._data = data
            self._write_cache(data)
            return None
        except (httpx.HTTPError, ValueError, OSError) as exc:
            return "翻译更新失败: {}".format(exc)
        finally:
            if own_client:
                client.close()

    def translate(self, category_id, name, lang):
        """返回翻译；分类未收录或该语言无键时回退英文原名。"""
        entry = self._data.get(str(category_id))
        if entry and lang in entry:
            return entry[lang]
        return name

    def _read_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return None
            for key, value in payload.items():
                if not isinstance(value, dict) or not all(
                        isinstance(v, str) for v in value.values()):
                    return None
            return payload
        except (OSError, ValueError):
            return None

    def _write_cache(self, data):
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            temp_path = self._cache_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(temp_path, self._cache_path)
        except OSError:
            pass
