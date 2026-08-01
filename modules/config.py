# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - 配置管理模块
管理 JSON 配置文件：游戏路径、Mod 备注、预览图、分组等。
"""

import os
import sys
import json


# ============================================================
# 路径常量
# ============================================================
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_DIR = get_app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "mod_manager_config.json")

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
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    @staticmethod
    def save(config):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

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
    def get_view_mode():
        mode = ConfigManager.load().get("view_mode", "list")
        return mode if mode in ("list", "card") else "list"

    @staticmethod
    def set_view_mode(mode):
        if mode not in ("list", "card"):
            return
        config = ConfigManager.load()
        config["view_mode"] = mode
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
