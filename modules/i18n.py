# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - 多语言模块
自动检测系统语言，加载 JSON 翻译文件。
中文为源代码语言（无需 JSON），其他语言通过 locales/xx.json 翻译。
"""

import os
import sys
import json
import locale
import ctypes


def _get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _detect_system_language():
    """通过系统 API 检测用户界面语言，返回语言代码或 None。"""
    if sys.platform == "win32":
        try:
            windll = ctypes.windll.kernel32
            lang_id = windll.GetUserDefaultUILanguage()
            primary = lang_id & 0x3FF
            if primary == 0x04:
                return "zh"
            if primary == 0x09:
                return "en"
            if primary == 0x11:
                return "ja"
            if primary == 0x12:
                return "ko"
        except Exception:
            pass

    try:
        sys_locale = locale.getdefaultlocale()[0]
        if sys_locale:
            if sys_locale.startswith("zh"):
                return "zh"
            if sys_locale.startswith("en"):
                return "en"
            if sys_locale.startswith("ja"):
                return "ja"
            if sys_locale.startswith("ko"):
                return "ko"
    except Exception:
        pass

    return None


class _SimpleNamespace:
    """支持点号访问的字典包装器，用于 JSON 键值路径解析。"""

    def __init__(self, data):
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, _SimpleNamespace(value))
            else:
                setattr(self, key, value)

    def get(self, key, default=None):
        return getattr(self, key, default) if hasattr(self, key) else default


class I18n:
    """多语言管理器（单例）。

    用法:
        i18n = I18n()
        i18n.set_language("auto")  # 或 "zh", "en"
        text = i18n.t("top.subtitle", "|  Mod 管理器")
    """

    def __init__(self):
        self._app_dir = _get_app_dir()
        self._locales_dir = os.path.join(self._app_dir, "locales")
        self._available = {}
        self._translations = _SimpleNamespace({})
        self._lang = "auto"
        self._effective = "zh"
        self._callbacks = []

        self._scan_locales()
        self.set_language(self._lang)

    def _scan_locales(self):
        """扫描 locales/ 目录下可用的翻译文件。"""
        self._available.clear()
        if os.path.isdir(self._locales_dir):
            for fname in os.listdir(self._locales_dir):
                if fname.endswith(".json"):
                    code = fname[:-5]
                    self._available[code] = os.path.join(self._locales_dir, fname)

    def set_language(self, lang):
        """
        设置语言。
        lang: "auto" (自动检测) / "zh" / "en" / ...
        返回 True 表示语言发生了实际变化。
        """
        old_effective = self._effective

        if lang == "auto":
            detected = _detect_system_language()
            if detected and detected in self._available:
                self._effective = detected
            elif detected == "zh":
                self._effective = "zh"
            else:
                self._effective = "en" if "en" in self._available else "zh"
        else:
            self._effective = lang

        self._lang = lang

        changed = (self._effective != old_effective)
        if changed:
            self._load_translations()
            for cb in self._callbacks:
                cb()
        elif not hasattr(self._translations, "__initialized"):
            self._load_translations()

        return changed

    def _load_translations(self):
        """加载当前有效语言的 JSON 翻译文件。"""
        if self._effective == "zh":
            self._translations = _SimpleNamespace({})
        elif self._effective in self._available:
            try:
                with open(self._available[self._effective], "r", encoding="utf-8") as f:
                    self._translations = _SimpleNamespace(json.load(f))
            except (json.JSONDecodeError, IOError):
                self._translations = _SimpleNamespace({})
        else:
            self._translations = _SimpleNamespace({})

        object.__setattr__(self._translations, "__initialized", True)

    def t(self, key, zh_default):
        """
        获取翻译文本。
        key: 点号分隔的 JSON 路径，如 "top.subtitle"
        zh_default: 中文原文（中文模式下直接返回）
        """
        if self._effective == "zh":
            return zh_default

        parts = key.split(".")
        node = self._translations
        for part in parts:
            if isinstance(node, _SimpleNamespace):
                node = node.get(part)
            else:
                return zh_default
            if node is None:
                return zh_default
        return node if isinstance(node, str) else zh_default

    def on_language_changed(self, callback):
        """注册语言变更回调。"""
        self._callbacks.append(callback)

    @property
    def lang(self):
        """用户设置的语言代码（"auto", "zh", "en" 等）。"""
        return self._lang

    @property
    def effective_lang(self):
        """实际生效的语言代码（"zh", "en" 等）。"""
        return self._effective

    @property
    def available(self):
        """所有可用的语言代码列表。"""
        return list(self._available.keys())


_i18n = None


def init_i18n():
    """初始化全局 i18n 单例。"""
    global _i18n
    _i18n = I18n()
    return _i18n


def get_i18n():
    """获取全局 i18n 单例（未初始化时自动创建）。"""
    global _i18n
    if _i18n is None:
        _i18n = I18n()
    return _i18n


def t(key, zh_default):
    """快捷翻译函数。"""
    return get_i18n().t(key, zh_default)
