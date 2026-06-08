# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - GUI 主界面模块
基于 customtkinter 的 Mod 管理器主窗口。
"""

import os
import sys
import threading
from tkinter import messagebox, filedialog

import customtkinter as ctk
from customtkinter import CTkImage

# PIL 用于预览图片
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# pypinyin 用于中文拼音首字母索引（可选依赖）
try:
    from pypinyin import lazy_pinyin, Style

    HAS_PYPINYIN = True
except ImportError:
    HAS_PYPINYIN = False

from modules.config import ConfigManager, README_LABELS
from modules.mod_ops import ModManager
from modules.i18n import t, get_i18n


class ModManagerApp:
    PREVIEW_SIZE = 48

    LANG_NATIVE = {
        "zh": "中文",
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
    }

    def __init__(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("EFMI Mod Manager")
        self.root.geometry("1120x740")
        self.root.minsize(960, 520)

        app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(app_dir, "app.ico")
        if os.path.isfile(icon_path):
            self.root.iconbitmap(icon_path)

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
        self._preview_ctk_images = {}  # mod_name -> CTkImage
        # 分组级 A-Z 索引（全局右侧栏，跳转到分组标题）
        self._primary_alpha_index = {}  # letter -> 第一个匹配的分组名
        self._primary_alpha_buttons = {}  # letter -> button
        self._ungrouped_btn = None  # 未分组专用索引按钮
        self._sorted_group_names = []  # 按名称排序后的分组名列表（未分组除外）
        # 分组内部的迷你 A-Z 索引栏
        self._group_mini_alpha_bars = {}  # group_name -> {"frame", "buttons", "index"}

        # 语言切换下拉菜单
        self._lang_var = None
        self._lang_menu = None

        # 工具栏可翻译控件引用
        self._toolbar_widgets = {}

        # 动态 DPI 缩放
        self._dpi_scale = self._get_dpi_scale_factor()

        self._build_ui()
        self._load_config_and_refresh()

    # ============================================================
    # DPI 动态缩放
    # ============================================================
    def _get_dpi_scale_factor(self):
        """获取 Windows DPI 缩放因子（96 DPI = 1.0, 144 DPI = 1.5 等）"""
        if sys.platform != "win32":
            return 1.0
        try:
            import ctypes
            user32 = ctypes.windll.user32
            shcore = ctypes.windll.shcore

            hwnd = None
            try:
                hwnd = self.root.winfo_id()
            except Exception:
                pass

            if hwnd:
                monitor = user32.MonitorFromWindow(hwnd, 0)
                if monitor:
                    dpi_x = ctypes.c_uint()
                    dpi_y = ctypes.c_uint()
                    result = shcore.GetDpiForMonitor(
                        monitor, 0,
                        ctypes.byref(dpi_x), ctypes.byref(dpi_y))
                    if result == 0:
                        scale = dpi_x.value / 96.0
                        return max(0.8, min(scale, 3.0))

            hdc = user32.GetDC(0)
            if hdc:
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
                user32.ReleaseDC(0, hdc)
                if dpi and dpi > 0:
                    scale = dpi / 96.0
                    return max(0.8, min(scale, 3.0))

            return 1.0
        except Exception:
            return 1.0

    def _font(self, base_size, weight=None):
        """根据 DPI 缩放因子计算字体"""
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

        self._title_label = ctk.CTkLabel(
            top_frame, text=t("app.title", "EFMI Mod Manager"),
            font=self._font(20, weight="bold")
        )
        self._title_label.pack(side="left", padx=(20, 10), pady=12)

        self._subtitle_label = ctk.CTkLabel(
            top_frame, text=t("top.subtitle", "|  Mod 管理器"),
            font=self._font(12),
            text_color="gray"
        )
        self._subtitle_label.pack(side="left", padx=(0, 20), pady=12)

        self.path_label = ctk.CTkLabel(
            top_frame, text=t("top.no_folder", "未选择文件夹"),
            font=self._font(11),
            text_color="gray"
        )
        self.path_label.pack(side="right", padx=(0, 10), pady=12)

        self._refresh_btn = ctk.CTkButton(
            top_frame, text=t("top.refresh", "🔄 刷新"), width=70, height=30,
            font=self._font(11),
            command=self._refresh
        )
        self._refresh_btn.pack(side="right", padx=(0, 8), pady=12)

        self._browse_btn = ctk.CTkButton(
            top_frame, text=t("top.browse", "📁 选择文件夹"), width=110, height=30,
            font=self._font(11),
            command=self._browse_folder
        )
        self._browse_btn.pack(side="right", padx=(0, 8), pady=12)

        self._lang_var = ctk.StringVar(value=self._lang_menu_display())
        self._lang_menu = ctk.CTkOptionMenu(
            top_frame,
            values=self._lang_menu_values(),
            variable=self._lang_var,
            command=self._on_language_change,
            width=70, height=30,
            font=self._font(10),
            fg_color=("gray85", "gray25"),
            text_color=("gray20", "gray85"),
            button_color=("gray70", "gray30"),
            button_hover_color=("gray60", "gray40"),
        )
        self._lang_menu.pack(side="right", padx=(0, 8), pady=12)

        # ---- 工具栏 ----
        toolbar = ctk.CTkFrame(self.root, height=42, corner_radius=0,
                               fg_color=("gray90", "gray17"))
        toolbar.pack(fill="x", padx=0, pady=(0, 0))
        toolbar.pack_propagate(False)

        toolbar_inner = ctk.CTkFrame(toolbar, fg_color=("gray90", "gray17"))
        toolbar_inner.pack(side="left", fill="y", padx=14, pady=4)

        w_select_label = ctk.CTkLabel(toolbar_inner, text=t("toolbar.select", "选择:"),
                                      font=self._font(11))
        w_select_label.pack(side="left", padx=(0, 6))
        self._toolbar_widgets["select_label"] = w_select_label

        w_select_all = ctk.CTkButton(toolbar_inner, text=t("toolbar.select_all", "全选"),
                                     width=50, height=26,
                                     font=self._font(10),
                                     command=self._select_all)
        w_select_all.pack(side="left", padx=2)
        self._toolbar_widgets["select_all"] = w_select_all

        w_invert = ctk.CTkButton(toolbar_inner, text=t("toolbar.invert", "反选"),
                                 width=50, height=26,
                                 font=self._font(10),
                                 command=self._invert_selection)
        w_invert.pack(side="left", padx=2)
        self._toolbar_widgets["invert"] = w_invert

        w_deselect = ctk.CTkButton(toolbar_inner, text=t("toolbar.deselect", "不选"),
                                   width=50, height=26,
                                   font=self._font(10),
                                   command=self._deselect_all)
        w_deselect.pack(side="left", padx=2)
        self._toolbar_widgets["deselect"] = w_deselect

        sep1 = ctk.CTkFrame(toolbar_inner, width=1, height=22, fg_color="gray40")
        sep1.pack(side="left", padx=10)

        w_actions_label = ctk.CTkLabel(toolbar_inner, text=t("toolbar.actions", "操作:"),
                                       font=self._font(11))
        w_actions_label.pack(side="left", padx=(0, 6))
        self._toolbar_widgets["actions_label"] = w_actions_label

        w_batch_enable = ctk.CTkButton(toolbar_inner, text=t("toolbar.batch_enable", "批量启用"),
                                       width=70, height=26,
                                       font=self._font(10), fg_color="#2ea043",
                                       hover_color="#3fb950",
                                       command=lambda: self._batch_toggle(True))
        w_batch_enable.pack(side="left", padx=2)
        self._toolbar_widgets["batch_enable"] = w_batch_enable

        w_batch_disable = ctk.CTkButton(toolbar_inner, text=t("toolbar.batch_disable", "批量禁用"),
                                        width=70, height=26,
                                        font=self._font(10), fg_color="#da3633",
                                        hover_color="#f85149",
                                        command=lambda: self._batch_toggle(False))
        w_batch_disable.pack(side="left", padx=2)
        self._toolbar_widgets["batch_disable"] = w_batch_disable

        sep2 = ctk.CTkFrame(toolbar_inner, width=1, height=22, fg_color="gray40")
        sep2.pack(side="left", padx=10)

        w_new_group = ctk.CTkButton(toolbar_inner, text=t("toolbar.new_group", "➕ 新建分组"),
                                    width=80, height=26,
                                    font=self._font(10),
                                    command=self._create_group)
        w_new_group.pack(side="left", padx=2)
        self._toolbar_widgets["new_group"] = w_new_group

        w_manage_groups = ctk.CTkButton(toolbar_inner, text=t("toolbar.manage_groups", "✏️ 管理分组"),
                                        width=80, height=26,
                                        font=self._font(10),
                                        command=self._manage_groups)
        w_manage_groups.pack(side="left", padx=2)
        self._toolbar_widgets["manage_groups"] = w_manage_groups

        # ---- 主体区域 ----
        body = ctk.CTkFrame(self.root, fg_color=("gray95", "gray14"))
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Mod 列表（可滚动）
        self.scroll_frame = ctk.CTkScrollableFrame(body, label_text="")
        self.scroll_frame.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=0)

        # A-Z 侧边栏（仅分组级跳转）
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
        """构建分组级 A-Z 快速跳转侧边栏（仅跳转分组标题）"""
        self._alpha_container = ctk.CTkFrame(parent, width=28, corner_radius=0,
                                              fg_color=("gray90", "gray14"))
        self._alpha_container.pack(side="right", fill="y", padx=0, pady=0)
        self._alpha_container.pack_propagate(False)

        # 一级索引栏（分组名首字母 A-Z）
        self._primary_frame = ctk.CTkFrame(self._alpha_container, width=22,
                                            corner_radius=0,
                                            fg_color=("gray90", "gray14"))
        self._primary_frame.place(x=3, y=0, relheight=1.0)

        # 保留旧引用兼容
        self._alpha_frame = self._primary_frame
        self._alpha_buttons = {}

        # 占位
        ctk.CTkLabel(self._primary_frame, text="", font=self._font(6)).pack()

    # ============================================================
    # 语言切换
    # ============================================================
    def _lang_menu_display(self):
        i18n = get_i18n()
        if i18n.lang == "auto":
            return t("lang.auto", "自动")
        return self.LANG_NATIVE.get(i18n.lang, i18n.lang)

    def _lang_menu_values(self):
        i18n = get_i18n()
        values = [t("lang.auto", "自动")]
        for code in self.LANG_NATIVE:
            values.append(self.LANG_NATIVE[code])
        return values

    def _on_language_change(self, display_value):
        if display_value == t("lang.auto", "自动"):
            new_lang = "auto"
        else:
            inverse = {v: k for k, v in self.LANG_NATIVE.items()}
            new_lang = inverse.get(display_value, display_value)

        if new_lang == get_i18n().lang:
            return

        ConfigManager.set_language(new_lang)
        get_i18n().set_language(new_lang)
        self._apply_language()

    def _apply_language(self):
        self.root.title(t("app.title", "EFMI Mod Manager"))
        self._title_label.configure(text=t("app.title", "EFMI Mod Manager"))
        self._subtitle_label.configure(text=t("top.subtitle", "|  Mod 管理器"))
        self._browse_btn.configure(text=t("top.browse", "📁 选择文件夹"))
        self._refresh_btn.configure(text=t("top.refresh", "🔄 刷新"))

        tw = self._toolbar_widgets
        tw["select_label"].configure(text=t("toolbar.select", "选择:"))
        tw["select_all"].configure(text=t("toolbar.select_all", "全选"))
        tw["invert"].configure(text=t("toolbar.invert", "反选"))
        tw["deselect"].configure(text=t("toolbar.deselect", "不选"))
        tw["actions_label"].configure(text=t("toolbar.actions", "操作:"))
        tw["batch_enable"].configure(text=t("toolbar.batch_enable", "批量启用"))
        tw["batch_disable"].configure(text=t("toolbar.batch_disable", "批量禁用"))
        tw["new_group"].configure(text=t("toolbar.new_group", "➕ 新建分组"))
        tw["manage_groups"].configure(text=t("toolbar.manage_groups", "✏️ 管理分组"))

        self._lang_var.set(self._lang_menu_display())
        self._lang_menu.configure(values=self._lang_menu_values())

        self._refresh()

    # ---- 中文拼音索引支持 ----
    @staticmethod
    def _get_sort_key(display):
        """
        返回用于排序和字母索引的 key tuple: (sort_key, original_display)
        - 中文字符 → 拼音首字母（小写），如 '测试' → 'c'
        - 英文字母 → 自身小写，如 'Alpha' → 'a'
        - 其他字符 → 原字符小写
        如果 pypinyin 不可用，整个中文串归入 '#'
        """
        display_lower = display.lower()
        first_char_letter = None

        for ch in display:
            if 'a' <= ch <= 'z' or 'A' <= ch <= 'Z':
                first_char_letter = ch.lower()
                break
            if '\u4e00' <= ch <= '\u9fff':
                # 中文字符
                if HAS_PYPINYIN:
                    try:
                        py = lazy_pinyin(ch, style=Style.FIRST_LETTER)
                        if py and py[0]:
                            first_char_letter = py[0].lower()
                            break
                    except Exception:
                        pass
                # 无 pypinyin 时归入其他
                first_char_letter = '#'
                break
            # 其他 Unicode 字符继续扫描

        # 如果没找到字母或中文始字符
        if first_char_letter is None:
            first_char_letter = '#'

        if 'a' <= first_char_letter <= 'z':
            return (first_char_letter, display_lower)
        else:
            return ('#', display_lower)

    @staticmethod
    def _get_index_letter(display):
        """
        返回侧边栏索引字母（大写 A-Z 或 '#'）。
        如果 pypinyin 可用，中文字符转换为拼音首字母大写。
        """
        for ch in display:
            if 'a' <= ch <= 'z' or 'A' <= ch <= 'Z':
                return ch.upper()
            if '\u4e00' <= ch <= '\u9fff':
                if HAS_PYPINYIN:
                    try:
                        py = lazy_pinyin(ch, style=Style.FIRST_LETTER)
                        if py and py[0]:
                            letter = py[0].upper()
                            if 'A' <= letter <= 'Z':
                                return letter
                    except Exception:
                        pass
                return '#'
        return '#'

    def _rebuild_alphabet_bar(self):
        """重建一级 A-Z 索引：分组名首字母（全局右侧栏）"""
        # ---- 清理 ----
        for widget in self._primary_frame.winfo_children():
            widget.destroy()
        self._primary_alpha_index.clear()
        self._primary_alpha_buttons.clear()
        self._ungrouped_btn = None

        # ---- 收集分组名 ----
        groups = ConfigManager.get_mod_groups()

        all_groups_set = set()
        assigned = set()
        valid_names = {m["name"] for m in self.mods_data}
        for gname, mods in groups.items():
            if any(m in valid_names for m in mods):
                all_groups_set.add(gname)
                for mod_name in mods:
                    assigned.add(mod_name)
        unassigned = [m for m in self.mods_data if m["name"] not in assigned]
        has_ungrouped = bool(unassigned)

        # 排序分组名（除"未分组"），按分组名全词典序
        sorted_groups = sorted(all_groups_set, key=lambda g: self._get_sort_key(g))
        self._sorted_group_names = sorted_groups

        # 建一级索引
        for gname in sorted_groups:
            letter = self._get_index_letter(gname)
            if letter not in self._primary_alpha_index:
                self._primary_alpha_index[letter] = gname

        # 渲染一级按钮
        all_letters = [chr(i) for i in range(ord('A'), ord('Z') + 1)]
        for letter in all_letters:
            if letter not in self._primary_alpha_index:
                continue
            btn = ctk.CTkButton(
                self._primary_frame,
                text=letter,
                width=22,
                height=20,
                font=self._font(9),
                corner_radius=2,
                fg_color=("gray70", "gray25"),
                text_color=("gray20", "gray90"),
                hover_color=("gray60", "gray35"),
                command=lambda l=letter: self._scroll_to_group(l),
            )
            btn.pack(pady=1, padx=3)
            self._primary_alpha_buttons[letter] = btn

        # 未分组专用按钮（最底部）
        if has_ungrouped:
            ungrouped_btn = ctk.CTkButton(
                self._primary_frame,
                text="📁",
                width=22,
                height=20,
                font=self._font(9),
                corner_radius=2,
                fg_color=("gray70", "gray25"),
                text_color=("gray20", "gray90"),
                hover_color=("gray60", "gray35"),
                command=self._scroll_to_ungrouped,
            )
            ungrouped_btn.pack(side="bottom", pady=1, padx=3)
            self._ungrouped_btn = ungrouped_btn

        # 占位
        ctk.CTkLabel(self._primary_frame, text="", font=self._font(6)).pack(side="bottom")

    # ============================================================
    # 分组内部迷你 A-Z 索引栏
    # ============================================================
    def _build_group_mini_alpha_bar(self, content_frame, gname, mods, notes):
        """在分组内容区右侧构建该组的迷你 A-Z 索引栏"""
        mini_bar = ctk.CTkFrame(content_frame, width=22, corner_radius=0,
                                fg_color=("gray88", "gray16"))
        mini_bar.pack(side="right", fill="y", padx=(2, 0), pady=2)
        mini_bar.pack_propagate(False)

        # 建索引
        alpha_index = {}  # letter -> first mod_name
        for mod in mods:
            display = (notes.get(mod["name"], "") or mod["name"]).strip()
            if display:
                letter = self._get_index_letter(display)
                if letter not in alpha_index:
                    alpha_index[letter] = mod["name"]

        buttons = {}
        if alpha_index:
            for letter in sorted(alpha_index.keys()):
                btn = ctk.CTkButton(
                    mini_bar,
                    text=letter,
                    width=18,
                    height=16,
                    font=self._font(7),
                    corner_radius=2,
                    fg_color=("gray70", "gray25"),
                    text_color=("gray20", "gray90"),
                    hover_color=("gray60", "gray35"),
                    command=lambda l=letter, idx=alpha_index: self._scroll_to_mini_letter(l, idx),
                )
                btn.pack(pady=1, padx=2)
                buttons[letter] = btn
        else:
            # 至少有一个占位，保持栏可见
            ctk.CTkLabel(mini_bar, text="", font=self._font(6)).pack()

        self._group_mini_alpha_bars[gname] = {
            "frame": mini_bar,
            "buttons": buttons,
            "index": alpha_index,
        }

    def _scroll_to_mini_letter(self, letter, alpha_index):
        """滚动到迷你索引中指定字母对应的第一个 Mod"""
        if letter not in alpha_index:
            return
        mod_name = alpha_index[letter]
        row_info = self._mod_rows.get(mod_name)
        if not row_info:
            return
        widget = row_info.get("row_frame")
        if widget and widget.winfo_exists():
            self._scroll_to_widget(widget)

    # ============================================================
    # 跳转方法
    # ============================================================
    def _scroll_to_group(self, letter):
        """滚动到对应字母的第一个分组标题"""
        if letter not in self._primary_alpha_index:
            return
        gname = self._primary_alpha_index[letter]
        header = self._group_headers.get(gname)
        if header and header.winfo_exists():
            self._scroll_to_widget(header)

    def _scroll_to_ungrouped(self):
        """滚动到未分组标题"""
        header = self._group_headers.get(t("mod_list.ungrouped", "未分组"))
        if header and header.winfo_exists():
            self._scroll_to_widget(header)

    def _scroll_to_widget(self, widget):
        """将 scrollable frame 滚动到指定 widget 可见"""
        if not widget or not widget.winfo_exists():
            return
        canvas = self.scroll_frame._parent_canvas
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
        path = filedialog.askdirectory(title=t("top.browse", "选择游戏 Mod 文件夹（包含 Mods 和 Disabled_Mods 的目录）"))
        if path:
            ConfigManager.set_game_path(path)
            self._load_config_and_refresh()

    def _load_config_and_refresh(self):
        game_path = ConfigManager.get_game_path()
        if game_path:
            self.path_label.configure(text=os.path.basename(game_path) or game_path)
        else:
            self.path_label.configure(text=t("top.no_folder", "未选择文件夹"))
        self._refresh()

    def _refresh(self):
        game_path = ConfigManager.get_game_path()
        if not game_path:
            self._show_empty_state(t("mod_list.empty_state", "请先选择一个包含 Mods 文件夹的游戏目录"))
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

        if created_disabled:
            self.root.after(100, lambda: messagebox.showinfo(
                t("dialog.title_hint", "提示"),
                t("dialog.disabled_dir_created", "检测到游戏目录中没有 Disabled_Mods 文件夹，已自动创建。\n\n"
                  "路径: {path}").format(path=self.mod_manager.disabled_dir)
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
        self._primary_alpha_index.clear()
        self._sorted_group_names.clear()
        self._preview_ctk_images.clear()
        self._group_mini_alpha_bars.clear()
        self.mods_data = []

        label = ctk.CTkLabel(
            self.scroll_frame, text=message,
            font=self._font(13),
            text_color="gray"
        )
        label.pack(pady=60)
        self.status_label.configure(text="")

    # ============================================================
    # 渲染 Mod 列表（带分组、折叠、复选框、迷你 A-Z 索引栏）
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
        self._group_mini_alpha_bars.clear()

        if not self.mods_data:
            ctk.CTkLabel(
                self.scroll_frame, text=t("mod_list.empty", "没有找到任何 Mod 文件夹"),
                font=self._font(13), text_color="gray"
            ).pack(pady=60)
            return

        groups = ConfigManager.get_mod_groups()
        collapsed = set(ConfigManager.get_collapsed_groups())
        notes = ConfigManager.get_mod_notes()
        images = ConfigManager.get_mod_images()

        mod_by_name = {m["name"]: m for m in self.mods_data}
        assigned = set()

        # 收集所有有 mod 的分组（排除空分组），按分组名 A-Z 排序
        active_groups = []
        for gname, mods_in_group_names in groups.items():
            mods_in_group = [mod_by_name[n] for n in mods_in_group_names if n in mod_by_name]
            if mods_in_group:
                active_groups.append((gname, mods_in_group))
                for m in mods_in_group:
                    assigned.add(m["name"])

        # 分组名 A-Z 排序（全词典序）
        active_groups.sort(key=lambda x: self._get_sort_key(x[0]))

        # 渲染分组
        for gname, mods_in_group in active_groups:
            # 组内按备注名排序
            mods_in_group.sort(
                key=lambda m: self._get_sort_key(
                    (notes.get(m["name"], "") or m["name"]).strip()
                )
            )
            self._create_group_section(gname, mods_in_group, notes, images,
                                       is_collapsed=(gname in collapsed))

        # 未分组永远是置底的
        unassigned = [m for m in self.mods_data if m["name"] not in assigned]
        if unassigned:
            unassigned.sort(
                key=lambda m: self._get_sort_key(
                    (notes.get(m["name"], "") or m["name"]).strip()
                )
            )
            self._create_group_section(t("mod_list.ungrouped", "未分组"), unassigned, notes, images,
                                       is_collapsed=(t("mod_list.ungrouped", "未分组") in collapsed))

    def _create_group_section(self, gname, mods, notes, images, is_collapsed=False):
        # ---- 分组标题栏 ----
        header = ctk.CTkFrame(
            self.scroll_frame, height=36, corner_radius=6,
            fg_color=("gray85", "gray20")
        )
        header.pack(fill="x", padx=2, pady=(10, 2))
        header.pack_propagate(False)

        arrow = t("mod_list.arrow_collapsed", "▶") if is_collapsed else t("mod_list.arrow_expanded", "▼")
        collapse_btn = ctk.CTkButton(
            header, text=arrow, width=26, height=26,
            font=self._font(10),
            fg_color=("gray85", "gray20"),
            hover_color=("gray75", "gray28"),
            text_color=("gray30", "gray80"),
        )
        collapse_btn.pack(side="left", padx=(4, 2))

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

        name_label = ctk.CTkLabel(
            header, text=f"📁 {gname}",
            font=self._font(12, weight="bold")
        )
        name_label.pack(side="left")

        count_label = ctk.CTkLabel(
            header,
            text=t("mod_list.count_suffix", "({count} 个)").format(count=len(mods)),
            font=self._font(10),
            text_color="gray"
        )
        count_label.pack(side="left", padx=(6, 0))

        self._group_headers[gname] = header

        # ---- 分组内容区（水平布局：左栏 Mod 行 + 右栏迷你 A-Z 索引）----
        content = ctk.CTkFrame(self.scroll_frame, fg_color=("gray95", "gray14"))
        if not is_collapsed:
            content.pack(fill="x", padx=2, pady=0)

        self._group_contents[gname] = content

        if mods:
            self._group_first_mod[gname] = mods[0]["name"]

        # 左栏：Mod 行
        left_frame = ctk.CTkFrame(content, fg_color=("gray95", "gray14"))
        left_frame.pack(side="left", fill="both", expand=True)

        for mod in mods:
            self._mod_to_group[mod["name"]] = gname
            self._create_mod_row(left_frame, mod, notes.get(mod["name"], ""),
                                 images.get(mod["name"], ""))

        # 右栏：该组的迷你 A-Z 索引
        self._build_group_mini_alpha_bar(content, gname, mods, notes)

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
            content.pack_forget()
            btn.configure(text=t("mod_list.arrow_collapsed", "▶"))
            if gname not in collapsed_list:
                collapsed_list.append(gname)
        else:
            header = self._group_headers.get(gname)
            if header:
                content.pack(after=header, fill="x", padx=2, pady=0)
            else:
                content.pack(fill="x", padx=2, pady=0)
            btn.configure(text=t("mod_list.arrow_expanded", "▼"))
            if gname in collapsed_list:
                collapsed_list.remove(gname)

        ConfigManager.set_collapsed_groups(collapsed_list)

    # ============================================================
    # 预览图路径解析
    # ============================================================
    @staticmethod
    def _resolve_preview_path(mod_path, stored_path):
        """
        解析预览图路径，兼容 Mod 文件夹移动（开关）导致的路径变化。

        - 相对路径：拼接到 mod_path 后面
        - 绝对路径：直接使用；若路径中包含 Mods/ 或 Disabled_Mods/ 但文件不存在，
          尝试交换文件夹名称（应对 Mod 开关移动）
        """
        if not stored_path:
            return ""

        if not os.path.isabs(stored_path):
            full = os.path.join(mod_path, stored_path)
            return full if os.path.isfile(full) else ""

        if os.path.isfile(stored_path):
            return stored_path

        norm = os.path.normpath(stored_path)
        mods_sep = f"{os.sep}Mods{os.sep}"
        disabled_sep = f"{os.sep}Disabled_Mods{os.sep}"
        if mods_sep in norm:
            alt = norm.replace(mods_sep, disabled_sep)
            if os.path.isfile(alt):
                return alt
        elif disabled_sep in norm:
            alt = norm.replace(disabled_sep, mods_sep)
            if os.path.isfile(alt):
                return alt
        return ""

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
        resolved_img = self._resolve_preview_path(mod["path"], image_path)
        if resolved_img and HAS_PIL:
            try:
                img = Image.open(resolved_img)
                img.thumbnail((self.PREVIEW_SIZE, self.PREVIEW_SIZE), Image.LANCZOS)
                ctk_img = CTkImage(light_image=img, dark_image=img,
                                   size=(self.PREVIEW_SIZE, self.PREVIEW_SIZE))
                self._preview_ctk_images[name] = ctk_img
                preview_label = ctk.CTkLabel(row, image=ctk_img, text="",
                                              cursor="hand2")
                preview_label.pack(side="left", padx=(0, 6))
                preview_label.bind("<Button-1>",
                                   lambda e, p=resolved_img: self._show_full_image(p))
                for child in preview_label.winfo_children():
                    child.bind("<Button-1>",
                               lambda e, p=resolved_img: self._show_full_image(p))
                preview_label._image_path = resolved_img
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

        status_label = ctk.CTkLabel(
            right_frame,
            text=t("mod_list.status_enabled", "启用") if enabled else t("mod_list.status_disabled", "禁用"),
            font=self._font(9),
            text_color="#3fb950" if enabled else "gray"
        )
        status_label.pack(side="left", padx=(0, 4))

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
        is_checked = self._group_checkbox_vars[gname].get()
        for mod_name, var in self._checkbox_vars.items():
            if self._mod_to_group.get(mod_name) == gname:
                var.set(is_checked)

    def _on_mod_checkbox_toggle(self, mod_name):
        gname = self._mod_to_group.get(mod_name)
        if gname and gname in self._group_checkbox_vars:
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
    def _show_input_dialog(self, title, prompt):
        result = [None]

        dialog = ctk.CTkToplevel(self.root)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.lift()
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(dialog, text=prompt).pack(padx=20, pady=(20, 10))
        entry = ctk.CTkEntry(dialog, width=250)
        entry.pack(padx=20, pady=(0, 20))
        entry.focus()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))

        def _ok():
            result[0] = entry.get()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ctk.CTkButton(btn_frame, text=t("dialog.ok", "确定"), command=_ok).pack(
            side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(btn_frame, text=t("dialog.cancel", "取消"), command=_cancel).pack(
            side="right", expand=True, fill="x", padx=(5, 0))

        entry.bind("<Return>", lambda e: _ok())
        dialog.bind("<Escape>", lambda e: _cancel())

        dialog.update_idletasks()
        dw = dialog.winfo_width()
        dh = dialog.winfo_height()
        px = self.root.winfo_rootx()
        py = self.root.winfo_rooty()
        pw = self.root.winfo_width()
        ph = self.root.winfo_height()
        x = max(0, px + (pw - dw) // 2)
        y = max(0, py + (ph - dh) // 2)
        dialog.geometry(f"+{x}+{y}")

        dialog.grab_set()
        self.root.wait_window(dialog)
        return result[0]

    def _create_group(self):
        result = self._show_input_dialog(
            t("group_dialog.title_create", "新建分组"),
            t("group_dialog.prompt_name", "输入分组名称："))
        if result and result.strip():
            gname = result.strip()
            groups = ConfigManager.get_mod_groups()
            order = ConfigManager.get_group_order()
            if gname in groups:
                messagebox.showwarning(
                    t("group_dialog.already_exists", "已存在"),
                    t("group_dialog.already_exists_msg", "分组 \"{name}\" 已存在").format(name=gname))
                return
            groups[gname] = []
            order.append(gname)
            ConfigManager.set_mod_groups(groups)
            ConfigManager.set_group_order(order)
            self._refresh()

    def _manage_groups(self):
        def _get_ordered():
            groups = ConfigManager.get_mod_groups()
            order = ConfigManager.get_group_order()
            ordered_groups = [g for g in order if g in groups]
            other_groups = [g for g in groups if g not in ordered_groups]
            return groups, order, ordered_groups + other_groups

        groups, order, all_groups = _get_ordered()

        if not all_groups:
            messagebox.showinfo(
                t("dialog.title_hint", "提示"),
                t("group_dialog.hint_no_groups", "当前没有任何分组，请先新建分组。"))
            return

        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("group_dialog.title_manage", "管理分组"))
        dialog.geometry("520x480")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text=t("group_dialog.label_existing", "现有分组（点击选择）:"),
            font=self._font(13, weight="bold")
        ).pack(padx=20, pady=(16, 4), anchor="w")

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
        group_buttons = {}

        def select_group(gname):
            selected_group[0] = gname
            mods = groups.get(gname, [])
            empty_text = t("group_dialog.label_info_empty", "(空)")
            info_text = t("group_dialog.label_info_mods", "包含: {mods}").format(
                mods=", ".join(mods) if mods else empty_text)
            info_label.configure(text=info_text)
            for g, btn in group_buttons.items():
                if g == gname:
                    btn.configure(fg_color=("#3B8ED0", "#1F6AA5"))
                else:
                    btn.configure(fg_color=("gray85", "gray25"))

        def _rebuild_dialog():
            nonlocal groups, order, all_groups
            groups, order, all_groups = _get_ordered()
            if not all_groups:
                dialog.destroy()
                self._refresh()
                return
            selected_group[0] = None
            info_label.configure(text="")
            for w in list_frame.winfo_children():
                w.destroy()
            group_buttons.clear()
            for gname in all_groups:
                mod_count = len(groups.get(gname, []))
                btn = ctk.CTkButton(
                    list_frame, text=f"📁 {gname}  ({mod_count} Mods)",
                    anchor="w",
                    font=self._font(11),
                    fg_color=("gray85", "gray25"),
                    hover_color=("gray75", "gray35"),
                    text_color=("gray20", "gray85"),
                    command=lambda g=gname: select_group(g),
                )
                btn.pack(fill="x", pady=2)
                group_buttons[gname] = btn
            self._refresh()

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
                messagebox.showwarning(
                    t("dialog.title_warning", "提示"),
                    t("group_dialog.select_first", "请先选择一个分组"))
                return
            new_name = self._show_input_dialog(
                t("group_dialog.title_rename", "重命名分组"),
                t("group_dialog.prompt_rename", "将 \"{name}\" 重命名为：").format(name=gname))
            if new_name and new_name.strip() and new_name.strip() != gname:
                nn = new_name.strip()
                if nn in groups:
                    messagebox.showwarning(
                        t("group_dialog.already_exists", "已存在"),
                        t("group_dialog.already_exists_msg", "分组 \"{name}\" 已存在").format(name=nn))
                    return
                groups[nn] = groups.pop(gname)
                if gname in order:
                    order[order.index(gname)] = nn
                ConfigManager.set_mod_groups(groups)
                ConfigManager.set_group_order(order)
                _rebuild_dialog()

        def delete_group():
            gname = selected_group[0]
            if not gname:
                return
            if messagebox.askyesno(
                t("group_dialog.title_delete_confirm", "确认删除"),
                t("group_dialog.msg_delete_confirm", "确定要删除分组 \"{name}\" 吗？\n（Mod 不会被删除，只是移除分组）").format(name=gname)):
                groups.pop(gname, None)
                if gname in order:
                    order.remove(gname)
                ConfigManager.set_mod_groups(groups)
                ConfigManager.set_group_order(order)
                _rebuild_dialog()

        def create_group():
            result = self._show_input_dialog(
                t("group_dialog.title_create", "新建分组"),
                t("group_dialog.prompt_name", "输入分组名称："))
            if result and result.strip():
                gname = result.strip()
                if gname in groups:
                    messagebox.showwarning(
                        t("group_dialog.already_exists", "已存在"),
                        t("group_dialog.already_exists_msg", "分组 \"{name}\" 已存在").format(name=gname))
                    return
                groups[gname] = []
                if not order:
                    order.append(gname)
                else:
                    idx = order.index(selected_group[0]) + 1 if selected_group[0] in order else len(order)
                    order.insert(idx, gname)
                ConfigManager.set_mod_groups(groups)
                ConfigManager.set_group_order(order)
                _rebuild_dialog()

        ctk.CTkButton(btn_row, text=t("group_dialog.btn_rename", "✏️ 重命名"), width=80,
                      command=rename_group).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text=t("group_dialog.btn_delete", "🗑️ 删除分组"), width=80,
                      fg_color="#da3633", hover_color="#f85149",
                      command=delete_group).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text=t("group_dialog.btn_create", "➕ 新建"), width=80,
                      fg_color="#2ea043", hover_color="#3fb950",
                      command=create_group).pack(side="left")
        ctk.CTkButton(btn_row, text=t("group_dialog.btn_close", "关闭"), width=60,
                      command=dialog.destroy).pack(side="right")

    # ============================================================
    # 更多菜单
    # ============================================================
    def _show_more_menu(self, mod):
        name = mod["name"]
        import tkinter as tk
        menu = tk.Menu(self.root, tearoff=0,
                       bg="#2b2b2b", fg="#e0e0e0",
                       activebackground="#3B8ED0", activeforeground="white",
                       font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))), bd=1, relief="flat")

        current_note = ConfigManager.get_mod_notes().get(name, "")
        note_has_label = t("more_menu.edit_note_has", " (已有)") if current_note else ""
        menu.add_command(
            label=t("more_menu.edit_note", "📝 编辑备注") + note_has_label,
            command=lambda: self._edit_note(mod),
        )

        current_img = ConfigManager.get_mod_images().get(name, "")
        img_has_label = t("more_menu.set_preview_has", " (已设置)") if current_img else ""
        menu.add_command(
            label=t("more_menu.set_preview", "🖼️ 设置预览图") + img_has_label,
            command=lambda: self._set_preview_image(mod),
        )

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
            group_menu.add_command(label=t("more_menu.no_groups", "  (无分组，请先创建)"), state="disabled")

        menu.add_cascade(label=t("more_menu.group_add_remove", "📁 添加到分组 / 移出分组"), menu=group_menu)

        if current_img:
            menu.add_command(label=t("more_menu.clear_preview", "🗑️ 清除预览图"), command=lambda: self._clear_preview_image(mod))
        if current_note:
            menu.add_command(label=t("more_menu.clear_note", "🗑️ 清除备注"), command=lambda: self._clear_note(mod))

        row_info = self._mod_rows.get(name)
        if row_info:
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
        result = self._show_input_dialog(
            t("note_dialog.title", "编辑备注"),
            t("note_dialog.prompt", "为 Mod \"{name}\" 设置备注名称：").format(name=name))
        if result is not None:
            ConfigManager.set_mod_note(name, result.strip())
            self._refresh()

    def _clear_note(self, mod):
        ConfigManager.set_mod_note(mod["name"], "")
        self._refresh()

    def _set_preview_image(self, mod):
        if not HAS_PIL:
            messagebox.showwarning(
                t("dialog.title_warning", "缺少依赖"),
                t("preview_dialog.missing_dep", "预览图功能需要 Pillow 库。\n\n请运行: pip install Pillow"))
            return
        path = filedialog.askopenfilename(
            title=t("preview_dialog.title", "选择预览图片"),
            filetypes=[(t("preview_dialog.filetypes", "图片文件"), "*.png *.jpg *.jpeg *.gif *.bmp"), ("All Files", "*.*")],
        )
        if path:
            mod_dir = os.path.normpath(mod["path"])
            norm_path = os.path.normpath(path)
            if norm_path.startswith(mod_dir + os.sep):
                stored = os.path.relpath(norm_path, mod_dir)
            else:
                stored = norm_path
            ConfigManager.set_mod_image(mod["name"], stored)
            self._refresh()

    def _clear_preview_image(self, mod):
        ConfigManager.set_mod_image(mod["name"], "")
        self._refresh()

    # ============================================================
    # 全屏预览原图
    # ============================================================
    def _show_full_image(self, image_path):
        if not HAS_PIL or not os.path.isfile(image_path):
            return
        try:
            pil_img = Image.open(image_path)
            orig_w, orig_h = pil_img.size

            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            max_w = int(screen_w * 0.6)
            max_h = int(screen_h * 0.6)

            scale = min(1.0, max_w / orig_w, max_h / orig_h)
            if scale < 1.0:
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)
                resample = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
                display_img = pil_img.resize((new_w, new_h), resample)
            else:
                new_w, new_h = orig_w, orig_h
                display_img = pil_img

            win = ctk.CTkToplevel(self.root)
            win.title(t("preview.title", "图片预览 - {name}").format(name=os.path.basename(image_path)))
            win.geometry(f"{new_w}x{new_h}")
            win.resizable(False, False)
            win.attributes("-topmost", True)
            win.lift()

            x = (screen_w - new_w) // 2
            y = (screen_h - new_h) // 2
            win.geometry(f"+{x}+{y}")

            ctk_img = CTkImage(light_image=display_img, dark_image=display_img, size=(new_w, new_h))
            img_label = ctk.CTkLabel(win, image=ctk_img, text="")
            img_label.image = ctk_img
            img_label.pack(fill="both", expand=True)

            win.bind("<Escape>", lambda e: win.destroy())

            win.focus_force()

        except Exception:
            pass

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
            messagebox.showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            row_info = self._mod_rows.get(mod["name"])
            if row_info:
                row_info["switch_var"].set(mod["enabled"])
            return

        name = mod["name"]
        currently_enabled = mod["enabled"]
        action_key = "disable" if currently_enabled else "enable"
        action_display = t("dialog.action_disable", "禁用") if currently_enabled else t("dialog.action_enable", "启用")

        if not messagebox.askyesno(
            t("dialog.title_confirm", "确认操作"),
            t("dialog.toggle_confirm", "确定要{action} Mod \"{name}\" 吗？\n\n这将会移动整个 Mod 文件夹。").format(
                action=action_display, name=name)):
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
        self.progress_text.configure(
            text=t("progress.toggling", "正在{action}: {name} ...").format(action=action_display, name=name))

        def file_cb(current, total, bytes_done, status):
            pct = current / total if total > 0 else 1.0
            self.root.after(0, self._update_progress, pct, status)

        def worker():
            try:
                self.mod_manager.toggle_mod(name, currently_enabled, file_cb)
                self.root.after(0, self._on_toggle_complete, name, action_key, True, "")
            except Exception as e:
                self.root.after(0, self._on_toggle_complete, name, action_key, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # 批量切换
    # ============================================================
    def _batch_toggle(self, enable):
        if self.is_operating:
            messagebox.showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            return

        selected = self._get_selected_mods()
        if not selected:
            messagebox.showinfo(
                t("dialog.title_hint", "提示"),
                t("dialog.select_mods_first", "请先勾选要操作的 Mod"))
            return

        action_key = "enable" if enable else "disable"
        action_display = t("dialog.action_enable", "启用") if enable else t("dialog.action_disable", "禁用")
        to_toggle = [m for m in selected if m["enabled"] != enable]
        already = len(selected) - len(to_toggle)

        skip_msg = ""
        if already > 0:
            skip_msg = "\n" + t("dialog.batch_skip", "（{count} 个已处于目标状态，将跳过）").format(count=already)

        if not messagebox.askyesno(
            t("dialog.title_confirm", "确认批量操作"),
            t("dialog.batch_confirm", "确定要批量{action} {count} 个 Mod 吗？{skip}\n\n这将会移动 Mod 文件夹。").format(
                action=action_display, count=len(to_toggle), skip=skip_msg)):
            return

        if not to_toggle:
            messagebox.showinfo(
                t("dialog.title_hint", "提示"),
                t("dialog.already_target_state", "所选 Mod 均已处于目标状态"))
            return

        self.is_operating = True
        self._set_ui_enabled(False)

        self.progress_frame.pack(fill="x", padx=16, pady=(6, 0))
        self.progress_bar.pack(side="left", padx=(10, 8))
        self.progress_text.pack(side="left")
        self.progress_bar.set(0)
        self.progress_text.configure(
            text=t("progress.batch_toggling", "正在批量{action}... ({current}/{total})").format(
                action=action_display, current=0, total=len(to_toggle)))

        def file_cb(current, total, bytes_done, status):
            pass

        def mod_cb(idx, total, status):
            pct = idx / total
            self.root.after(0, self._update_progress, pct,
                            t("progress.batch_toggling", "正在批量{action}... ({current}/{total}) {status}").format(
                                action=action_display, current=idx, total=total, status=status))

        def worker():
            results = self.mod_manager.toggle_mods_batch(
                to_toggle, enable,
                progress_callback=mod_cb,
                file_progress_callback=file_cb,
            )
            self.root.after(0, self._on_batch_complete, results, action_key, action_display)

        threading.Thread(target=worker, daemon=True).start()

    def _on_batch_complete(self, results, action_key, action_display):
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
            messagebox.showwarning(
                t("dialog.batch_result_title", "批量操作结果"),
                t("dialog.batch_result_fail", "批量{action}完成：成功 {success} 个，失败 {fail} 个\n\n{detail}").format(
                    action=action_display, success=success, fail=fail, detail=detail))
        else:
            self.status_label.configure(
                text=t("status.batch_complete", "批量{action}完成: 成功 {success} 个").format(
                    action=action_display, success=success))

        self._refresh()

    def _update_progress(self, pct, status):
        self.progress_bar.set(pct)
        self.progress_text.configure(text=status)

    def _on_toggle_complete(self, name, action_key, success, error_msg):
        self.progress_frame.pack_forget()
        self.progress_bar.pack_forget()
        self.progress_text.pack_forget()
        self._set_ui_enabled(True)
        self.is_operating = False

        if success:
            if action_key == "enable":
                msg = t("status.toggled_enable", "已启用: {name}").format(name=name)
            else:
                msg = t("status.toggled_disable", "已禁用: {name}").format(name=name)
            self.status_label.configure(text=msg)
            self._refresh()
        else:
            action_display = t("dialog.action_enable", "启用") if action_key == "enable" else t("dialog.action_disable", "禁用")
            messagebox.showerror(
                t("dialog.operation_failed", "操作失败"),
                t("dialog.cannot_toggle", "无法{action} Mod \"{name}\":\n{error}").format(
                    action=action_display, name=name, error=error_msg))
            self.status_label.configure(
                text=t("status.toggle_failed", "{action}失败: {name}").format(
                    action=action_display, name=name))

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
            text=t("status.stats", "已启用: {enabled} 个  |  已禁用: {disabled} 个  |  共计: {total} 个 Mod").format(
                enabled=enabled_count, disabled=disabled_count, total=len(self.mods_data))
        )

    def run(self):
        self.root.mainloop()