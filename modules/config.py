# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - 配置管理模块
管理 JSON 配置文件：游戏路径、Mod 备注、预览图、分组等。
"""

import os
import sys
import json
import tempfile
import time


# ============================================================
# 路径常量
# ============================================================
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_DIR = get_app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "mod_manager_config.json")
CONFIG_SCHEMA_VERSION = 1
VIEW_MODES = ("compact", "card", "detailed")
VIEW_MODE_DEFAULTS = {"local": "compact", "online": "detailed", "patreon": "detailed"}


def get_data_dir():
    return os.path.join(APP_DIR, "data")


def get_patreon_profile_dir():
    return os.path.join(get_data_dir(), "patreon_profile")


def get_patreon_download_dir():
    return os.path.join(get_data_dir(), "downloads", "patreon")


def get_gb_cache_dir():
    return os.path.join(get_data_dir(), "cache", "gamebanana")


def get_gb_download_dir():
    return os.path.join(get_data_dir(), "downloads", "gamebanana")

README_NAMES = [
    "README.md",
    "README_ZH.md",
    "README_CN.md",
    "README_ZH_CN.md",
    "README_CHS.md",
    "README_TW.md",
    "README_ZH_TW.md",
    "README_CHT.md",
    "README_EN.md",
    "README_JA.md",
    "README_JP.md",
    "README_KO.md",
    "README_KR.md",
    "README.txt",
    "README_ZH.txt",
    "README_CN.txt",
    "README_ZH_CN.txt",
    "README_CHS.txt",
    "README_TW.txt",
    "README_ZH_TW.txt",
    "README_CHT.txt",
    "README_EN.txt",
    "README_JA.txt",
    "README_JP.txt",
    "README_KO.txt",
    "README_KR.txt",
]
README_LABELS = {
    "README.md": "📄 README.md",
    "README_ZH.md": "📄 README_ZH.md",
    "README_CN.md": "📄 README_CN.md",
    "README_ZH_CN.md": "📄 README_ZH_CN.md",
    "README_CHS.md": "📄 README_CHS.md",
    "README_TW.md": "📄 README_TW.md",
    "README_ZH_TW.md": "📄 README_ZH_TW.md",
    "README_CHT.md": "📄 README_CHT.md",
    "README_EN.md": "📄 README_EN.md",
    "README_JA.md": "📄 README_JA.md",
    "README_JP.md": "📄 README_JP.md",
    "README_KO.md": "📄 README_KO.md",
    "README_KR.md": "📄 README_KR.md",
    "README.txt": "📄 README.txt",
    "README_ZH.txt": "📄 README_ZH.txt",
    "README_CN.txt": "📄 README_CN.txt",
    "README_ZH_CN.txt": "📄 README_ZH_CN.txt",
    "README_CHS.txt": "📄 README_CHS.txt",
    "README_TW.txt": "📄 README_TW.txt",
    "README_ZH_TW.txt": "📄 README_ZH_TW.txt",
    "README_CHT.txt": "📄 README_CHT.txt",
    "README_EN.txt": "📄 README_EN.txt",
    "README_JA.txt": "📄 README_JA.txt",
    "README_KO.txt": "📄 README_KO.txt",
    "README_JP.txt": "📄 README_JP.txt",
    "README_KR.txt": "📄 README_KR.txt",
}


# ============================================================
# 配置文件管理
# ============================================================
class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                backup_path = "{}.corrupt-{}".format(
                    CONFIG_PATH, int(time.time()))
                try:
                    os.replace(CONFIG_PATH, backup_path)
                except OSError:
                    # Never allow a later save to overwrite unreadable user data.
                    raise OSError(
                        "配置文件已损坏且无法备份: {}".format(CONFIG_PATH))
            except IOError:
                raise
        return {}

    @staticmethod
    def save(config):
        config = dict(config)
        config.setdefault("schema_version", CONFIG_SCHEMA_VERSION)
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=".mod-manager-config-", suffix=".tmp", dir=APP_DIR)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, CONFIG_PATH)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @staticmethod
    def ensure_app_dir_writable():
        """Raise OSError when the portable application directory is read-only."""
        probe_path = None
        try:
            fd, probe_path = tempfile.mkstemp(prefix=".efmi-write-test-", dir=APP_DIR)
            os.close(fd)
        finally:
            if probe_path and os.path.exists(probe_path):
                try:
                    os.remove(probe_path)
                except OSError:
                    pass

    @staticmethod
    def get_game_path():
        return ConfigManager.load().get("game_path", "")

    @staticmethod
    def set_game_path(path):
        config = ConfigManager.load()
        config["game_path"] = path
        ConfigManager.save(config)

    @staticmethod
    def get_mod_notes():
        return ConfigManager.load().get("mod_notes", {})

    @staticmethod
    def set_mod_note(mod_name, note):
        config = ConfigManager.load()
        config.setdefault("mod_notes", {})
        if note:
            config["mod_notes"][mod_name] = note
        else:
            config["mod_notes"].pop(mod_name, None)
        ConfigManager.save(config)

    @staticmethod
    def get_mod_images():
        return ConfigManager.load().get("mod_images", {})

    @staticmethod
    def set_mod_image(mod_name, image_path):
        config = ConfigManager.load()
        config.setdefault("mod_images", {})
        if image_path:
            config["mod_images"][mod_name] = image_path
        else:
            config["mod_images"].pop(mod_name, None)
        ConfigManager.save(config)

    @staticmethod
    def get_mod_groups():
        return ConfigManager.load().get("mod_groups", {})

    @staticmethod
    def set_mod_groups(groups):
        config = ConfigManager.load()
        config["mod_groups"] = groups
        ConfigManager.save(config)

    @staticmethod
    def get_group_order():
        return ConfigManager.load().get("group_order", [])

    @staticmethod
    def set_group_order(order):
        config = ConfigManager.load()
        config["group_order"] = order
        ConfigManager.save(config)

    @staticmethod
    def get_collapsed_groups():
        return ConfigManager.load().get("collapsed_groups", [])

    @staticmethod
    def set_collapsed_groups(lst):
        config = ConfigManager.load()
        config["collapsed_groups"] = lst
        ConfigManager.save(config)

    @staticmethod
    def get_language():
        return ConfigManager.load().get("language", "auto")

    @staticmethod
    def set_language(lang):
        config = ConfigManager.load()
        config["language"] = lang
        ConfigManager.save(config)

    @staticmethod
    def get_view_mode(source="local"):
        if source not in VIEW_MODE_DEFAULTS:
            raise ValueError("source must be 'local' or 'online'")
        config = ConfigManager.load()
        modes = config.get("view_modes")
        if isinstance(modes, dict) and source in modes:
            mode = modes[source]
        elif source == "local":
            mode = {"list": "compact", "card": "card"}.get(
                config.get("view_mode"), VIEW_MODE_DEFAULTS[source])
        else:
            mode = VIEW_MODE_DEFAULTS[source]
        return mode if mode in VIEW_MODES else VIEW_MODE_DEFAULTS[source]

    @staticmethod
    def set_view_mode(source, mode=None):
        # A one-argument call remains the local setter for existing callers.
        if mode is None:
            mode = source
            source = "local"
            mode = {"list": "compact", "card": "card"}.get(mode, mode)
        if source not in VIEW_MODE_DEFAULTS:
            raise ValueError("source must be 'local' or 'online'")
        if mode not in VIEW_MODES:
            return False
        config = ConfigManager.load()
        modes = config.get("view_modes")
        if not isinstance(modes, dict):
            modes = {}
        modes[source] = mode
        config["view_modes"] = modes
        ConfigManager.save(config)
        return True

    @staticmethod
    def get_hide_sensitive_content():
        value = ConfigManager.load().get("hide_sensitive_content", True)
        return value if isinstance(value, bool) else True

    @staticmethod
    def set_hide_sensitive_content(hidden):
        config = ConfigManager.load()
        config["hide_sensitive_content"] = bool(hidden)
        ConfigManager.save(config)

    @staticmethod
    def get_patreon_creators():
        """已保存的 Patreon 创作者列表（campaign_id/name/url/avatar_url）。"""
        value = ConfigManager.load().get("patreon_creators")
        return value if isinstance(value, list) else []

    @staticmethod
    def set_patreon_creators(creators):
        config = ConfigManager.load()
        config["patreon_creators"] = list(creators)
        ConfigManager.save(config)

    @staticmethod
    def get_patreon_hidden_creators():
        """已屏蔽的 Patreon 创作者 campaign_id 列表。"""
        value = ConfigManager.load().get("patreon_hidden_creators")
        return value if isinstance(value, list) else []

    @staticmethod
    def set_patreon_hidden_creators(ids):
        config = ConfigManager.load()
        config["patreon_hidden_creators"] = list(ids)
        ConfigManager.save(config)

    @staticmethod
    def get_patreon_hide_unentitled():
        """是否隐藏无权限查看的帖子（未订阅付费内容）。"""
        value = ConfigManager.load().get("patreon_hide_unentitled")
        return bool(value) if isinstance(value, bool) else False

    @staticmethod
    def set_patreon_hide_unentitled(hide):
        config = ConfigManager.load()
        config["patreon_hide_unentitled"] = bool(hide)
        ConfigManager.save(config)

    @staticmethod
    def get_ai_base_url():
        """AI 翻译服务 base url（OpenAI 兼容）。"""
        return ConfigManager.load().get("ai_base_url", "")

    @staticmethod
    def set_ai_base_url(base_url):
        config = ConfigManager.load()
        config["ai_base_url"] = (base_url or "").strip()
        ConfigManager.save(config)

    @staticmethod
    def get_ai_model():
        """AI 翻译模型名称。"""
        return ConfigManager.load().get("ai_model", "")

    @staticmethod
    def set_ai_model(model):
        config = ConfigManager.load()
        config["ai_model"] = (model or "").strip()
        ConfigManager.save(config)

    @staticmethod
    def get_proxy():
        """手动代理地址（http/https），空串表示跟随系统代理。"""
        return ConfigManager.load().get("proxy", "").strip()

    @staticmethod
    def set_proxy(proxy):
        config = ConfigManager.load()
        config["proxy"] = (proxy or "").strip()
        ConfigManager.save(config)

    @staticmethod
    def get_gb_category_i18n_url():
        value = ConfigManager.load().get("gb_category_i18n_url")
        return value if isinstance(value, str) and value.strip() else ""

    @staticmethod
    def set_gb_category_i18n_url(url):
        config = ConfigManager.load()
        if url and url.strip():
            config["gb_category_i18n_url"] = url.strip()
        else:
            config.pop("gb_category_i18n_url", None)
        ConfigManager.save(config)

    @staticmethod
    def cleanup_mod_data(valid_mod_names):
        config = ConfigManager.load()
        changed = False
        for key in ("mod_notes", "mod_images"):
            if key in config:
                old = dict(config[key])
                config[key] = {k: v for k, v in old.items() if k in valid_mod_names}
                if len(config[key]) != len(old):
                    changed = True
        if "mod_groups" in config:
            old_groups = dict(config["mod_groups"])
            new_groups = {}
            for gname, mods in old_groups.items():
                filtered = [m for m in mods if m in valid_mod_names]
                new_groups[gname] = filtered  # 保留空分组
            if new_groups != old_groups:
                config["mod_groups"] = new_groups
                changed = True
            # 同步清理 group_order 中已不存在的分组名
            if "group_order" in config:
                old_order = list(config["group_order"])
                new_order = [g for g in old_order if g in new_groups]
                if new_order != old_order:
                    config["group_order"] = new_order
                    changed = True
        if changed:
            ConfigManager.save(config)
