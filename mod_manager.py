# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - Windows PC Mod Manager
管理 Mods / Disabled_Mods 文件夹中的 Mod，通过移动文件夹来启用/禁用
GUI 基于 customtkinter
"""

import os
import sys
import json
import shutil
import threading
import warnings
from tkinter import messagebox, filedialog, simpledialog

# ---- 抑制 PyInstaller 环境下 pkg_resources 的弃用警告 ----
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

import customtkinter as ctk
from customtkinter import CTkImage

# PIL 用于预览图片
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ============================================================
# 路径工具：兼容 pyinstaller 与直接运行 py
# ============================================================
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = get_app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "mod_manager_config.json")

README_NAMES = ["README.md", "README_ZH.md", "README.txt", "README_ZH.txt"]
README_LABELS = {
    "README.md": "📄 README.md",
    "README_ZH.md": "📄 README_ZH.md",
    "README.txt": "📄 README.txt",
    "README_ZH.txt": "📄 README_ZH.txt",
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


# ============================================================
# Mod 扫描与管理逻辑
# ============================================================
class ModManager:
    def __init__(self, game_path):
        self.game_path = game_path
        self.mods_dir = os.path.join(game_path, "Mods") if game_path else ""
        self.disabled_dir = os.path.join(game_path, "Disabled_Mods") if game_path else ""

    def validate(self):
        """返回 (is_valid, error_message, created_disabled)"""
        if not self.game_path:
            return False, "未设置游戏路径", False
        if not os.path.isdir(self.game_path):
            return False, "游戏路径不存在", False
        # Mods 文件夹必须存在
        if not os.path.isdir(self.mods_dir):
            return False, "游戏路径中未找到 Mods 文件夹，请确认路径是否正确", False
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
            raise FileNotFoundError(f"Mod 文件夹不存在: {src}")
        if os.path.exists(dst):
            raise FileExistsError(f"目标位置已存在同名 Mod: {dst}")
        self._move_with_progress(src, dst, progress_callback)

    def toggle_mods_batch(self, mod_list, enable, progress_callback=None,
                          file_progress_callback=None):
        results = []
        total_mods = len(mod_list)
        for idx, mod in enumerate(mod_list):
            if mod["enabled"] == enable:
                results.append((mod["name"], True, ""))
                if progress_callback:
                    progress_callback(idx + 1, total_mods, f"{mod['name']} (已处于目标状态)")
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
            progress_callback(0, total_files, total_bytes, "准备移动...")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.rename(src, dst)
            if progress_callback:
                progress_callback(total_files, total_files, total_bytes, "完成！")
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
                                      f"移动中... {copied_files}/{total_files} 个文件")
        shutil.rmtree(src)
        if progress_callback:
            progress_callback(total_files, total_files, total_bytes, "完成！")

    def open_mod_folder(self, mod_name, enabled):
        base = self.mods_dir if enabled else self.disabled_dir
        path = os.path.join(base, mod_name)
        if os.path.isdir(path):
            os.startfile(path)


# ============================================================
# 主窗口 UI
# ============================================================
class ModManagerApp:
    PREVIEW_SIZE = 48

    def __init__(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("EFMI Mod Manager")
        self.root.geometry("1120x740")
        self.root.minsize(960, 520)

        # 禁用 Ctrl+G 切换主题
        self.root.bind("<Control-g>", lambda e: "break")
        self.root.bind("<Control-G>", lambda e: "break")

        self.mod_manager = None
        self.mods_data = []
        self.is_operating = False
        self._checkbox_vars = {}  # mod_name -> ctk.BooleanVar
        self._group_checkbox_vars = {}  # group_name -> ctk.BooleanVar
        self._group_headers = {}  # group_name -> header frame
        self._group_contents = {}  # group_name -> content frame
        self._group_first_mod = {}  # group_name -> first mod name (for A-Z scroll)
        self._mod_to_group = {}  # mod_name -> group_name
        self._mod_rows = {}  # mod_name -> row widgets dict
        self._alphabet_index = {}  # letter -> first mod_name
        self._preview_ctk_images = {}  # mod_name -> CTkImage

        # 动态 DPI 缩放
        self._dpi_scale = self._get_dpi_scale_factor()

        self._build_ui()
        self._load_config_and_refresh()

    # ============================================================
    # DPI 动态缩放
    # ============================================================
    def _get_dpi_scale_factor(self):
        """获取 Windows DPI 缩放因子（96 DPI = 1.0, 144 DPI = 1.5 等）

        注意：不能把 HDC 传给 MonitorFromWindow（需要 HWND），
        这里先尝试获取 TK 窗口 HWND，若未就绪则回退到主显示器 DPI。
        """
        try:
            import ctypes
            user32 = ctypes.windll.user32
            shcore = ctypes.windll.shcore

            # 方法1：通过 Tk 窗口 HWND 获取所在显示器 DPI（最准确）
            hwnd = None
            try:
                hwnd = self.root.winfo_id()  # 返回 HWND
            except Exception:
                pass

            if hwnd:
                monitor = user32.MonitorFromWindow(hwnd, 0)  # MONITOR_DEFAULTTONEAREST
                if monitor:
                    dpi_x = ctypes.c_uint()
                    dpi_y = ctypes.c_uint()
                    result = shcore.GetDpiForMonitor(
                        monitor, 0,  # MDT_EFFECTIVE_DPI = 0
                        ctypes.byref(dpi_x), ctypes.byref(dpi_y))
                    if result == 0:  # S_OK
                        scale = dpi_x.value / 96.0
                        return max(0.8, min(scale, 3.0))

            # 方法2：回退 - 获取主显示器 DPI
            hdc = user32.GetDC(0)
            if hdc:
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX = 88
                user32.ReleaseDC(0, hdc)
                if dpi and dpi > 0:
                    scale = dpi / 96.0
                    return max(0.8, min(scale, 3.0))

            return 1.0
        except Exception:
            return 1.0

    def _font(self, base_size, weight=None):
        """根据 DPI 缩放因子计算字体，基础字号以 100% 缩放 (96 DPI) 为基准"""
        scaled = max(5, int(base_size * self._dpi_scale))
        kwargs = {"size": scaled}
        if weight:
            kwargs["weight"] = weight
        return ctk.CTkFont(**kwargs)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        # ---- 顶部栏 ----
        top_frame = ctk.CTkFrame(self.root, height=56, corner_radius=0)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)

        title_label = ctk.CTkLabel(
            top_frame, text="EFMI Mod Manager",
            font=self._font(20, weight="bold")
        )
        title_label.pack(side="left", padx=(20, 10), pady=12)

        subtitle_label = ctk.CTkLabel(
            top_frame, text="|  Mod 管理器",
            font=self._font(12),
            text_color="gray"
        )
        subtitle_label.pack(side="left", padx=(0, 20), pady=12)

        self.path_label = ctk.CTkLabel(
            top_frame, text="未选择文件夹",
            font=self._font(11),
            text_color="gray"
        )
        self.path_label.pack(side="right", padx=(0, 10), pady=12)

        refresh_btn = ctk.CTkButton(
            top_frame, text="🔄 刷新", width=70, height=30,
            font=self._font(11),
            command=self._refresh
        )
        refresh_btn.pack(side="right", padx=(0, 8), pady=12)
        self._refresh_btn = refresh_btn

        browse_btn = ctk.CTkButton(
            top_frame, text="📁 选择文件夹", width=110, height=30,
            font=self._font(11),
            command=self._browse_folder
        )
        browse_btn.pack(side="right", padx=(0, 8), pady=12)
        self._browse_btn = browse_btn

        # ---- 工具栏 ----
        toolbar = ctk.CTkFrame(self.root, height=42, corner_radius=0,
                               fg_color=("gray90", "gray17"))
        toolbar.pack(fill="x", padx=0, pady=(0, 0))
        toolbar.pack_propagate(False)

        toolbar_inner = ctk.CTkFrame(toolbar, fg_color=("gray90", "gray17"))
        toolbar_inner.pack(side="left", fill="y", padx=14, pady=4)

        ctk.CTkLabel(toolbar_inner, text="选择:",
                     font=self._font(11)).pack(side="left", padx=(0, 6))

        ctk.CTkButton(toolbar_inner, text="全选", width=50, height=26,
                      font=self._font(10),
                      command=self._select_all).pack(side="left", padx=2)
        ctk.CTkButton(toolbar_inner, text="反选", width=50, height=26,
                      font=self._font(10),
                      command=self._invert_selection).pack(side="left", padx=2)
        ctk.CTkButton(toolbar_inner, text="不选", width=50, height=26,
                      font=self._font(10),
                      command=self._deselect_all).pack(side="left", padx=2)

        sep1 = ctk.CTkFrame(toolbar_inner, width=1, height=22, fg_color="gray40")
        sep1.pack(side="left", padx=10)

        ctk.CTkLabel(toolbar_inner, text="操作:",
                     font=self._font(11)).pack(side="left", padx=(0, 6))

        ctk.CTkButton(toolbar_inner, text="批量启用", width=70, height=26,
                      font=self._font(10), fg_color="#2ea043",
                      hover_color="#3fb950",
                      command=lambda: self._batch_toggle(True)).pack(side="left", padx=2)
        ctk.CTkButton(toolbar_inner, text="批量禁用", width=70, height=26,
                      font=self._font(10), fg_color="#da3633",
                      hover_color="#f85149",
                      command=lambda: self._batch_toggle(False)).pack(side="left", padx=2)

        sep2 = ctk.CTkFrame(toolbar_inner, width=1, height=22, fg_color="gray40")
        sep2.pack(side="left", padx=10)

        ctk.CTkButton(toolbar_inner, text="➕ 新建分组", width=80, height=26,
                      font=self._font(10),
                      command=self._create_group).pack(side="left", padx=2)
        ctk.CTkButton(toolbar_inner, text="✏️ 管理分组", width=80, height=26,
                      font=self._font(10),
                      command=self._manage_groups).pack(side="left", padx=2)

        # ---- 主体区域 ----
        body = ctk.CTkFrame(self.root, fg_color=("gray95", "gray14"))
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Mod 列表（可滚动）
        self.scroll_frame = ctk.CTkScrollableFrame(body, label_text="")
        self.scroll_frame.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=0)

        # A-Z 侧边栏
        self._build_alphabet_bar(body)

        # ---- 底部状态栏 ----
        self.status_bar = ctk.CTkFrame(self.root, height=28, corner_radius=0,
                                       fg_color=("gray85", "gray20"))
        self.status_bar.pack(fill="x", side="bottom", padx=0, pady=0)
        self.status_bar.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            self.status_bar, text="",
            font=self._font(11),
            text_color="gray"
        )
        self.status_label.pack(side="left", padx=16, pady=2)

        # 进度条（默认隐藏）
        self.progress_frame = ctk.CTkFrame(self.root, height=32, corner_radius=0,
                                           fg_color=("gray95", "gray14"))

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, width=300, height=12)
        self.progress_bar.set(0)

        self.progress_text = ctk.CTkLabel(
            self.progress_frame, text="",
            font=self._font(10)
        )

    def _build_alphabet_bar(self, parent):
        """构建 A-Z 快速跳转侧边栏"""
        alpha_frame = ctk.CTkFrame(parent, width=28, corner_radius=0,
                                   fg_color=("gray90", "gray14"))
        alpha_frame.pack(side="right", fill="y", padx=0, pady=0)
        alpha_frame.pack_propagate(False)

        self._alpha_frame = alpha_frame
        self._alpha_buttons = {}

        # 先显示空状态
        placeholder = ctk.CTkLabel(
            alpha_frame, text="", font=self._font(6)
        )
        placeholder.pack()

        self._alpha_placeholder = placeholder

    def _rebuild_alphabet_bar(self):
        """根据当前 Mod 重建字母侧边栏"""
        for widget in self._alpha_frame.winfo_children():
            widget.destroy()
        self._alpha_buttons.clear()
        self._alphabet_index.clear()

        # 按显示名称排序所有 Mod
        notes = ConfigManager.get_mod_notes()
        sorted_mods = sorted(self.mods_data, key=lambda m: (notes.get(m["name"], "") or m["name"]).lower())

        # 建立字母索引
        last_letter = None
        for mod in sorted_mods:
            display = (notes.get(mod["name"], "") or mod["name"]).strip()
            if display:
                first_char = display[0].upper()
                if 'A' <= first_char <= 'Z':
                    if first_char not in self._alphabet_index:
                        self._alphabet_index[first_char] = mod["name"]
                elif not last_letter:
                    # 非字母开头归到 #
                    if '#' not in self._alphabet_index:
                        self._alphabet_index['#'] = mod["name"]

        # 生成 A-Z 按钮
        all_letters = [chr(i) for i in range(ord('A'), ord('Z') + 1)]
        if '#' in self._alphabet_index:
            all_letters.insert(0, '#')

        for letter in all_letters:
            has_mod = letter in self._alphabet_index
            btn = ctk.CTkButton(
                self._alpha_frame,
                text=letter,
                width=22,
                height=20,
                font=self._font(9),
                corner_radius=2,
                fg_color=("gray95", "gray14") if not has_mod else ("gray70", "gray25"),
                text_color="gray50" if not has_mod else ("gray20", "gray90"),
                hover_color=("gray60", "gray35") if has_mod else ("gray95", "gray14"),
                command=lambda l=letter: self._scroll_to_letter(l) if l in self._alphabet_index else None,
            )
            btn.pack(pady=1, padx=3)
            self._alpha_buttons[letter] = btn

    def _scroll_to_letter(self, letter):
        """滚动到对应字母的第一个 Mod"""
        if letter not in self._alphabet_index:
            return
        mod_name = self._alphabet_index[letter]
        row_info = self._mod_rows.get(mod_name)
        if not row_info:
            return
        widget = row_info.get("row_frame")
        if widget and widget.winfo_exists():
            # 使用 CTkScrollableFrame 的内部 canvas 滚动
            canvas = self.scroll_frame._parent_canvas
            # 获取 widget 在 canvas 中的位置
            bbox = canvas.bbox("all")
            if bbox:
                widget_y = widget.winfo_rooty() - canvas.winfo_rooty()
                total_h = bbox[3] - bbox[1]
                if total_h > 0:
                    fraction = max(0, min(1, widget_y / total_h))
                    canvas.yview_moveto(fraction)

    # ============================================================
    # 选择文件夹 / 刷新
    # ============================================================
    def _browse_folder(self):
        path = filedialog.askdirectory(title="选择游戏 Mod 文件夹（包含 Mods 和 Disabled_Mods 的目录）")
        if path:
            ConfigManager.set_game_path(path)
            self._load_config_and_refresh()

    def _load_config_and_refresh(self):
        game_path = ConfigManager.get_game_path()
        if game_path:
            self.path_label.configure(text=os.path.basename(game_path) or game_path)
        self._refresh()

    def _refresh(self):
        game_path = ConfigManager.get_game_path()
        if not game_path:
            self._show_empty_state("请先选择一个包含 Mods 文件夹的游戏目录")
            return

        self.mod_manager = ModManager(game_path)
        valid, msg, created_disabled = self.mod_manager.validate()
        if not valid:
            self._show_empty_state(msg)
            return

        self.mods_data = self.mod_manager.scan_mods()
        valid_names = {m["name"] for m in self.mods_data}
        ConfigManager.cleanup_mod_data(valid_names)

        self._render_mod_list()
        self._update_stats()
        self._rebuild_alphabet_bar()

        # 通知用户 Disabled_Mods 已自动创建
        if created_disabled:
            self.root.after(100, lambda: messagebox.showinfo(
                "提示",
                "检测到游戏目录中没有 Disabled_Mods 文件夹，已自动创建。\n\n"
                "路径: " + self.mod_manager.disabled_dir
            ))

    def _show_empty_state(self, message):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._checkbox_vars.clear()
        self._group_checkbox_vars.clear()
        self._group_headers.clear()
        self._group_contents.clear()
        self._group_first_mod.clear()
        self._mod_to_group.clear()
        self._mod_rows.clear()
        self._alphabet_index.clear()
        self._preview_ctk_images.clear()
        self.mods_data = []

        label = ctk.CTkLabel(
            self.scroll_frame, text=message,
            font=self._font(13),
            text_color="gray"
        )
        label.pack(pady=60)
        self.status_label.configure(text="")

    # ============================================================
    # 渲染 Mod 列表（带分组、折叠、复选框）
    # ============================================================
    def _render_mod_list(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._checkbox_vars.clear()
        self._group_checkbox_vars.clear()
        self._group_headers.clear()
        self._group_contents.clear()
        self._group_first_mod.clear()
        self._mod_to_group.clear()
        self._mod_rows.clear()
        self._preview_ctk_images.clear()

        if not self.mods_data:
            ctk.CTkLabel(
                self.scroll_frame, text="没有找到任何 Mod 文件夹",
                font=self._font(13), text_color="gray"
            ).pack(pady=60)
            return

        groups = ConfigManager.get_mod_groups()
        order = ConfigManager.get_group_order()
        collapsed = set(ConfigManager.get_collapsed_groups())
        notes = ConfigManager.get_mod_notes()
        images = ConfigManager.get_mod_images()

        mod_by_name = {m["name"]: m for m in self.mods_data}
        assigned = set()

        # 过滤 order 中已经不存在的分组名（防止 KeyError）
        ordered_groups = [g for g in order if g in groups]
        other_groups = [g for g in groups if g not in ordered_groups]

        for gname in ordered_groups + other_groups:
            mods_in_group = []
            if gname not in groups:
                continue  # group_order 中有但 mod_groups 中已不存在，跳过
            for mod_name in groups[gname]:
                if mod_name in mod_by_name:
                    mods_in_group.append(mod_by_name[mod_name])
                    assigned.add(mod_name)
            if mods_in_group:
                self._create_group_section(gname, mods_in_group, notes, images,
                                           is_collapsed=(gname in collapsed))

        # 未分组
        unassigned = [m for m in self.mods_data if m["name"] not in assigned]
        if unassigned:
            self._create_group_section("未分组", unassigned, notes, images,
                                       is_collapsed=("未分组" in collapsed))

    def _create_group_section(self, gname, mods, notes, images, is_collapsed=False):
        # ---- 分组标题栏 ----
        header = ctk.CTkFrame(
            self.scroll_frame, height=36, corner_radius=6,
            fg_color=("gray85", "gray20")
        )
        header.pack(fill="x", padx=2, pady=(10, 2))
        header.pack_propagate(False)

        # 折叠箭头
        arrow = "▶" if is_collapsed else "▼"
        collapse_btn = ctk.CTkButton(
            header, text=arrow, width=26, height=26,
            font=self._font(10),
            fg_color=("gray85", "gray20"),
            hover_color=("gray75", "gray28"),
            text_color=("gray30", "gray80"),
        )
        collapse_btn.pack(side="left", padx=(4, 2))

        # 分组复选框
        group_var = ctk.BooleanVar(value=False)
        self._group_checkbox_vars[gname] = group_var
        group_cb = ctk.CTkCheckBox(
            header, text="",
            checkbox_width=18, checkbox_height=18,
            width=18,
            command=lambda g=gname: self._on_group_checkbox_toggle(g),
            variable=group_var,
            onvalue=True, offvalue=False,
        )
        group_cb.pack(side="left", padx=(2, 6))

        # 分组名称
        name_label = ctk.CTkLabel(
            header, text=f"📁 {gname}",
            font=self._font(12, weight="bold")
        )
        name_label.pack(side="left")

        # Mod 数量
        count_label = ctk.CTkLabel(
            header, text=f"({len(mods)} 个)",
            font=self._font(10),
            text_color="gray"
        )
        count_label.pack(side="left", padx=(6, 0))

        self._group_headers[gname] = header

        # ---- 分组内容区 ----
        content = ctk.CTkFrame(self.scroll_frame, fg_color=("gray95", "gray14"))
        if not is_collapsed:
            content.pack(fill="x", padx=2, pady=0)

        self._group_contents[gname] = content

        # 第一个 Mod 用于 A-Z 跳转
        if mods:
            self._group_first_mod[gname] = mods[0]["name"]

        # Mod 行
        for mod in mods:
            self._mod_to_group[mod["name"]] = gname
            self._create_mod_row(content, mod, notes.get(mod["name"], ""),
                                 images.get(mod["name"], ""))

        # 绑定折叠按钮
        collapse_btn.configure(
            command=lambda g=gname, btn=collapse_btn:
            self._toggle_group_collapse(g, btn)
        )

    def _toggle_group_collapse(self, gname, btn):
        content = self._group_contents.get(gname)
        if not content:
            return

        collapsed_list = ConfigManager.get_collapsed_groups()
        if content.winfo_manager():
            # 当前展开 → 折叠
            content.pack_forget()
            btn.configure(text="▶")
            if gname not in collapsed_list:
                collapsed_list.append(gname)
        else:
            # 当前折叠 → 展开
            header = self._group_headers.get(gname)
            if header:
                content.pack(after=header, fill="x", padx=2, pady=0)
            else:
                content.pack(fill="x", padx=2, pady=0)
            btn.configure(text="▼")
            if gname in collapsed_list:
                collapsed_list.remove(gname)

        ConfigManager.set_collapsed_groups(collapsed_list)

    def _create_mod_row(self, parent, mod, note, image_path):
        name = mod["name"]
        enabled = mod["enabled"]

        row = ctk.CTkFrame(parent, height=44, corner_radius=4,
                           fg_color=("gray95", "gray13"))
        row.pack(fill="x", padx=2, pady=2)
        row.pack_propagate(False)

        # ---- 复选框 ----
        var = ctk.BooleanVar(value=False)
        self._checkbox_vars[name] = var
        cb = ctk.CTkCheckBox(
            row, text="",
            checkbox_width=18, checkbox_height=18,
            width=18,
            variable=var,
            onvalue=True, offvalue=False,
            command=lambda n=name: self._on_mod_checkbox_toggle(n),
        )
        cb.pack(side="left", padx=(8, 4))

        # ---- 预览图 ----
        if image_path and HAS_PIL and os.path.isfile(image_path):
            try:
                img = Image.open(image_path)
                img.thumbnail((self.PREVIEW_SIZE, self.PREVIEW_SIZE), Image.LANCZOS)
                ctk_img = CTkImage(light_image=img, dark_image=img,
                                   size=(self.PREVIEW_SIZE, self.PREVIEW_SIZE))
                self._preview_ctk_images[name] = ctk_img
                preview_label = ctk.CTkLabel(row, image=ctk_img, text="",
                                             cursor="hand2")
                preview_label.pack(side="left", padx=(0, 6))
                # 绑定点击 → 全屏查看原图
                preview_label.bind("<Button-1>",
                                   lambda e, p=image_path: self._show_full_image(p))
                # 同时给内部 label 也绑定（customtkinter 的 CTkLabel 是 tk.Label 子类）
                for child in preview_label.winfo_children():
                    child.bind("<Button-1>",
                               lambda e, p=image_path: self._show_full_image(p))
                preview_label._image_path = image_path
            except Exception:
                pass

        # ---- 名称区域 ----
        name_frame = ctk.CTkFrame(row, fg_color=("gray95", "gray13"))
        name_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        display_name = note if note else name
        name_label = ctk.CTkLabel(
            name_frame, text=display_name,
            font=self._font(12, weight="bold"),
            anchor="w"
        )
        name_label.pack(fill="x")

        original_name_label = None
        if note:
            original_name_label = ctk.CTkLabel(
                name_frame, text=name,
                font=self._font(9),
                text_color="gray",
                anchor="w"
            )
            original_name_label.pack(fill="x")

        # ---- 右侧按钮区 ----
        right_frame = ctk.CTkFrame(row, fg_color=("gray95", "gray13"))
        right_frame.pack(side="right", padx=(0, 4))

        # README 按钮
        readme_files = []
        if self.mod_manager:
            readme_files = self.mod_manager.check_readme_files(name, enabled)

        for rf_name, rf_path in readme_files:
            btn_text = README_LABELS.get(rf_name, f"📄 {rf_name}")
            r_btn = ctk.CTkButton(
                right_frame, text=btn_text,
                width=90, height=22,
                font=self._font(9),
                fg_color=("gray80", "gray25"),
                hover_color=("gray70", "gray35"),
                text_color=("gray25", "gray85"),
                command=lambda p=rf_path: self.mod_manager.open_file(p),
            )
            r_btn.pack(side="left", padx=2)

        # Switch 开关
        switch_var = ctk.BooleanVar(value=enabled)
        switch = ctk.CTkSwitch(
            right_frame, text="",
            variable=switch_var,
            onvalue=True, offvalue=False,
            width=42,
            switch_width=38, switch_height=20,
            command=lambda n=name, sv=switch_var: self._on_switch_toggled(n, sv.get()),
        )
        switch.pack(side="left", padx=(6, 4))

        # 状态文字
        status_label = ctk.CTkLabel(
            right_frame,
            text="启用" if enabled else "禁用",
            font=self._font(9),
            text_color="#3fb950" if enabled else "gray"
        )
        status_label.pack(side="left", padx=(0, 4))

        # 打开文件夹按钮
        open_btn = ctk.CTkButton(
            right_frame, text="📂",
            width=28, height=28,
            font=self._font(12),
            fg_color=("gray95", "gray13"),
            hover_color=("gray85", "gray25"),
            text_color=("gray40", "gray70"),
            command=lambda m=mod: self._open_mod_folder(m),
        )
        open_btn.pack(side="left", padx=2)

        # 更多操作按钮
        more_btn = ctk.CTkButton(
            right_frame, text="⋯",
            width=28, height=28,
            font=self._font(14, weight="bold"),
            fg_color=("gray95", "gray13"),
            hover_color=("gray85", "gray25"),
            text_color=("gray40", "gray70"),
            command=lambda m=mod, b=None: self._show_more_menu(m),
        )
        more_btn.pack(side="left", padx=2)

        self._mod_rows[name] = {
            "row_frame": row,
            "switch": switch,
            "switch_var": switch_var,
            "status_label": status_label,
            "checkbox_var": var,
            "name_label": name_label,
            "original_name_label": original_name_label,
            "mod": mod,
        }

    # ============================================================
    # 复选框逻辑
    # ============================================================
    def _on_group_checkbox_toggle(self, gname):
        """分组复选框切换 → 勾选/取消该分组所有 Mod"""
        is_checked = self._group_checkbox_vars[gname].get()
        for mod_name, var in self._checkbox_vars.items():
            # 只操作属于该分组的 Mod
            if self._mod_to_group.get(mod_name) == gname:
                var.set(is_checked)

    def _on_mod_checkbox_toggle(self, mod_name):
        """单个 Mod 复选框变化 → 同步更新分组复选框状态"""
        gname = self._mod_to_group.get(mod_name)
        if gname and gname in self._group_checkbox_vars:
            # 收集该组内所有 Mod 名（包括虚拟的"未分组"）
            group_mod_names = [
                mn for mn, g in self._mod_to_group.items()
                if g == gname
            ]
            all_checked = True
            any_checked = False
            for mn in group_mod_names:
                if mn in self._checkbox_vars:
                    v = self._checkbox_vars[mn].get()
                    if v:
                        any_checked = True
                    else:
                        all_checked = False
            group_var = self._group_checkbox_vars[gname]
            if all_checked:
                group_var.set(True)
            elif not any_checked:
                group_var.set(False)
            # 部分选中时，customtkinter 不支持三态，保持原样

    def _select_all(self):
        for var in self._checkbox_vars.values():
            var.set(True)
        self._sync_all_group_checkboxes()

    def _deselect_all(self):
        for var in self._checkbox_vars.values():
            var.set(False)
        self._sync_all_group_checkboxes()

    def _invert_selection(self):
        for var in self._checkbox_vars.values():
            var.set(not var.get())
        self._sync_all_group_checkboxes()

    def _sync_all_group_checkboxes(self):
        """同步所有分组复选框状态"""
        for gname, group_var in self._group_checkbox_vars.items():
            group_mod_names = [
                mn for mn, g in self._mod_to_group.items()
                if g == gname
            ]
            if not group_mod_names:
                group_var.set(False)
                continue
            all_checked = True
            for mn in group_mod_names:
                if mn in self._checkbox_vars:
                    if not self._checkbox_vars[mn].get():
                        all_checked = False
                        break
            group_var.set(all_checked)

    def _get_selected_mods(self):
        selected = []
        for mod_name, var in self._checkbox_vars.items():
            if var.get():
                for m in self.mods_data:
                    if m["name"] == mod_name:
                        selected.append(m)
                        break
        return selected

    # ============================================================
    # 分组管理
    # ============================================================
    def _create_group(self):
        result = simpledialog.askstring("新建分组", "输入分组名称：", parent=self.root)
        if result and result.strip():
            gname = result.strip()
            groups = ConfigManager.get_mod_groups()
            order = ConfigManager.get_group_order()
            if gname in groups:
                messagebox.showwarning("已存在", f"分组 \"{gname}\" 已存在")
                return
            groups[gname] = []
            order.append(gname)
            ConfigManager.set_mod_groups(groups)
            ConfigManager.set_group_order(order)
            self._refresh()

    def _manage_groups(self):
        groups = ConfigManager.get_mod_groups()
        order = ConfigManager.get_group_order()
        ordered_groups = [g for g in order if g in groups]
        other_groups = [g for g in groups if g not in ordered_groups]
        all_groups = ordered_groups + other_groups

        if not all_groups:
            messagebox.showinfo("提示", "当前没有任何分组，请先新建分组。")
            return

        dialog = ctk.CTkToplevel(self.root)
        dialog.title("管理分组")
        dialog.geometry("520x480")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="现有分组（点击选择）:",
            font=self._font(13, weight="bold")
        ).pack(padx=20, pady=(16, 4), anchor="w")

        # 使用 CTkScrollableFrame 来显示分组列表
        list_frame = ctk.CTkScrollableFrame(dialog, height=240)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        info_label = ctk.CTkLabel(
            dialog, text="",
            font=self._font(10),
            text_color="gray",
            wraplength=480,
            justify="left"
        )
        info_label.pack(fill="x", padx=16, pady=(2, 8))

        selected_group = [None]

        def select_group(gname):
            selected_group[0] = gname
            mods = groups.get(gname, [])
            info_label.configure(text=f"包含 Mod: {', '.join(mods) if mods else '(空)'}")
            # 高亮所有按钮
            for g, btn in group_buttons.items():
                if g == gname:
                    btn.configure(fg_color=("#3B8ED0", "#1F6AA5"))
                else:
                    btn.configure(fg_color=("gray85", "gray25"))

        group_buttons = {}
        for gname in all_groups:
            btn = ctk.CTkButton(
                list_frame, text=f"📁 {gname}  ({len(groups[gname])} Mods)",
                anchor="w",
                font=self._font(11),
                fg_color=("gray85", "gray25"),
                hover_color=("gray75", "gray35"),
                text_color=("gray20", "gray85"),
                command=lambda g=gname: select_group(g),
            )
            btn.pack(fill="x", pady=2)
            group_buttons[gname] = btn

        btn_row = ctk.CTkFrame(dialog, fg_color=("gray90", "gray17"))
        btn_row.pack(fill="x", padx=16, pady=(0, 16))

        def rename_group():
            gname = selected_group[0]
            if not gname:
                messagebox.showwarning("提示", "请先选择一个分组")
                return
            new_name = simpledialog.askstring("重命名分组", f"将 \"{gname}\" 重命名为：",
                                              parent=dialog)
            if new_name and new_name.strip() and new_name.strip() != gname:
                nn = new_name.strip()
                if nn in groups:
                    messagebox.showwarning("已存在", f"分组 \"{nn}\" 已存在")
                    return
                groups[nn] = groups.pop(gname)
                if gname in order:
                    order[order.index(gname)] = nn
                ConfigManager.set_mod_groups(groups)
                ConfigManager.set_group_order(order)
                dialog.destroy()
                self._refresh()

        def delete_group():
            gname = selected_group[0]
            if not gname:
                return
            if messagebox.askyesno("确认删除", f"确定要删除分组 \"{gname}\" 吗？\n（Mod 不会被删除，只是移除分组）"):
                groups.pop(gname, None)
                if gname in order:
                    order.remove(gname)
                ConfigManager.set_mod_groups(groups)
                ConfigManager.set_group_order(order)
                dialog.destroy()
                self._refresh()

        ctk.CTkButton(btn_row, text="✏️ 重命名", width=80,
                      command=rename_group).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="🗑️ 删除分组", width=80,
                      fg_color="#da3633", hover_color="#f85149",
                      command=delete_group).pack(side="left")
        ctk.CTkButton(btn_row, text="关闭", width=60,
                      command=dialog.destroy).pack(side="right")

    # ============================================================
    # 更多菜单（仍使用 tkinter Menu，因为它是最方便的弹出菜单方案）
    # ============================================================
    def _show_more_menu(self, mod):
        name = mod["name"]
        import tkinter as tk
        menu = tk.Menu(self.root, tearoff=0,
                       bg="#2b2b2b", fg="#e0e0e0",
                       activebackground="#3B8ED0", activeforeground="white",
                       font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))), bd=1, relief="flat")

        current_note = ConfigManager.get_mod_notes().get(name, "")
        menu.add_command(
            label=f"📝 编辑备注" + (" (已有)" if current_note else ""),
            command=lambda: self._edit_note(mod),
        )

        current_img = ConfigManager.get_mod_images().get(name, "")
        menu.add_command(
            label="🖼️ 设置预览图" + (" (已设置)" if current_img else ""),
            command=lambda: self._set_preview_image(mod),
        )

        # 分组子菜单
        groups = ConfigManager.get_mod_groups()
        order = ConfigManager.get_group_order()
        ordered_groups = [g for g in order if g in groups]
        other_groups = [g for g in groups if g not in ordered_groups]
        all_groups = ordered_groups + other_groups

        group_menu = tk.Menu(menu, tearoff=0,
                             bg="#2b2b2b", fg="#e0e0e0",
                             activebackground="#3B8ED0", activeforeground="white",
                             font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))))
        for gname in all_groups:
            has_mod = name in groups[gname]
            label = f"  {'✓ ' if has_mod else ''}{gname}"
            group_menu.add_command(
                label=label,
                command=lambda g=gname, has=has_mod:
                self._toggle_mod_group(mod, g, not has),
            )
        if not all_groups:
            group_menu.add_command(label="  (无分组，请先创建)", state="disabled")

        menu.add_cascade(label="📁 添加到分组 / 移出分组", menu=group_menu)

        if current_img:
            menu.add_command(label="🗑️ 清除预览图", command=lambda: self._clear_preview_image(mod))
        if current_note:
            menu.add_command(label="🗑️ 清除备注", command=lambda: self._clear_note(mod))

        row_info = self._mod_rows.get(name)
        if row_info:
            # Find the more button "⋯" in the right_frame
            try:
                btn_parent = row_info["switch"].master
                for child in reversed(btn_parent.winfo_children()):
                    if isinstance(child, ctk.CTkButton):
                        try:
                            if child.cget("text") == "⋯":
                                x = child.winfo_rootx()
                                y = child.winfo_rooty() + child.winfo_height()
                                menu.tk_popup(x, y)
                                menu.grab_release()
                                return
                        except Exception:
                            pass
            except Exception:
                pass

        # fallback
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _toggle_mod_group(self, mod, gname, add):
        name = mod["name"]
        groups = ConfigManager.get_mod_groups()
        if add:
            groups.setdefault(gname, [])
            if name not in groups[gname]:
                groups[gname].append(name)
        else:
            if gname in groups and name in groups[gname]:
                groups[gname].remove(name)
                if not groups[gname]:
                    del groups[gname]
        ConfigManager.set_mod_groups(groups)
        self._refresh()

    def _edit_note(self, mod):
        name = mod["name"]
        current = ConfigManager.get_mod_notes().get(name, "")
        result = simpledialog.askstring(
            "编辑备注", f"为 Mod \"{name}\" 设置备注名称：",
            initialvalue=current, parent=self.root,
        )
        if result is not None:
            ConfigManager.set_mod_note(name, result.strip())
            self._refresh()

    def _clear_note(self, mod):
        ConfigManager.set_mod_note(mod["name"], "")
        self._refresh()

    def _set_preview_image(self, mod):
        if not HAS_PIL:
            messagebox.showwarning("缺少依赖", "预览图功能需要 Pillow 库。\n\n请运行: pip install Pillow")
            return
        path = filedialog.askopenfilename(
            title="选择预览图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp"), ("所有文件", "*.*")],
        )
        if path:
            ConfigManager.set_mod_image(mod["name"], path)
            self._refresh()

    def _clear_preview_image(self, mod):
        ConfigManager.set_mod_image(mod["name"], "")
        self._refresh()

    # ============================================================
    # 全屏预览原图
    # ============================================================
    def _show_full_image(self, image_path):
        """点击预览图 → 独立窗口显示原图（≤屏幕 60%，否则原尺寸）"""
        if not HAS_PIL or not os.path.isfile(image_path):
            return
        try:
            from PIL import ImageTk
            import tkinter as tk

            pil_img = Image.open(image_path)
            orig_w, orig_h = pil_img.size

            # 计算屏幕可用尺寸的 60%
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            max_w = int(screen_w * 0.6)
            max_h = int(screen_h * 0.6)

            # 缩放规则：保持宽高比，任何一边不超过 max
            scale = min(1.0, max_w / orig_w, max_h / orig_h)
            if scale < 1.0:
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)
                resample = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
                display_img = pil_img.resize((new_w, new_h), resample)
            else:
                new_w, new_h = orig_w, orig_h
                display_img = pil_img

            # 创建独立窗口，尺寸 = 图片显示尺寸
            win = tk.Toplevel(self.root)
            win.title(f"图片预览 - {os.path.basename(image_path)}")
            win.geometry(f"{new_w}x{new_h}")
            win.resizable(False, False)
            win.configure(bg="black")

            # 居中于屏幕
            x = (screen_w - new_w) // 2
            y = (screen_h - new_h) // 2
            win.geometry(f"+{x}+{y}")

            # 图片填满窗口
            tk_img = ImageTk.PhotoImage(display_img)
            img_label = tk.Label(win, image=tk_img, bg="black", cursor="hand2")
            img_label.image = tk_img  # 保持引用
            img_label.pack(fill="both", expand=True)

            # 关闭：点击图片 / Esc / 滚轮
            def close_win(e=None):
                win.destroy()

            img_label.bind("<Button-1>", close_win)
            win.bind("<Escape>", close_win)
            win.bind("<MouseWheel>", close_win)

            # 窗口获得焦点（可选）
            win.focus_force()

        except Exception:
            pass  # 图片加载失败，静默处理

    # ============================================================
    # 开关切换
    # ============================================================
    def _on_switch_toggled(self, mod_name, new_state):
        mod = None
        for m in self.mods_data:
            if m["name"] == mod_name:
                mod = m
                break
        if not mod or new_state == mod["enabled"]:
            return
        self._toggle_mod_threaded(mod)

    def _toggle_mod_threaded(self, mod):
        if self.is_operating:
            messagebox.showwarning("操作中", "请等待当前操作完成")
            row_info = self._mod_rows.get(mod["name"])
            if row_info:
                row_info["switch_var"].set(mod["enabled"])
            return

        name = mod["name"]
        currently_enabled = mod["enabled"]
        action = "禁用" if currently_enabled else "启用"

        if not messagebox.askyesno("确认操作", f"确定要{action} Mod \"{name}\" 吗？\n\n这将会移动整个 Mod 文件夹。"):
            row_info = self._mod_rows.get(name)
            if row_info:
                row_info["switch_var"].set(currently_enabled)
            return

        self.is_operating = True
        self._set_ui_enabled(False)

        self.progress_frame.pack(fill="x", padx=16, pady=(6, 0))
        self.progress_bar.pack(side="left", padx=(10, 8))
        self.progress_text.pack(side="left")
        self.progress_bar.set(0)
        self.progress_text.configure(text=f"正在{action}: {name} ...")

        def file_cb(current, total, bytes_done, status):
            pct = current / total if total > 0 else 1.0
            self.root.after(0, self._update_progress, pct, status)

        def worker():
            try:
                self.mod_manager.toggle_mod(name, currently_enabled, file_cb)
                self.root.after(0, self._on_toggle_complete, name, action, True, "")
            except Exception as e:
                self.root.after(0, self._on_toggle_complete, name, action, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # 批量切换
    # ============================================================
    def _batch_toggle(self, enable):
        if self.is_operating:
            messagebox.showwarning("操作中", "请等待当前操作完成")
            return

        selected = self._get_selected_mods()
        if not selected:
            messagebox.showinfo("提示", "请先勾选要操作的 Mod")
            return

        action = "启用" if enable else "禁用"
        to_toggle = [m for m in selected if m["enabled"] != enable]
        already = len(selected) - len(to_toggle)

        msg = f"确定要批量{action} {len(to_toggle)} 个 Mod 吗？"
        if already > 0:
            msg += f"\n（{already} 个已处于目标状态，将跳过）"
        msg += "\n\n这将会移动 Mod 文件夹。"

        if not messagebox.askyesno("确认批量操作", msg):
            return

        if not to_toggle:
            messagebox.showinfo("提示", "所选 Mod 均已处于目标状态")
            return

        self.is_operating = True
        self._set_ui_enabled(False)

        self.progress_frame.pack(fill="x", padx=16, pady=(6, 0))
        self.progress_bar.pack(side="left", padx=(10, 8))
        self.progress_text.pack(side="left")
        self.progress_bar.set(0)
        self.progress_text.configure(text=f"正在批量{action}... (0/{len(to_toggle)})")

        def file_cb(current, total, bytes_done, status):
            pass

        def mod_cb(idx, total, status):
            pct = idx / total
            self.root.after(0, self._update_progress, pct,
                            f"正在批量{action}... ({idx}/{total}) {status}")

        def worker():
            results = self.mod_manager.toggle_mods_batch(
                to_toggle, enable,
                progress_callback=mod_cb,
                file_progress_callback=file_cb,
            )
            self.root.after(0, self._on_batch_complete, results, action)

        threading.Thread(target=worker, daemon=True).start()

    def _on_batch_complete(self, results, action):
        self.progress_frame.pack_forget()
        self.progress_bar.pack_forget()
        self.progress_text.pack_forget()
        self._set_ui_enabled(True)
        self.is_operating = False

        success = sum(1 for _, ok, _ in results if ok)
        fail = len(results) - success

        if fail > 0:
            failed_list = [f"  - {name}: {err}" for name, ok, err in results if not ok]
            detail = "\n".join(failed_list[:8])
            messagebox.showwarning("批量操作结果",
                                   f"批量{action}完成：成功 {success} 个，失败 {fail} 个\n\n{detail}")
        else:
            self.status_label.configure(text=f"批量{action}完成: 成功 {success} 个")

        self._refresh()

    def _update_progress(self, pct, status):
        self.progress_bar.set(pct)
        self.progress_text.configure(text=status)

    def _on_toggle_complete(self, name, action, success, error_msg):
        self.progress_frame.pack_forget()
        self.progress_bar.pack_forget()
        self.progress_text.pack_forget()
        self._set_ui_enabled(True)
        self.is_operating = False

        if success:
            self.status_label.configure(text=f"已{action}: {name}")
            self._refresh()
        else:
            messagebox.showerror("操作失败", f"无法{action} Mod \"{name}\":\n{error_msg}")
            self.status_label.configure(text=f"{action}失败: {name}")

    def _set_ui_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self._browse_btn.configure(state=state)
        self._refresh_btn.configure(state=state)
        for row_info in self._mod_rows.values():
            row_info["switch"].configure(state=state)

    def _open_mod_folder(self, mod):
        if self.mod_manager:
            self.mod_manager.open_mod_folder(mod["name"], mod["enabled"])

    def _update_stats(self):
        enabled_count = sum(1 for m in self.mods_data if m["enabled"])
        disabled_count = len(self.mods_data) - enabled_count
        self.status_label.configure(
            text=f"已启用: {enabled_count} 个  |  已禁用: {disabled_count} 个  |  共计: {len(self.mods_data)} 个 Mod"
        )

    def run(self):
        self.root.mainloop()


def _setup_console_visibility():
    """
    控制终端窗口显示/隐藏。

    推荐 PyInstaller 构建方式：
      - 正常版本：pyinstaller --noconsole ...
        → 启动时无任何终端窗口。
      - 调试版本：仍使用 --noconsole 构建，但程序所在目录放置一个
        任意内容的 'debug_mode' 文件即可自动弹出终端窗口。

    兼容情况：
      - 直接运行 .py 文件时：终端始终可见（不做任何操作）。
      - 若使用 --console 构建：无 debug_mode 文件时会先隐藏再释放控制台，
        仍可能有短暂闪现，推荐使用 --noconsole 方式。
    """
    if not getattr(sys, "frozen", False):
        # 非 PyInstaller 产物，终端自然可见
        return

    import ctypes

    debug_file = os.path.join(APP_DIR, "debug_mode")
    kernel32 = ctypes.windll.kernel32

    if os.path.exists(debug_file):
        # debug_mode 文件存在 → 确保控制台可见
        console_hwnd = kernel32.GetConsoleWindow()
        if not console_hwnd:
            # --noconsole 构建：分配一个新控制台
            if kernel32.AllocConsole():
                # 重定向 stdout / stderr 到新控制台
                import io
                try:
                    conout = open("CONOUT$", "w", buffering=1)
                    sys.stdout = io.TextIOWrapper(conout, line_buffering=True)
                except Exception:
                    pass
                try:
                    conerr = open("CONOUT$", "w", buffering=1)
                    sys.stderr = io.TextIOWrapper(conerr, line_buffering=True)
                except Exception:
                    pass
        # --console 构建：窗口已存在且可见，无需额外操作
        return

    # debug_mode 文件不存在 → 隐藏/释放控制台
    console_hwnd = kernel32.GetConsoleWindow()
    if not console_hwnd:
        # --noconsole 构建：本来就没有终端，什么都不用做
        return

    # --console 构建但有控制台窗口：先隐藏再释放
    user32 = ctypes.windll.user32
    user32.ShowWindow(console_hwnd, 0)  # SW_HIDE
    kernel32.FreeConsole()


def main():
    _setup_console_visibility()
    app = ModManagerApp()
    app.run()


if __name__ == "__main__":
    main()