# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - Mod 操作模块
Mod 扫描、启用/禁用（文件夹移动）、README 检测等。
"""

import os
import shutil
from modules.config import README_NAMES
from modules.i18n import t


class ModManager:
    def __init__(self, game_path):
        self.game_path = game_path
        self.mods_dir = os.path.join(game_path, "Mods") if game_path else ""
        self.disabled_dir = os.path.join(game_path, "Disabled_Mods") if game_path else ""

    def validate(self):
        """返回 (is_valid, error_message, created_disabled)"""
        if not self.game_path:
            return False, t("validate.no_path", "未设置游戏路径"), False
        if not os.path.isdir(self.game_path):
            return False, t("validate.path_not_exist", "游戏路径不存在"), False
        # Mods 文件夹必须存在
        if not os.path.isdir(self.mods_dir):
            return False, t("validate.no_mods_dir", "游戏路径中未找到 Mods 文件夹，请确认路径是否正确"), False
        # Disabled_Mods 不存在则自动创建
        created_disabled = False
        if not os.path.isdir(self.disabled_dir):
            os.makedirs(self.disabled_dir, exist_ok=True)
            created_disabled = True
            # 确保 Mods 也存在（理论上已检查过，但做个保护）
            os.makedirs(self.mods_dir, exist_ok=True)
        return True, "", created_disabled

    def scan_mods(self):
        mods = []
        if os.path.isdir(self.mods_dir):
            for name in sorted(os.listdir(self.mods_dir)):
                full = os.path.join(self.mods_dir, name)
                if os.path.isdir(full):
                    mods.append({"name": name, "enabled": True, "path": full})
        if os.path.isdir(self.disabled_dir):
            for name in sorted(os.listdir(self.disabled_dir)):
                full = os.path.join(self.disabled_dir, name)
                if os.path.isdir(full):
                    mods.append({"name": name, "enabled": False, "path": full})
        return mods

    def check_readme_files(self, mod_name, enabled):
        base = self.mods_dir if enabled else self.disabled_dir
        mod_path = os.path.join(base, mod_name)
        results = []
        for fname in README_NAMES:
            fpath = os.path.join(mod_path, fname)
            if os.path.isfile(fpath):
                results.append((fname, fpath))
        return results

    def open_file(self, filepath):
        if os.path.isfile(filepath):
            os.startfile(filepath)

    def toggle_mod(self, mod_name, currently_enabled, progress_callback=None):
        if currently_enabled:
            src = os.path.join(self.mods_dir, mod_name)
            dst = os.path.join(self.disabled_dir, mod_name)
        else:
            src = os.path.join(self.disabled_dir, mod_name)
            dst = os.path.join(self.mods_dir, mod_name)
        if not os.path.exists(src):
            raise FileNotFoundError(t("toggle.src_not_found", "Mod 文件夹不存在: {path}").format(path=src))
        if os.path.exists(dst):
            raise FileExistsError(t("toggle.dst_exists", "目标位置已存在同名 Mod: {path}").format(path=dst))
        self._move_with_progress(src, dst, progress_callback)

    def toggle_mods_batch(self, mod_list, enable, progress_callback=None,
                          file_progress_callback=None):
        results = []
        total_mods = len(mod_list)
        for idx, mod in enumerate(mod_list):
            if mod["enabled"] == enable:
                results.append((mod["name"], True, ""))
                if progress_callback:
                    progress_callback(idx + 1, total_mods,
                                      t("progress.already_state", "{name} (已处于目标状态)").format(name=mod['name']))
                continue
            try:
                self.toggle_mod(mod["name"], mod["enabled"], file_progress_callback)
                results.append((mod["name"], True, ""))
                if progress_callback:
                    progress_callback(idx + 1, total_mods, f"{mod['name']} ✓")
            except Exception as e:
                results.append((mod["name"], False, str(e)))
                if progress_callback:
                    progress_callback(idx + 1, total_mods, f"{mod['name']} ✗: {e}")
        return results

    def _move_with_progress(self, src, dst, progress_callback=None):
        total_files = 0
        total_bytes = 0
        for root, dirs, files in os.walk(src):
            total_files += len(files)
            for f in files:
                try:
                    total_bytes += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        if progress_callback:
            progress_callback(0, total_files, total_bytes, t("progress.preparing", "准备移动..."))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.rename(src, dst)
            if progress_callback:
                progress_callback(total_files, total_files, total_bytes, t("progress.complete", "完成！"))
            return
        except OSError:
            pass
        copied_files = 0
        for root, dirs, files in os.walk(src):
            rel_path = os.path.relpath(root, src)
            dst_root = os.path.join(dst, rel_path) if rel_path != "." else dst
            os.makedirs(dst_root, exist_ok=True)
            for f in files:
                src_file = os.path.join(root, f)
                dst_file = os.path.join(dst_root, f)
                shutil.copy2(src_file, dst_file)
                copied_files += 1
                if progress_callback and total_files > 0:
                    progress_callback(copied_files, total_files, 0,
                                      t("progress.moving", "移动中... {copied}/{total} 个文件").format(copied=copied_files, total=total_files))
        shutil.rmtree(src)
        if progress_callback:
            progress_callback(total_files, total_files, total_bytes, t("progress.complete", "完成！"))

    def open_mod_folder(self, mod_name, enabled):
        base = self.mods_dir if enabled else self.disabled_dir
        path = os.path.join(base, mod_name)
        if os.path.isdir(path):
            os.startfile(path)