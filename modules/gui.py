# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - GUI 主界面模块
基于 customtkinter 的 Mod 管理器主窗口。
"""

import os
import math
import re
import subprocess
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog
from urllib.parse import urlparse

import httpx
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

from modules.config import APP_DIR, ConfigManager, README_LABELS
from modules.dialogs import (
    _apply_dialog_titlebar_color,
    askyesno,
    showerror,
    showinfo,
    showwarning,
)
from modules.config import get_gb_download_dir
from modules.config import get_patreon_download_dir
from modules.cleanup import (
    clean_all,
    cleanup_targets,
    format_size,
    measure_all,
)
from modules.ai_translate import (
    get_ai_api_key,
    list_models,
    set_ai_api_key,
    translate_text,
)
from modules.catalog_view import (
    CARD,
    COMPACT,
    DETAILED,
    VIEW_MODE_ORDER,
    LocalCatalogState,
    fit_card_text,
    normalize_view_mode,
)
from modules.local_preview_cache import LocalPreviewCache
from modules.mod_ops import ModManager, find_readme_files
from modules.archive_installer import (
    ArchiveInstallError,
    InstallSelection,
    cleanup_staging,
    cleanup_target_temporaries,
    format_bytes,
    inspect_zip,
    install_loose_file,
    install_zip,
    unique_target_name,
    validate_mod_name,
)
from modules.gamebanana import GameBananaClient
from modules.online_browser import OnlineBrowserFrame
from modules.patreon_browser import PatreonBrowserFrame
from modules.source_store import save_gamebanana_source, get_installed_sources, save_gamebanana_cover
from modules.source_store import save_patreon_source
from modules.update_checker import check_file
from modules.update_manager import update_from_zip, restore_backup
from modules.source_store import update_gamebanana_source, restore_source_from_manifest
from modules.i18n import t, get_i18n


def _patch_transient_titlebar_color():
    """禁用库的延迟标题栏重绘（transient 后 20ms / resizable 后 10ms）。

    customtkinter 的 _windows_set_titlebar_color() 通过 withdraw+update
    强制重绘标题栏，其 deiconify 延迟 5ms，在窗口被 grab_set() 之后运行
    会导致 Tk 事件循环卡死（与 online_browser 同款问题，见
    online_browser.py:1805）。这里统一设置
    _deactivate_windows_window_header_manipulation 让这些延迟回调变为
    空操作；标题栏重绘改由 grab_set() 补丁在 grab 前同步完成。
    """
    if not sys.platform.startswith("win"):
        return
    original = ctk.CTkToplevel.transient

    def transient_with_titlebar_color(self, master=None):
        result = original(self, master)
        try:
            self._deactivate_windows_window_header_manipulation = True
        except Exception:
            pass
        return result

    ctk.CTkToplevel.transient = transient_with_titlebar_color


def _patch_grab_set_titlebar_color():
    """grab_set() 前同步完成标题栏重绘。

    所有对话框都在控件构建完成后才调用 grab_set()，此时窗口尚未被
    grab，withdraw→update→deiconify 周期安全（不会卡死事件循环），
    且标题栏深色立即生效。"""
    if not sys.platform.startswith("win"):
        return
    original = ctk.CTkToplevel.grab_set

    def grab_set_with_titlebar(self):
        _apply_dialog_titlebar_color(self)
        return original(self)

    ctk.CTkToplevel.grab_set = grab_set_with_titlebar


_patch_transient_titlebar_color()
_patch_grab_set_titlebar_color()


class ModManagerApp:
    PREVIEW_SIZE = (85, 48)
    CARD_WIDTH = 256
    CARD_GAP = 4

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
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.mod_manager = None
        self.mods_data = []
        self.is_operating = False
        self._operation_cancel_event = None
        self._operation_thread = None
        self._closing = False
        self._current_page = "local"
        self._online_download = None
        self._online_source = None
        self._patreon_source = None
        self._checking_updates = False
        self._checkbox_vars = {}  # mod_name -> ctk.BooleanVar（该名称最新实例）
        self._group_checkbox_vars = {}  # group_name -> ctk.BooleanVar
        self._group_headers = {}  # group_name -> header frame
        self._group_contents = {}  # group_name -> content frame
        self._group_first_mod = {}  # group_name -> first mod name (for A-Z scroll)
        self._mod_to_group = {}  # mod_name -> group_name
        self._group_mods = {}  # group_name -> [mod names]
        self._mod_rows = {}  # mod_name -> [row handles]
        self._preview_ctk_images = {}  # mod_name -> CTkImage
        self._render_generation = 0
        self._preview_targets = {}
        self._readme_targets = {}
        # 分组级 A-Z 索引（全局右侧栏，跳转到分组标题）
        self._primary_alpha_index = {}  # letter -> 第一个匹配的分组名
        self._primary_alpha_buttons = {}  # letter -> button
        self._ungrouped_btn = None  # 未分组专用索引按钮
        self._sorted_group_names = []  # 按名称排序后的分组名列表（未分组除外）
        # 分组内部的迷你 A-Z 索引栏
        self._group_mini_alpha_bars = {}  # group_name -> {"frame", "buttons", "index"}

        # 语言切换（设置菜单中的子菜单）

        # 工具栏可翻译控件引用
        self._toolbar_widgets = {}
        self._local_state = LocalCatalogState(
            view_mode=normalize_view_mode(ConfigManager.get_view_mode("local")))
        self._view_mode = self._local_state.view_mode
        self._view_mode_var = None
        self._card_columns = None
        self._card_resize_job = None
        self._card_area_width = 0
        self._card_watch_job = None

        # 动态 DPI 缩放
        self._dpi_scale = self._get_dpi_scale_factor()
        preview_cache_dir = os.path.join(
            APP_DIR, "data", "cache", "local_previews")
        self._local_preview_cache = LocalPreviewCache(preview_cache_dir)
        self._preview_executor = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="local-preview")
        self._readme_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="local-readme")
        self._background_futures = set()
        self._background_futures_lock = threading.Lock()
        self._track_background_future(
            self._preview_executor.submit(self._local_preview_cache.prune))

        self._build_ui()
        cleanup_staging()
        self._card_watch_job = self.root.after(150, self._watch_card_area)
        self._load_config_and_refresh(defer=True)

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
        # ---- 菜单栏（经典 Win32：位于最顶部，下方一条分割线）----
        menubar = ctk.CTkFrame(self.root, height=36, corner_radius=0,
                               fg_color=("gray90", "gray17"))
        menubar.pack(fill="x", padx=0, pady=0)
        menubar.pack_propagate(False)

        self._settings_btn = ctk.CTkButton(
            menubar, text=t("top.settings", "⚙️ 设置") + " ▾",
            width=80, height=26, font=self._font(11),
            fg_color="transparent", corner_radius=4,
            hover_color=("gray80", "gray30"),
            text_color=("gray15", "gray90"),
            command=self._show_settings_menu)
        self._settings_btn.pack(side="left", padx=(8, 2), pady=5)

        self._more_btn = ctk.CTkButton(
            menubar, text=t("top.more_mod_settings", "更多 Mod 设置") + " ▾",
            width=116, height=26, font=self._font(11),
            fg_color="transparent", corner_radius=4,
            hover_color=("gray80", "gray30"),
            text_color=("gray15", "gray90"),
            command=self._show_mod_settings_menu)
        self._more_btn.pack(side="left", padx=2, pady=5)

        self._about_btn = ctk.CTkButton(
            menubar, text=t("about.button", "ℹ️ 关于"),
            width=72, height=26, font=self._font(11),
            fg_color="transparent", corner_radius=4,
            hover_color=("gray80", "gray30"),
            text_color=("gray15", "gray90"),
            command=self._show_about_dialog)
        self._about_btn.pack(side="left", padx=(2, 8), pady=5)

        # 菜单栏与下方区域的分割线
        menubar_sep = ctk.CTkFrame(self.root, height=1, corner_radius=0,
                                   fg_color=("gray50", "gray30"))
        menubar_sep.pack(fill="x", padx=0, pady=0)

        # ---- 标题栏 ----
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

        self._local_page_btn = ctk.CTkButton(
            top_frame, text=t("top.local_page", "本地 Mods"), width=86, height=30,
            command=lambda: self._switch_page("local"))
        self._local_page_btn.pack(side="left", padx=2, pady=12)
        self._online_page_btn = ctk.CTkButton(
            top_frame, text=t("top.online_page", "GameBanana"), width=86, height=30,
            command=lambda: self._switch_page("online"))
        self._online_page_btn.pack(side="left", padx=2, pady=12)
        self._patreon_page_btn = ctk.CTkButton(
            top_frame, text=t("top.patreon_page", "Patreon"), width=86, height=30,
            command=lambda: self._switch_page("patreon"))
        self._patreon_page_btn.pack(side="left", padx=2, pady=12)

        self.path_label = ctk.CTkLabel(
            top_frame, text=t("top.no_folder", "未选择文件夹"),
            font=self._font(11),
            text_color="gray"
        )
        self.path_label.pack(side="right", padx=(0, 10), pady=12)

        self._browse_btn = ctk.CTkButton(
            top_frame, text=t("top.browse", "📁 选择文件夹"), width=110, height=30,
            font=self._font(11),
            command=self._browse_folder
        )
        if not ConfigManager.get_game_path():
            self._browse_btn.pack(side="right", padx=(0, 8), pady=12)

        # ---- 工具栏 ----
        toolbar = ctk.CTkFrame(self.root, height=42, corner_radius=0,
                               fg_color=("gray90", "gray17"))
        toolbar.pack(fill="x", padx=0, pady=(0, 0))
        toolbar.pack_propagate(False)
        self._local_toolbar = toolbar

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

        self._refresh_btn = ctk.CTkButton(
            toolbar, text=t("top.refresh", "🔄 刷新"), width=70, height=26,
            font=self._font(11),
            command=self._refresh
        )
        self._refresh_btn.pack(side="right", padx=(0, 14), pady=7)

        w_install_zip = ctk.CTkButton(
            toolbar, text=t("toolbar.install_zip", "安装 ZIP"),
            width=82, height=26, font=self._font(10),
            command=self._install_zip_from_file,
        )
        w_install_zip.pack(side="right", padx=(2, 2), pady=7)
        self._toolbar_widgets["install_zip"] = w_install_zip

        self._view_mode_var = ctk.StringVar(value=self._view_mode)
        self._view_switch = ctk.CTkSegmentedButton(
            toolbar,
            values=list(VIEW_MODE_ORDER),
            variable=self._view_mode_var,
            command=self._on_view_mode_change,
            width=220, height=28,
            font=self._font(10),
        )
        self._view_switch.pack(side="right", padx=(6, 2), pady=7)
        self._update_view_switch_labels()

        # ---- 主体区域 ----
        body = ctk.CTkFrame(self.root, fg_color=("gray95", "gray14"))
        body.pack(fill="both", expand=True, padx=0, pady=0)
        self._local_body = body

        # Mod 列表（可滚动）
        self.scroll_frame = ctk.CTkScrollableFrame(body, label_text="")
        self.scroll_frame.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=0)

        # A-Z 侧边栏（仅分组级跳转）
        self._build_alphabet_bar(body)

        self._online_frame = OnlineBrowserFrame(
            self.root, self.root, self._install_online_file)
        self._online_frame.pack_forget()

        self._patreon_frame = PatreonBrowserFrame(
            self.root, self.root,
            self._install_patreon_file, self._open_patreon_external)
        self._patreon_frame.pack_forget()

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
        self.progress_cancel_button = ctk.CTkButton(
            self.progress_frame,
            text=t("zip_install.cancel_install", "取消安装"),
            width=86, height=24,
            command=self._cancel_current_operation,
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
        self._local_page_btn.configure(text=t("top.local_page", "本地 Mods"))
        self._online_page_btn.configure(text=t("top.online_page", "GameBanana"))
        self._patreon_page_btn.configure(text=t("top.patreon_page", "Patreon"))
        self._browse_btn.configure(text=t("top.browse", "📁 选择文件夹"))
        self._refresh_btn.configure(text=t("top.refresh", "🔄 刷新"))
        self._settings_btn.configure(text=t("top.settings", "⚙️ 设置") + " ▾")
        self._more_btn.configure(text=t("top.more_mod_settings", "更多 Mod 设置") + " ▾")
        self._about_btn.configure(text=t("about.button", "ℹ️ 关于"))

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
        tw["install_zip"].configure(text=t("toolbar.install_zip", "安装 ZIP"))
        self.progress_cancel_button.configure(
            text=t("zip_install.cancel_install", "取消安装"))
        self._update_view_switch_labels()

        try:
            self._online_frame.apply_language()
        except Exception:
            pass

        try:
            self._patreon_frame.apply_language()
        except Exception:
            pass

        self._refresh()

    def _switch_page(self, page):
        if page == self._current_page:
            if page == "online":
                self._online_frame.begin()
                self._online_frame.reload()
            elif page == "patreon":
                self._patreon_frame.begin()
            return
        self._current_page = page
        if page == "local":
            self._online_frame.pack_forget()
            self._patreon_frame.pack_forget()
            self._local_toolbar.pack(fill="x", padx=0, pady=0, before=self.status_bar)
            self._local_body.pack(fill="both", expand=True, padx=0, pady=0, before=self.status_bar)
            self._refresh()
        elif page == "patreon":
            self._local_toolbar.pack_forget()
            self._local_body.pack_forget()
            self._online_frame.pack_forget()
            self._patreon_frame.pack(fill="both", expand=True, padx=0, pady=0, before=self.status_bar)
            self._patreon_frame.begin()
        else:
            self._local_toolbar.pack_forget()
            self._local_body.pack_forget()
            self._patreon_frame.pack_forget()
            self._online_frame.pack(fill="both", expand=True, padx=0, pady=0, before=self.status_bar)
            self._online_frame.begin()
            self._online_frame.begin_preload()
            self._online_frame.reload()

    def _check_updates(self):
        if self.is_operating:
            showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            return
        if self._checking_updates:
            return
        records = [record for record in get_installed_sources().values()
                   if record.get("provider") == "gamebanana"]
        if not records:
            showinfo(
                t("dialog.title_hint", "提示"),
                t("online.no_managed_mods", "没有找到可检查更新的 GameBanana Mod"))
            return
        self._checking_updates = True
        self.status_label.configure(text=t("online.checking_updates", "正在检查 Mod 更新..."))

        def worker():
            client = GameBananaClient(proxy=ConfigManager.get_proxy() or None)
            results = []
            try:
                for record in records:
                    try:
                        details = client.details(record["submission_id"], force=True)
                        installed = type("Installed", (), {
                            "file_id": record.get("file_id", 0),
                            "file_name": record.get("file_name", ""),
                            "date_added": record.get("file_date_added", 0),
                            "description": record.get("file_description", ""),
                            "md5": record.get("file_md5"),
                        })()
                        results.append((record, check_file(installed, details)))
                    except Exception as exc:
                        results.append((record, type("Result", (), {
                            "kind": "error", "error": str(exc)})()))
            finally:
                client.close()
            self.root.after(0, self._show_update_results, results)
        threading.Thread(target=worker, daemon=True).start()

    def _restore_managed_backup(self):
        records = [record for record in get_installed_sources().values()
                   if record.get("provider") == "gamebanana"]
        available = []
        for record in records:
            backup_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "data", "backups",
                record.get("instance_id", ""))
            if os.path.isdir(backup_dir) and any(
                    os.path.isdir(os.path.join(backup_dir, name)) for name in os.listdir(backup_dir)):
                available.append(record)
        if not available:
            showinfo(t("dialog.title_hint", "提示"),
                                t("online.no_backups", "没有可恢复的在线 Mod 备份"))
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("top.restore_backup", "恢复备份"))
        dialog.geometry("520x320")
        dialog.transient(self.root)
        dialog.grab_set()
        rows = ctk.CTkScrollableFrame(dialog, label_text="")
        rows.pack(fill="both", expand=True, padx=12, pady=12)
        for record in available:
            ctk.CTkButton(
                rows, text=record.get("folder_name", "-"), anchor="w",
                command=lambda item=record: self._confirm_restore(item, dialog)
            ).pack(fill="x", pady=3)

    def _confirm_restore(self, record, dialog):
        dialog.destroy()
        if not askyesno(
                t("top.restore_backup", "恢复备份"),
                t("online.restore_confirm", "恢复 {name} 的上一个版本？当前版本将被移除。").format(
                    name=record.get("folder_name", "-"))):
            return
        try:
            restore_backup(record)
            restore_source_from_manifest(record["path"], record["instance_id"])
            showinfo(t("top.restore_backup", "恢复备份"),
                                t("online.restore_success", "已恢复上一个版本"))
            self._refresh()
        except Exception as exc:
            showerror(t("online.update_failed", "更新失败"), str(exc))

    def _show_update_results(self, results):
        self._checking_updates = False
        updates = [item for item in results if item[1].kind == "update_available"]
        ambiguous = [item for item in results if item[1].kind == "ambiguous"]
        unavailable = [item for item in results
                       if item[1].kind in ("source_unavailable", "file_removed", "error")]
        lines = (["可更新: {}".format(item[0].get("folder_name", "-")) for item in updates] +
                 ["需人工选择: {}".format(item[0].get("folder_name", "-")) for item in ambiguous] +
                 ["来源不可用: {}".format(item[0].get("folder_name", "-")) for item in unavailable])
        if updates:
            self._show_update_choice(updates)
            return
        showinfo(
            t("online.update_result_title", "更新检查结果"),
            t("online.update_result", "检查了 {total} 个 Mod。\n\n{details}").format(
                total=len(results), details="\n".join(lines) or "全部为最新版本"))
        self.status_label.configure(text=t(
            "online.update_status", "更新检查完成：{count} 个可更新").format(count=len(updates)))

    def _show_update_choice(self, updates):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("online.update_result_title", "更新检查结果"))
        dialog.geometry("680x360")
        dialog.transient(self.root)
        dialog.grab_set()
        ctk.CTkLabel(
            dialog,
            text=t("online.update_choose_hint", "选择一个更新候选。更新前会自动备份当前 Mod，失败时恢复。"),
            wraplength=620, justify="left").pack(fill="x", padx=18, pady=14)
        rows = ctk.CTkScrollableFrame(dialog, label_text="")
        rows.pack(fill="both", expand=True, padx=14, pady=4)
        selected = [None]
        for record, result in updates:
            remote = result.remote_file
            row = ctk.CTkFrame(rows)
            row.pack(fill="x", pady=3)
            label = "{} -> {} ({})".format(
                record.get("folder_name", "-"), remote.name,
                remote.version or "-")
            ctk.CTkButton(
                row, text=label, anchor="w",
                command=lambda item=(record, result): self._select_update(item, selected, dialog)
            ).pack(fill="x", padx=5, pady=5)
        ctk.CTkButton(
            dialog, text=t("dialog.cancel", "取消"),
            command=dialog.destroy).pack(anchor="e", padx=18, pady=12)

    def _select_update(self, item, selected, dialog):
        selected[0] = item
        dialog.destroy()
        self._download_update(item[0], item[1].remote_file)

    def _download_update(self, record, remote_file):
        if not os.path.isdir(record.get("path", "")):
            showerror(
                t("online.download_failed", "在线下载失败"),
                t("online.update_path_missing", "受管 Mod 目录不存在，无法更新"))
            return
        self.is_operating = True
        self._operation_cancel_event = threading.Event()
        self._set_ui_enabled(False)
        self._show_operation_progress(
            t("online.downloading", "正在下载 GameBanana 文件..."), cancellable=True)

        def worker():
            try:
                download_dir = get_gb_download_dir()
                os.makedirs(download_dir, exist_ok=True)
                archive_path = os.path.abspath(os.path.join(
                    download_dir, "gb-update-{}-{}.zip".format(record["submission_id"], remote_file.id)))
                client = self._online_frame.client
                client.download(remote_file, archive_path,
                                cancel_event=self._operation_cancel_event,
                                progress_callback=lambda done, total: self.root.after(
                                    0, self._update_progress,
                                    done / total if total else 0,
                                    t("online.download_progress", "正在下载... {done}/{total}").format(
                                        done=format_bytes(done), total=format_bytes(total))))
                inspection = inspect_zip(archive_path)
                self.root.after(0, self._on_update_download_ready, record, remote_file, inspection, None)
            except Exception as exc:
                self.root.after(0, self._on_update_download_ready, record, remote_file, None, str(exc))
        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_update_download_ready(self, record, remote_file, inspection, error):
        self._operation_thread = None
        self._operation_cancel_event = None
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        if error:
            showerror(t("online.download_failed", "在线下载失败"), error)
            return
        candidates = inspection.candidates
        if len(candidates) != 1:
            showwarning(
                t("online.update_requires_single_candidate", "更新需要明确的 Mod 候选"),
                t("online.update_multiple_candidates", "更新 ZIP 包含多个候选，请先使用普通安装流程选择目标"))
            return
        if not askyesno(
                t("online.update_confirm_title", "确认更新"),
                t("online.update_confirm", "将备份并替换 {name}，是否继续？").format(
                    name=record.get("folder_name", "-"))):
            return
        self._start_update_install(record, remote_file, inspection, candidates[0])

    def _start_update_install(self, record, remote_file, inspection, candidate):
        self.is_operating = True
        self._set_ui_enabled(False)
        self._show_operation_progress(t("online.updating", "正在备份并替换 Mod..."), cancellable=True)
        self._operation_cancel_event = threading.Event()

        def progress(current, total, _stage):
            self.root.after(0, self._update_progress, current / max(total, 1),
                            t("online.update_progress", "正在准备更新... ({current}/{total})").format(current=current, total=total))

        def worker():
            backup = None
            try:
                backup = update_from_zip(
                    inspection, candidate, record["path"], record,
                    progress_callback=progress, cancel_event=self._operation_cancel_event)
                details = self._online_frame.client.details(record["submission_id"])
                update_gamebanana_source(record, details, remote_file)
                cover_url = details.images[0].url if details.images else None
                if cover_url:
                    self._save_cover_in_background(
                        record["path"], record["folder_name"], cover_url)
                self.root.after(0, self._on_update_complete, True, backup, None)
            except Exception as exc:
                if backup:
                    try:
                        restore_backup(record)
                        restore_source_from_manifest(record["path"], record["instance_id"])
                    except Exception as rollback_exc:
                        exc = RuntimeError("{}; 自动恢复失败: {}".format(exc, rollback_exc))
                self.root.after(0, self._on_update_complete, False, None, str(exc))
        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_update_complete(self, success, backup, error):
        self._operation_thread = None
        self._operation_cancel_event = None
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        if success:
            showinfo(
                t("online.update_result_title", "更新完成"),
                t("online.update_success", "更新完成，旧版本已备份。\n\n备份：{path}").format(path=backup))
            self._refresh()
        else:
            showerror(t("online.update_failed", "更新失败"), error)

    def _save_cover_in_background(self, mod_path, mod_name, cover_url):
        def worker():
            try:
                save_gamebanana_cover(
                    self._online_frame.client.fetch_image, cover_url,
                    mod_path, mod_name)
            except Exception:
                return
            try:
                if not self._closing:
                    self.root.after(0, self._refresh)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _install_online_file(self, details, remote_file):
        if self.is_operating:
            showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            return
        game_path = ConfigManager.get_game_path()
        manager = ModManager(game_path)
        valid, error, _ = manager.validate()
        if not valid:
            showwarning(t("dialog.title_warning", "提示"), error)
            return
        try:
            ConfigManager.ensure_app_dir_writable()
        except OSError as exc:
            showerror(t("dialog.title_error", "错误"), str(exc))
            return
        if not askyesno(
                t("online.install_confirm_title", "确认在线安装"),
                t("online.install_confirm", "下载并安装 {name}？\n\n文件：{file}\n大小：{size}").format(
                    name=details.name, file=remote_file.name,
                    size=format_bytes(remote_file.size))):
            return
        self.mod_manager = manager
        self.is_operating = True
        self._operation_cancel_event = threading.Event()
        self._set_ui_enabled(False)
        self._show_operation_progress(
            t("online.downloading", "正在下载 GameBanana 文件..."), cancellable=True)

        def worker():
            try:
                import os
                download_dir = get_gb_download_dir()
                os.makedirs(download_dir, exist_ok=True)
                safe_name = "gb-{}-{}-download.zip".format(details.id, remote_file.id)
                archive_path = os.path.abspath(os.path.join(download_dir, safe_name))
                client = self._online_frame.client
                client.download(
                    remote_file, archive_path,
                    cancel_event=self._operation_cancel_event,
                    progress_callback=lambda done, total: self.root.after(
                        0, self._update_progress,
                        done / total if total else 0,
                        t("online.download_progress", "正在下载... {done}/{total}").format(
                            done=format_bytes(done), total=format_bytes(total))))
                inspection = inspect_zip(archive_path)
                self.root.after(0, self._on_online_download_ready, details, remote_file, inspection, None)
            except Exception as exc:
                self.root.after(0, self._on_online_download_ready, details, remote_file, None, str(exc))
        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_online_download_ready(self, details, remote_file, inspection, error):
        self._operation_thread = None
        self._operation_cancel_event = None
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        if error:
            showerror(t("online.download_failed", "在线下载失败"), error)
            return
        selections = self._show_zip_candidates_dialog(inspection)
        if selections:
            self._online_source = (details, remote_file)
            self._start_zip_install(inspection, selections)

    # ============================================================
    # Patreon 下载与安装
    # ============================================================
    def _install_patreon_file(self, campaign_id, post, attachment):
        if self.is_operating:
            showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            return
        game_path = ConfigManager.get_game_path()
        manager = ModManager(game_path)
        valid, error, _ = manager.validate()
        if not valid:
            showwarning(t("dialog.title_warning", "提示"), error)
            return
        try:
            ConfigManager.ensure_app_dir_writable()
        except OSError as exc:
            showerror(t("dialog.title_error", "错误"), str(exc))
            return
        if not askyesno(
                t("patreon.install_confirm_title", "确认安装 Patreon Mod"),
                t("patreon.install_confirm",
                  "下载并安装 {file}？\n\n帖子：{title}").format(
                    file=attachment.get("name", ""),
                    title=post.get("title") or "-")):
            return
        self.mod_manager = manager
        self.is_operating = True
        self._operation_cancel_event = threading.Event()
        self._set_ui_enabled(False)
        self._show_operation_progress(
            t("patreon.downloading", "正在下载 Patreon 附件..."), cancellable=True)

        def worker():
            try:
                session = self._patreon_frame.ensure_session()
                download_dir = get_patreon_download_dir()
                os.makedirs(download_dir, exist_ok=True)
                file_path = session.download_attachment(
                    attachment["url"], attachment.get("name") or "file",
                    download_dir,
                    cancel_event=self._operation_cancel_event,
                    progress_callback=lambda done, total: self.root.after(
                        0, self._update_progress,
                        done / total if total else 0,
                        t("patreon.download_progress", "正在下载... {done}/{total}").format(
                            done=format_bytes(done), total=format_bytes(total))))
                if file_path is None:
                    self.root.after(0, self._on_patreon_download_ready,
                                    campaign_id, post, attachment, None, None)
                    return
                if zipfile.is_zipfile(file_path):
                    inspection = inspect_zip(file_path)
                    self.root.after(0, self._on_patreon_download_ready,
                                    campaign_id, post, attachment, inspection, file_path)
                else:
                    self.root.after(0, self._on_patreon_download_ready,
                                    campaign_id, post, attachment, None, file_path)
            except Exception as exc:
                self.root.after(0, self._on_patreon_download_ready,
                                campaign_id, post, attachment, None, str(exc))
        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_patreon_download_ready(self, campaign_id, post, attachment, inspection, file_path):
        self._operation_thread = None
        self._operation_cancel_event = None
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        if isinstance(file_path, str) and not os.path.isfile(file_path):
            showerror(t("patreon.download_failed", "Patreon 下载失败"), file_path)
            return
        if inspection is not None:
            selections = self._show_zip_candidates_dialog(inspection)
            if selections:
                self._patreon_source = (campaign_id, post, attachment)
                self._start_zip_install(inspection, selections)
            return
        if not file_path:
            return
        self._patreon_source = (campaign_id, post, attachment)
        self._start_loose_install(file_path, post)

    def _start_loose_install(self, file_path, post):
        self.is_operating = True
        self._operation_cancel_event = threading.Event()
        self._set_ui_enabled(False)
        self._show_operation_progress(
            t("patreon.installing", "正在安装独立 Mod 文件夹..."), cancellable=True)

        preferred = post.get("title") or os.path.splitext(os.path.basename(file_path))[0]

        def progress(current, total, name):
            self.root.after(0, self._update_progress,
                            current / total if total else 0,
                            t("patreon.install_progress", "正在安装 {name}...").format(
                                name=name))

        def worker():
            try:
                results = install_loose_file(
                    file_path, self.mod_manager.mods_dir,
                    self.mod_manager.disabled_dir, preferred,
                    progress_callback=progress,
                    cancel_event=self._operation_cancel_event)
                self.root.after(0, self._on_patreon_install_complete, [results], None)
            except Exception as exc:
                self.root.after(0, self._on_patreon_install_complete, [], str(exc))

        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_patreon_install_complete(self, results, error):
        self._operation_thread = None
        self._operation_cancel_event = None
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        source = self._patreon_source
        self._patreon_source = None
        if error:
            showerror(t("patreon.install_failed", "Patreon 安装失败"), error)
            self._refresh()
            return
        if not source:
            self._refresh()
            return
        campaign_id, post, attachment = source
        succeeded = [item for item in results if item.success]
        if succeeded:
            cover_url = post.get("cover_url") or post.get("cover_thumb_url")
            for item in succeeded:
                try:
                    save_patreon_source(item.target_path, campaign_id, post, attachment)
                except Exception:
                    pass
                if cover_url:
                    self._save_patreon_cover_in_background(
                        item.target_path, item.target_name, cover_url)
        self._refresh()
        if succeeded:
            self.status_label.configure(text=t(
                "patreon.install_success", "已从 Patreon 安装 {count} 个 Mod").format(
                    count=len(succeeded)))

    def _save_patreon_cover_in_background(self, mod_path, mod_name, cover_url):
        def fetch(url):
            response = httpx.get(
                url, timeout=30, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
                proxy=ConfigManager.get_proxy() or None)
            response.raise_for_status()
            return response.content

        def worker():
            try:
                save_gamebanana_cover(fetch, cover_url, mod_path, mod_name)
            except Exception:
                return
            try:
                if not self._closing:
                    self.root.after(0, self._refresh)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _open_patreon_external(self, campaign_id, post, url):
        if self.is_operating:
            showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            return
        if not askyesno(
                t("patreon.external_confirm_title", "打开外部下载链接"),
                t("patreon.external_confirm",
                  "将在浏览器窗口中打开以下链接，请在窗口中手动完成下载：\n\n{url}\n\n"
                  "下载完成后文件会被自动捕获。").format(url=url)):
            return
        self.is_operating = True
        self._operation_cancel_event = threading.Event()
        self._set_ui_enabled(False)
        self._show_operation_progress(
            t("patreon.external_waiting", "请在浏览器窗口中完成下载..."), cancellable=True)

        def worker():
            try:
                session = self._patreon_frame.ensure_session()
                file_path = session.open_external(
                    url, cancel_event=self._operation_cancel_event,
                    on_message=lambda msg: self.root.after(
                        0, self._update_progress, 0,
                        t("patreon.external_waiting", "请在浏览器窗口中完成下载...")))
                self.root.after(0, self._on_patreon_external_done,
                                campaign_id, post, file_path)
            except Exception as exc:
                self.root.after(0, self._on_patreon_external_done,
                                campaign_id, post, str(exc))

        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_patreon_external_done(self, campaign_id, post, file_path):
        self._operation_thread = None
        self._operation_cancel_event = None
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        if not file_path or not os.path.isfile(file_path):
            if isinstance(file_path, str):
                showerror(
                    t("patreon.external_failed", "外部下载失败"), file_path)
            return
        if not askyesno(
                t("patreon.external_install_title", "安装下载的文件"),
                t("patreon.external_install_confirm",
                  "已捕获文件：{name}\n\n是否安装为 Mod？").format(
                    name=os.path.basename(file_path))):
            return
        attachment = {"name": os.path.basename(file_path)}
        self._patreon_source = (campaign_id, post, attachment)
        if zipfile.is_zipfile(file_path):
            try:
                inspection = inspect_zip(file_path)
            except Exception as exc:
                showerror(
                    t("patreon.install_failed", "Patreon 安装失败"), str(exc))
                return
            selections = self._show_zip_candidates_dialog(inspection)
            if selections:
                self._start_zip_install(inspection, selections)
            else:
                self._patreon_source = None
            return
        self._start_loose_install(file_path, post)

    def _view_mode_labels(self):
        return {
            COMPACT: t("toolbar.view_compact", "☷ 紧凑列表"),
            CARD: t("toolbar.view_card", "▦ 卡片"),
            DETAILED: t("toolbar.view_detailed", "☰ 详情列表"),
        }

    def _update_view_switch_labels(self):
        labels = self._view_mode_labels()
        self._view_switch.configure(
            values=[labels[mode] for mode in VIEW_MODE_ORDER])
        self._view_mode_var.set(labels[self._view_mode])

    def _on_view_mode_change(self, selected_label):
        labels = self._view_mode_labels()
        by_label = {label: mode for mode, label in labels.items()}
        mode = by_label.get(selected_label)
        if mode is None or mode == self._view_mode:
            return
        self._view_mode = mode
        self._local_state.view_mode = mode
        if mode != CARD and self._card_resize_job is not None:
            self.root.after_cancel(self._card_resize_job)
            self._card_resize_job = None
        ConfigManager.set_view_mode("local", mode)
        self._render_mod_list()

    def _get_card_column_count(self, measured_width=None):
        if measured_width is None:
            measured_width = (
                self._card_area_width or self.scroll_frame.winfo_width()
            )
        available_width = max(
            self.CARD_WIDTH,
            (measured_width - 34) / self._dpi_scale,
        )
        return max(
            1,
            int((available_width + self.CARD_GAP) //
                (self.CARD_WIDTH + self.CARD_GAP)),
        )

    def _watch_card_area(self):
        self._card_watch_job = None
        if self.root.winfo_exists():
            self.root.update_idletasks()
            self._card_area_width = self.scroll_frame._parent_canvas.winfo_width()
            if self._view_mode == CARD and self.mods_data:
                columns = self._get_card_column_count(self._card_area_width)
                if columns != self._card_columns:
                    self._refresh_card_columns()
            self._card_watch_job = self.root.after(150, self._watch_card_area)

    def _refresh_card_columns(self):
        self._card_resize_job = None
        if self._view_mode != CARD:
            return
        columns = self._get_card_column_count()
        if columns == self._card_columns:
            return
        self._render_mod_list()
        self._sync_all_group_checkboxes()

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
        handles = self._mod_rows.get(mod_name) or []
        widget = None
        for handle in handles:
            widget = handle.get("row_frame")
            if widget:
                break
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

    def _capture_scroll_anchor(self):
        """按首个可见 Mod 的标识记录滚动锚点（与布局高度无关）。"""
        if not self._mod_rows:
            return None
        canvas = self.scroll_frame._parent_canvas
        try:
            canvas_top = canvas.winfo_rooty()
            canvas_height = canvas.winfo_height()
        except Exception:
            return None
        best = None
        for name, handles in self._mod_rows.items():
            for handle in handles:
                widget = handle.get("row_frame")
                if not widget:
                    continue
                try:
                    if not widget.winfo_exists() or not widget.winfo_manager():
                        continue
                    delta = widget.winfo_rooty() - canvas_top
                except Exception:
                    continue
                if -50 <= delta < canvas_height and (best is None or delta < best[1]):
                    best = (name, delta)
        return best

    def _restore_scroll_anchor(self, anchor):
        """按锚点 Mod 恢复滚动位置（按像素偏移换算到新布局）。"""
        if not anchor:
            return
        name, offset = anchor
        handles = self._mod_rows.get(name) or []
        widget = None
        for handle in handles:
            widget = handle.get("row_frame")
            if widget:
                break
        if not widget:
            return
        try:
            self.root.update_idletasks()
            canvas = self.scroll_frame._parent_canvas
            if not widget.winfo_exists() or not widget.winfo_manager():
                return
            delta = widget.winfo_rooty() - canvas.winfo_rooty()
            if abs(delta - offset) < 4:
                return
            bbox = canvas.bbox("all")
            content_h = bbox[3] - bbox[1] if bbox else 0
            viewport_h = canvas.winfo_height()
            if content_h <= viewport_h:
                return
            current = canvas.yview()[0]
            fraction_delta = (delta - offset) / float(content_h)
            canvas.yview_moveto(max(0.0, min(1.0, current + fraction_delta)))
        except Exception:
            return

    # ============================================================
    # 选择文件夹 / 刷新
    # ============================================================
    def _install_zip_from_file(self):
        if self.is_operating:
            showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            return

        game_path = ConfigManager.get_game_path()
        manager = ModManager(game_path)
        valid, error, _ = manager.validate()
        if not valid:
            showwarning(t("dialog.title_warning", "提示"), error)
            return
        try:
            ConfigManager.ensure_app_dir_writable()
        except OSError as exc:
            showerror(
                t("dialog.title_error", "错误"),
                t("zip_install.app_dir_readonly",
                  "程序目录不可写，无法创建安装暂存和配置文件。\n\n请将便携版移动到有写入权限的目录后重试。\n\n{error}").format(
                      error=exc))
            return

        archive_path = filedialog.askopenfilename(
            title=t("zip_install.choose_title", "选择要安装的 ZIP Mod"),
            filetypes=[
                (t("zip_install.zip_files", "ZIP 压缩包"), "*.zip"),
                (t("zip_install.all_files", "所有文件"), "*.*"),
            ],
        )
        if not archive_path:
            return

        self.mod_manager = manager
        self.is_operating = True
        self._set_ui_enabled(False)
        self._show_operation_progress(t("zip_install.inspecting", "正在安全检查 ZIP..."))

        def worker():
            try:
                inspection = inspect_zip(archive_path)
                self.root.after(0, self._on_zip_inspected, inspection, None)
            except Exception as exc:
                self.root.after(0, self._on_zip_inspected, None, str(exc))

        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_zip_inspected(self, inspection, error):
        self._operation_thread = None
        if self._closing:
            self.root.destroy()
            return
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        if error:
            showerror(
                t("zip_install.inspect_failed_title", "ZIP 检查失败"), error)
            return

        selections = self._show_zip_candidates_dialog(inspection)
        if not selections:
            self._online_source = None
            self._patreon_source = None
            return
        self._start_zip_install(inspection, selections)

    def _show_zip_candidates_dialog(self, inspection):
        result = [None]
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("zip_install.confirm_title", "确认安装 ZIP"))
        dialog.geometry("700x520")
        dialog.minsize(620, 420)
        dialog.transient(self.root)
        dialog.grab_set()

        summary = t(
            "zip_install.summary",
            "{archive}\n检测到 {candidates} 个候选 Mod，共 {files} 个文件，解压后约 {size}"
        ).format(
            archive=inspection.archive_name,
            candidates=len(inspection.candidates),
            files=inspection.file_count,
            size=format_bytes(inspection.total_size),
        )
        ctk.CTkLabel(
            dialog, text=summary, justify="left", anchor="w",
            font=self._font(12, weight="bold"),
        ).pack(fill="x", padx=18, pady=(16, 8))

        hint = t(
            "zip_install.hint",
            "勾选要安装的候选并确认文件夹名。同名项目已自动生成“保留两者”的新名称。")
        ctk.CTkLabel(
            dialog, text=hint, justify="left", anchor="w",
            wraplength=650, text_color="gray", font=self._font(10),
        ).pack(fill="x", padx=18, pady=(0, 8))

        rows_frame = ctk.CTkScrollableFrame(dialog, label_text="")
        rows_frame.pack(fill="both", expand=True, padx=16, pady=4)

        row_states = []
        reserved_names = set()
        roots = [self.mod_manager.mods_dir, self.mod_manager.disabled_dir]
        for candidate in inspection.candidates:
            suggested = unique_target_name(candidate.suggested_name, roots)
            while suggested.casefold() in reserved_names:
                suggested = unique_target_name(suggested + " (2)", roots)
            reserved_names.add(suggested.casefold())

            row = ctk.CTkFrame(rows_frame)
            row.pack(fill="x", padx=2, pady=4)
            selected_var = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(row, text="", variable=selected_var, width=24).pack(
                side="left", padx=(10, 4), pady=12)
            info = t("zip_install.candidate_info", "{files} 个文件 / {size}").format(
                files=candidate.file_count, size=format_bytes(candidate.total_size))
            ctk.CTkLabel(
                row, text=info, width=140, anchor="w", text_color="gray",
                font=self._font(9),
            ).pack(side="right", padx=(6, 10), pady=10)
            name_var = ctk.StringVar(value=suggested)
            entry = ctk.CTkEntry(row, textvariable=name_var)
            entry.pack(side="left", fill="x", expand=True, padx=(4, 6), pady=9)
            row_states.append((candidate, selected_var, name_var))

        enabled_text = t("zip_install.target_enabled", "启用（Mods）")
        disabled_text = t("zip_install.target_disabled", "禁用（Disabled_Mods）")
        target_var = ctk.StringVar(value=enabled_text)
        target_row = ctk.CTkFrame(dialog, fg_color="transparent")
        target_row.pack(fill="x", padx=18, pady=(8, 2))
        ctk.CTkLabel(
            target_row, text=t("zip_install.target_label", "安装后状态："),
            font=self._font(11),
        ).pack(side="left")
        ctk.CTkOptionMenu(
            target_row, values=[enabled_text, disabled_text], variable=target_var,
            width=210,
        ).pack(side="left", padx=8)

        button_row = ctk.CTkFrame(dialog, fg_color="transparent")
        button_row.pack(fill="x", padx=18, pady=(10, 16))

        def confirm():
            selections = []
            planned_names = set()
            for candidate, selected_var, name_var in row_states:
                if not selected_var.get():
                    continue
                name = name_var.get().strip()
                try:
                    validate_mod_name(name)
                except ArchiveInstallError as exc:
                    showwarning(
                        t("zip_install.invalid_name_title", "文件夹名无效"),
                        "{}: {}".format(candidate.suggested_name, exc),
                        parent=dialog)
                    return
                key = name.casefold()
                if key in planned_names:
                    showwarning(
                        t("zip_install.name_conflict_title", "名称冲突"),
                        t("zip_install.name_conflict", "多个候选不能使用同一个目标名称：{name}").format(name=name),
                        parent=dialog)
                    return
                if unique_target_name(name, roots) != name:
                    showwarning(
                        t("zip_install.name_conflict_title", "名称冲突"),
                        t("zip_install.existing_conflict", "Mods 或 Disabled_Mods 中已存在同名目录：{name}").format(name=name),
                        parent=dialog)
                    return
                planned_names.add(key)
                selections.append(InstallSelection(
                    candidate=candidate,
                    target_name=name,
                    enabled=target_var.get() == enabled_text,
                ))
            if not selections:
                showinfo(
                    t("dialog.title_hint", "提示"),
                    t("zip_install.select_candidate", "请至少选择一个候选 Mod"),
                    parent=dialog)
                return
            result[0] = selections
            dialog.destroy()

        ctk.CTkButton(
            button_row, text=t("zip_install.install_button", "开始安装"),
            command=confirm,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            button_row, text=t("dialog.cancel", "取消"),
            fg_color=("gray70", "gray30"), command=dialog.destroy,
        ).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        self.root.wait_window(dialog)
        return result[0]

    def _start_zip_install(self, inspection, selections):
        self.is_operating = True
        self._operation_cancel_event = threading.Event()
        self._set_ui_enabled(False)
        self._show_operation_progress(
            t("zip_install.installing", "正在安装 ZIP..."), cancellable=True)

        def progress(current, total, name):
            pct = current / total if total else 0
            status = t(
                "zip_install.install_progress",
                "正在安装 {name}... ({current}/{total} 个文件)"
            ).format(name=name, current=current, total=total)
            self.root.after(0, self._update_progress, pct, status)

        def worker():
            try:
                results = install_zip(
                    inspection, selections,
                    self.mod_manager.mods_dir, self.mod_manager.disabled_dir,
                    progress_callback=progress,
                    cancel_event=self._operation_cancel_event,
                )
                self.root.after(0, self._on_zip_install_complete, results, None)
            except Exception as exc:
                self.root.after(0, self._on_zip_install_complete, [], str(exc))

        self._operation_thread = threading.Thread(target=worker, daemon=True)
        self._operation_thread.start()

    def _on_zip_install_complete(self, results, error):
        self._operation_thread = None
        if self._closing:
            self.root.destroy()
            return
        self._hide_operation_progress()
        self._set_ui_enabled(True)
        self.is_operating = False
        self._operation_cancel_event = None
        if error:
            showerror(t("zip_install.failed_title", "ZIP 安装失败"), error)
            self._refresh()
            return

        succeeded = [item for item in results if item.success]
        failed = [item for item in results if not item.success]
        online_source = self._online_source
        self._online_source = None
        patreon_source = self._patreon_source
        self._patreon_source = None
        if succeeded and online_source:
            details, remote_file = online_source
            cover_url = details.images[0].url if details.images else None
            for item in succeeded:
                try:
                    save_gamebanana_source(item.target_path, details, remote_file)
                except Exception as exc:
                    failed.append(type("SourceFailure", (), {
                        "target_name": item.target_name, "error": str(exc)})())
                if cover_url:
                    self._save_cover_in_background(
                        item.target_path, item.target_name, cover_url)
        elif succeeded and patreon_source:
            campaign_id, post, attachment = patreon_source
            cover_url = post.get("cover_url") or post.get("cover_thumb_url")
            for item in succeeded:
                try:
                    save_patreon_source(item.target_path, campaign_id, post, attachment)
                except Exception as exc:
                    failed.append(type("SourceFailure", (), {
                        "target_name": item.target_name, "error": str(exc)})())
                if cover_url:
                    self._save_patreon_cover_in_background(
                        item.target_path, item.target_name, cover_url)
        if failed:
            details = "\n".join("{}: {}".format(item.target_name, item.error) for item in failed)
            showwarning(
                t("zip_install.result_title", "ZIP 安装结果"),
                t("zip_install.partial_result", "成功 {success} 个，失败 {failed} 个。\n\n{details}").format(
                    success=len(succeeded), failed=len(failed), details=details))
        self._refresh()
        if succeeded and not failed:
            self.status_label.configure(text=t(
                "zip_install.success_status", "已安装 {count} 个 Mod：{names}").format(
                    count=len(succeeded),
                    names=", ".join(item.target_name for item in succeeded)))

    def _show_operation_progress(self, text, cancellable=False):
        self.progress_frame.pack(fill="x", padx=16, pady=(6, 0))
        self.progress_bar.pack(side="left", padx=(10, 8))
        self.progress_text.pack(side="left")
        if cancellable:
            self.progress_cancel_button.configure(state="normal")
            self.progress_cancel_button.pack(side="right", padx=(8, 10), pady=4)
        self.progress_bar.set(0)
        self.progress_text.configure(text=text)

    def _hide_operation_progress(self):
        self.progress_frame.pack_forget()
        self.progress_bar.pack_forget()
        self.progress_text.pack_forget()
        self.progress_cancel_button.pack_forget()

    def _cancel_current_operation(self):
        if self._operation_cancel_event is not None:
            self._operation_cancel_event.set()
            self.progress_cancel_button.configure(state="disabled")
            self.progress_text.configure(
                text=t("zip_install.cancelling", "正在取消并清理暂存文件..."))

    def _on_close(self):
        if self._closing:
            return
        thread = self._operation_thread
        if thread is None or not thread.is_alive():
            self._shutdown_background_loaders()
            self.root.destroy()
            return
        self._closing = True
        self._shutdown_background_loaders()
        if self._operation_cancel_event is not None:
            self._operation_cancel_event.set()
        self._set_ui_enabled(False)
        self._show_operation_progress(
            t("zip_install.closing", "正在结束安装并清理暂存文件..."))
        self.root.after(100, self._wait_for_operation_before_close)

    def _wait_for_operation_before_close(self):
        thread = self._operation_thread
        if thread is not None and thread.is_alive():
            self.root.after(100, self._wait_for_operation_before_close)
            return
        self.root.destroy()

    def _shutdown_background_loaders(self):
        self._closing = True
        self._render_generation += 1
        with self._background_futures_lock:
            futures = tuple(self._background_futures)
        for future in futures:
            future.cancel()
        self._preview_executor.shutdown(wait=False)
        self._readme_executor.shutdown(wait=False)
        try:
            self._online_frame.destroy()
        except Exception:
            pass
        try:
            self._patreon_frame.destroy()
        except Exception:
            pass

    def _track_background_future(self, future):
        with self._background_futures_lock:
            self._background_futures.add(future)

        def discard(_done):
            with self._background_futures_lock:
                self._background_futures.discard(future)

        future.add_done_callback(discard)
        return future

    def _update_browse_btn_visibility(self):
        """选择文件夹按钮仅在尚未选择路径时显示，选中后隐藏。"""
        try:
            if ConfigManager.get_game_path():
                self._browse_btn.pack_forget()
            elif not self._browse_btn.winfo_ismapped():
                self._browse_btn.pack(side="right", padx=(0, 8), pady=12)
        except Exception:
            pass

    def _show_settings_menu(self, anchor=None):
        import tkinter as tk

        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#2b2b2b", fg="#e0e0e0",
            activebackground="#3B8ED0", activeforeground="white",
            font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))),
            bd=1, relief="flat",
        )

        lang_menu = tk.Menu(
            menu, tearoff=0,
            bg="#2b2b2b", fg="#e0e0e0",
            activebackground="#3B8ED0", activeforeground="white",
            font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))),
        )
        current = self._lang_menu_display()
        for display_value in self._lang_menu_values():
            label = f"  {'✓ ' if display_value == current else ''}{display_value}"
            lang_menu.add_command(
                label=label,
                command=lambda v=display_value: self._on_language_change(v),
            )
        menu.add_cascade(
            label=t("top.settings_language", "语言"), menu=lang_menu)
        menu.add_separator()
        menu.add_command(
            label=t("top.browse", "📁 选择文件夹"),
            command=self._browse_folder,
        )
        menu.add_separator()
        menu.add_command(
            label=t("top.cleanup", "🧹 清理缓存"),
            command=self._show_cleanup_dialog,
        )
        menu.add_separator()
        menu.add_command(
            label=t("top.ai_settings", "🌐 AI 翻译设置"),
            command=self._show_ai_settings_dialog,
        )
        menu.add_command(
            label=t("top.proxy_settings", "🛰️ 网络代理设置"),
            command=self._show_proxy_settings_dialog,
        )

        if anchor is not None:
            try:
                menu.tk_popup(
                    anchor.winfo_rootx(),
                    anchor.winfo_rooty() + anchor.winfo_height(),
                )
                menu.grab_release()
                return
            except Exception:
                pass

        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _show_mod_settings_menu(self, anchor=None):
        import tkinter as tk

        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#2b2b2b", fg="#e0e0e0",
            activebackground="#3B8ED0", activeforeground="white",
            font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))),
            bd=1, relief="flat",
        )
        menu.add_command(
            label=t("top.restore_backup", "恢复备份"),
            command=self._restore_managed_backup,
        )
        menu.add_command(
            label=t("top.check_gb_updates", "检查 GameBanana 模组更新"),
            command=self._check_updates,
        )

        if anchor is not None:
            try:
                menu.tk_popup(
                    anchor.winfo_rootx(),
                    anchor.winfo_rooty() + anchor.winfo_height(),
                )
                menu.grab_release()
                return
            except Exception:
                pass

        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    # ============================================================
    # 关于对话框（顶栏 → ℹ️ 关于）
    # ============================================================
    def _show_about_dialog(self):
        import webbrowser

        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("about.title", "关于"))
        dialog.geometry("560x640")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        body = ctk.CTkScrollableFrame(dialog, label_text="")
        body.pack(fill="both", expand=True, padx=18, pady=(16, 4))

        # 纪念图片（路径与配置文件一致：APP_DIR 同时兼容 .py 运行与打包运行）
        img_path = os.path.join(APP_DIR, "README.assets", "酸橙色的纪念.png")
        if HAS_PIL and os.path.isfile(img_path):
            try:
                pil_img = Image.open(img_path)
                orig_w, orig_h = pil_img.size
                target_w = 500
                new_h = max(1, int(orig_h * (target_w / float(orig_w))))
                resample = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
                display_img = pil_img.resize((target_w, new_h), resample)
                ctk_img = CTkImage(
                    light_image=display_img, dark_image=display_img,
                    size=(target_w, new_h))
                img_label = ctk.CTkLabel(body, image=ctk_img, text="")
                img_label.image = ctk_img
                img_label.pack(pady=(0, 12))
            except Exception:
                pass

        ctk.CTkLabel(
            body,
            text=t("about.caption",
                   "谨以此纪念 2026 年那个酸橙色的夏天——\n酸橙是夏天的颜色，也是记忆的味道。"),
            wraplength=500, justify="center",
            font=self._font(13, weight="bold"),
            text_color=("#B2500B", "#FFB74D"),
        ).pack(fill="x", pady=(0, 4))

        def divider():
            ctk.CTkFrame(body, height=1, corner_radius=0,
                         fg_color=("gray50", "gray30")).pack(fill="x", pady=14)

        divider()

        ctk.CTkLabel(
            body, text=t("about.section_about", "关于本项目"),
            font=self._font(14, weight="bold"), anchor="w",
        ).pack(fill="x", pady=(0, 6))

        def about_line(key, zh_default):
            ctk.CTkLabel(
                body, text=t(key, zh_default),
                wraplength=500, justify="left", anchor="w",
            ).pack(fill="x", pady=2)

        about_line("about.app_desc",
                   "EFMI Mod Manager 是一款基于 customtkinter 的 Windows PC Mod 管理器，"
                   "通过在 Mods 与 Disabled_Mods 目录之间移动文件夹来启用/禁用 Mod。")
        about_line("about.disclaimer",
                   "本程序不负责 Mod 的加载、解析或注入，Mod 的加载由 EFMI 在游戏启动时完成；"
                   "本程序仅提供图形化前端，用于快捷地启用或禁用 Mod。")

        repo_url = "https://github.com/gunfub/EFMI_Mod_Manager"
        repo_label = ctk.CTkLabel(
            body,
            text=t("about.repo_label",
                   "项目主页：https://github.com/gunfub/EFMI_Mod_Manager"),
            wraplength=500, justify="left", anchor="w",
            text_color=("cornflower blue", "#7FB3FF"),
            cursor="hand2",
        )
        repo_label.pack(fill="x", pady=2)
        repo_label.bind("<Button-1>", lambda e: webbrowser.open(repo_url))

        about_line("about.version_label", "版本：2.0")
        about_line("about.license_label", "开源许可证：GPLv3")

        divider()

        ctk.CTkLabel(
            body, text=t("about.section_credits", "感谢开源"),
            font=self._font(14, weight="bold"), anchor="w",
        ).pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            body,
            text=t("about.credits_intro",
                   "本软件包含以下第三方开源组件（名称、版本、许可证与版权信息）："),
            wraplength=500, justify="left", anchor="w",
            text_color="gray",
        ).pack(fill="x", pady=(0, 6))

        credits = [
            {
                "name": "customtkinter",
                "version": "5.2.2",
                "license": "MIT License",
                "copyright": "Copyright (c) 2023 Tom Schimansky",
                "url": "https://github.com/TomSchimansky/CustomTkinter",
            },
            {
                "name": "Pillow",
                "version": "10.4.0",
                "license": "HPND License",
                "copyright": "Copyright (c) 1995-2011 Fredrik Lundh and contributors\n"
                              "Copyright (c) 2010-2024 Jeffrey A. Clark and contributors",
                "url": "https://github.com/python-pillow/Pillow",
            },
            {
                "name": "httpx",
                "version": "0.28.1",
                "license": "BSD 3-Clause License",
                "copyright": "Copyright (c) 2019 Encode OSS Ltd",
                "url": "https://github.com/encode/httpx",
            },
            {
                "name": "keyring",
                "version": "25.5.0",
                "license": "MIT License",
                "copyright": "Copyright (c) Jason R. Coombs",
                "url": "https://github.com/jaraco/keyring",
            },
            {
                "name": "pypinyin",
                "version": "0.55.0",
                "license": "MIT License",
                "copyright": "Copyright (c) 2016 mozillazg, 闲耘",
                "url": "https://github.com/mozillazg/python-pinyin",
            },
            {
                "name": "pywebview",
                "version": "6.2.1",
                "license": "BSD 3-Clause License",
                "copyright": "Copyright (c) 2014-2017 Roman Sirokov",
                "url": "https://github.com/r0x0r/pywebview",
            },
            {
                "name": "PyInstaller (build-time packaging tool)",
                "version": "6.20.0",
                "license": "\nGPL-2.0-or-later (with Bootloader exception)",
                "copyright": "Copyright (c) 2010-2023 PyInstaller Development Team\n"
                              "Copyright (c) 2005-2009 Giovanni Bajo",
                "url": "https://github.com/pyinstaller/pyinstaller",
            },
        ]
        for item in credits:
            head = ctk.CTkLabel(
                body,
                text="{} {} — {}".format(item["name"], item["version"], item["license"]),
                justify="left", anchor="w",
                font=self._font(11, weight="bold"),
                text_color=("cornflower blue", "#7FB3FF"),
                cursor="hand2",
            )
            head.pack(fill="x", pady=(4, 0))
            head.bind("<Button-1>", lambda e, u=item["url"]: webbrowser.open(u))
            for line in item["copyright"].split("\n"):
                ctk.CTkLabel(
                    body, text=line,
                    wraplength=500, justify="left", anchor="w",
                    font=self._font(10),
                    text_color="gray",
                ).pack(fill="x", pady=0)

        ctk.CTkLabel(
            body,
            text=t("about.credits_footer",
                   "完整许可证文本随程序分发于 THIRD_PARTY_NOTICES.txt（点击项目名可打开对应仓库）。"),
            wraplength=500, justify="left", anchor="w",
            text_color="gray",
        ).pack(fill="x", pady=(8, 0))

        bottom = ctk.CTkFrame(dialog, fg_color="transparent")
        bottom.pack(fill="x", padx=18, pady=(4, 14))
        ctk.CTkButton(
            bottom, text=t("about.close", "关闭"), width=90,
            command=dialog.destroy).pack(side="right")

        _apply_dialog_titlebar_color(dialog)
        dialog.grab_set()
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.lift()

    def _browse_folder(self):
        path = filedialog.askdirectory(title=t("top.browse", "选择游戏 Mod 文件夹（包含 Mods 和 Disabled_Mods 的目录）"))
        if path:
            ConfigManager.set_game_path(path)
            self._load_config_and_refresh()

    # ============================================================
    # 缓存清理（设置菜单 → 🧹 清理缓存）
    # ============================================================
    def _show_cleanup_dialog(self):
        import threading

        targets = cleanup_targets()
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("cleanup.title", "清理缓存"))
        dialog.geometry("560x460")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text=t("cleanup.hint",
                   "勾选要清理的项目（显示占用空间），点击「清理所选」。\n"
                   "Patreon 浏览器缓存不影响登录状态。"),
            wraplength=520, justify="left", text_color="gray",
        ).pack(fill="x", padx=18, pady=(14, 4))

        rows = ctk.CTkScrollableFrame(dialog, label_text="")
        rows.pack(fill="both", expand=True, padx=14, pady=4)

        vars_by_key = {}
        size_labels = {}
        for target in targets:
            var = ctk.BooleanVar(value=True)
            vars_by_key[target["key"]] = var
            row = ctk.CTkFrame(rows, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkCheckBox(
                row, text=t(target["label_key"], target["key"]),
                variable=var, onvalue=True, offvalue=False,
            ).pack(side="left", fill="x", expand=True)
            size_label = ctk.CTkLabel(
                row, text="…", text_color="gray", width=90, anchor="e")
            size_label.pack(side="right", padx=(8, 4))
            size_labels[target["key"]] = size_label

        bottom = ctk.CTkFrame(dialog, fg_color="transparent")
        bottom.pack(fill="x", padx=14, pady=(2, 12))

        result_label = ctk.CTkLabel(
            bottom, text="", text_color="gray", anchor="w")
        result_label.pack(side="left", fill="x", expand=True)

        def set_all(value):
            for var in vars_by_key.values():
                var.set(value)

        select_all = ctk.CTkCheckBox(
            bottom, text=t("cleanup.select_all", "全选"),
            onvalue=True, offvalue=False,
            command=lambda: set_all(select_all.get()))
        select_all.pack(side="right", padx=(8, 4))

        clean_button = ctk.CTkButton(
            bottom, text=t("cleanup.clean_selected", "清理所选"), width=110,
            command=lambda: self._run_cleanup(
                dialog, targets, vars_by_key, size_labels,
                result_label, clean_button))
        clean_button.pack(side="right", padx=(0, 4))

        ctk.CTkButton(
            bottom, text=t("cleanup.close", "关闭"), width=80,
            command=dialog.destroy).pack(side="right", padx=(0, 6))

        ctk.CTkLabel(
            dialog,
            text=t("cleanup.note",
                   "缓存用于加速浏览与加载体验，建议仅在需要释放空间时清理，无需频繁清理。"),
            text_color="gray", font=self._font(10),
        ).pack(fill="x", padx=18, pady=(0, 12))

        def measure_job():
            sizes = measure_all(targets)

            def apply_sizes():
                try:
                    if not dialog.winfo_exists():
                        return
                except Exception:
                    return
                dialog._cleanup_sizes = sizes
                for key, size in sizes.items():
                    label = size_labels.get(key)
                    if label is not None:
                        label.configure(text=format_size(size))

            try:
                self.root.after(0, apply_sizes)
            except Exception:
                pass

        threading.Thread(
            target=measure_job, name="cleanup-measure", daemon=True).start()

    def _run_cleanup(self, dialog, targets, vars_by_key, size_labels,
                     result_label, clean_button):
        import threading

        selected = [t for t in targets if vars_by_key[t["key"]].get()]
        if not selected:
            showinfo(
                t("cleanup.title", "清理缓存"),
                t("cleanup.none_selected", "请先勾选要清理的项目"),
                parent=dialog)
            return
        if self.is_operating and any(
                t["key"] == "downloads_temp" for t in selected):
            # 下载进行中：跳过临时残留清理，避免破坏进行中的 .part 文件
            showwarning(
                t("cleanup.title", "清理缓存"),
                t("cleanup.download_in_progress",
                  "下载进行中，已跳过「下载临时残留」。"),
                parent=dialog)
            selected = [t for t in selected if t["key"] != "downloads_temp"]
            if not selected:
                return
        sizes = getattr(dialog, "_cleanup_sizes", {})
        total = sum(sizes.get(t["key"], 0) for t in selected)
        if not askyesno(
                t("cleanup.confirm_title", "确认清理"),
                t("cleanup.confirm",
                  "确定清理所选 {count} 项（共 {size}）？").format(
                    count=len(selected), size=format_size(total)),
                parent=dialog):
            return

        clean_button.configure(state="disabled")

        def job():
            results = clean_all(selected)
            freed = sum(freed for freed, _failed in results.values())
            failed = sum(failed for _freed, failed in results.values())
            new_sizes = measure_all(targets)

            def apply_result():
                try:
                    if not dialog.winfo_exists():
                        return
                except Exception:
                    return
                clean_button.configure(state="normal")
                dialog._cleanup_sizes = new_sizes
                for key, size in new_sizes.items():
                    label = size_labels.get(key)
                    if label is not None:
                        label.configure(text=format_size(size))
                if failed:
                    result_label.configure(text=t(
                        "cleanup.partial",
                        "已清理 {size}（{failed} 个文件被占用跳过）").format(
                        size=format_size(freed), failed=failed))
                else:
                    result_label.configure(text=t(
                        "cleanup.done", "已清理 {size}").format(
                        size=format_size(freed)))

            try:
                self.root.after(0, apply_result)
            except Exception:
                pass

        threading.Thread(
            target=job, name="cleanup-job", daemon=True).start()

    # ============================================================
    # AI 翻译设置（设置菜单 → 🌐 AI 翻译设置）
    # ============================================================
    def _show_ai_settings_dialog(self):
        import threading

        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("ai.settings_title", "AI 翻译设置"))
        dialog.geometry("560x420")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text=t("ai.settings_hint",
                   "使用 OpenAI 兼容接口翻译 GameBanana 详情页描述。\n"
                   "API key 存入系统凭据管理器，不写入配置文件。"),
            wraplength=520, justify="left", text_color="gray",
        ).pack(fill="x", padx=18, pady=(14, 8))

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="x", padx=18, pady=4)

        ctk.CTkLabel(
            form, text=t("ai.base_url", "Base URL"), anchor="w",
        ).pack(fill="x", pady=(4, 2))
        base_var = ctk.StringVar(value=ConfigManager.get_ai_base_url())
        ctk.CTkEntry(
            form, textvariable=base_var,
            placeholder_text="https://api.openai.com/v1",
        ).pack(fill="x")

        ctk.CTkLabel(
            form, text=t("ai.api_key", "API Key"), anchor="w",
        ).pack(fill="x", pady=(10, 2))
        key_var = ctk.StringVar(value=get_ai_api_key())
        ctk.CTkEntry(
            form, textvariable=key_var, show="*",
            placeholder_text="sk-...",
        ).pack(fill="x")

        model_row = ctk.CTkFrame(form, fg_color="transparent")
        model_row.pack(fill="x", pady=(10, 2))
        ctk.CTkLabel(
            model_row, text=t("ai.model", "模型"), anchor="w",
        ).pack(side="left")
        ctk.CTkButton(
            model_row, text=t("ai.fetch_models", "获取可用模型"),
            width=120, height=26, font=self._font(11),
            command=lambda: self._fetch_ai_models(
                dialog, base_var, key_var, model_var, status_label),
        ).pack(side="right")

        model_var = ctk.StringVar(value=ConfigManager.get_ai_model())
        self._ai_model_combo = ctk.CTkComboBox(
            form, variable=model_var, values=[], height=30)
        self._ai_model_combo.pack(fill="x")

        status_label = ctk.CTkLabel(
            dialog, text="", wraplength=520, justify="left",
            text_color="#e06c75", anchor="w")
        status_label.pack(fill="x", padx=18, pady=(8, 0))

        bottom = ctk.CTkFrame(dialog, fg_color="transparent")
        bottom.pack(fill="x", padx=18, pady=(10, 14))

        def save():
            ConfigManager.set_ai_base_url(base_var.get())
            ConfigManager.set_ai_model(model_var.get())
            set_ai_api_key(key_var.get())
            dialog.destroy()

        ctk.CTkButton(
            bottom, text=t("ai.save", "保存"), width=100,
            command=save).pack(side="right")
        ctk.CTkButton(
            bottom, text=t("ai.cancel", "取消"), width=100,
            fg_color="transparent", border_width=1,
            command=dialog.destroy).pack(side="right", padx=(0, 8))

    def _fetch_ai_models(self, dialog, base_var, key_var, model_var,
                         status_label):
        import threading

        base = base_var.get().strip()
        key = key_var.get().strip()
        if not base or not key:
            status_label.configure(text=t(
                "ai.fetch_models_need_config",
                "请先填写 Base URL 和 API Key"))
            return
        status_label.configure(text=t(
            "ai.fetching_models", "正在获取可用模型..."))

        def job():
            try:
                models = list_models(base, key)
            except Exception as exc:
                models = None
                message = str(exc)
            else:
                message = ""

            def apply():
                try:
                    if not dialog.winfo_exists():
                        return
                except Exception:
                    return
                if models is None:
                    status_label.configure(text=message)
                    return
                current = model_var.get()
                self._ai_model_combo.configure(values=models)
                if current in models:
                    model_var.set(current)
                elif models:
                    model_var.set(models[0])
                status_label.configure(
                    text=t("ai.fetch_models_ok",
                           "获取到 {count} 个可用模型").format(count=len(models)),
                    text_color=("gray40", "gray60"))

            try:
                self.root.after(0, apply)
            except Exception:
                pass

        threading.Thread(
            target=job, name="ai-fetch-models", daemon=True).start()

    # ============================================================
    # 网络代理设置（设置菜单 → 🛰️ 网络代理设置）
    # ============================================================
    def _show_proxy_settings_dialog(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("proxy.settings_title", "网络代理设置"))
        dialog.geometry("560x380")
        dialog.transient(self.root)

        ctk.CTkLabel(
            dialog,
            text=t("proxy.hint",
                   "为所有网络请求（GameBanana/Patreon/AI 翻译等）设置代理。\n"
                   "留空 = 跟随系统代理；仅支持 http/https。\n"
                   "代理含账号密码时，Patreon 浏览器仍走系统代理。"),
            wraplength=520, justify="left", text_color="gray",
        ).pack(fill="x", padx=18, pady=(14, 8))

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="x", padx=18, pady=4)

        ctk.CTkLabel(
            form, text=t("proxy.url_label", "代理地址"), anchor="w",
        ).pack(fill="x", pady=(4, 2))
        proxy_var = ctk.StringVar(value=ConfigManager.get_proxy())
        ctk.CTkEntry(
            form, textvariable=proxy_var,
            placeholder_text="http://127.0.0.1:7897",
        ).pack(fill="x")

        status_label = ctk.CTkLabel(
            dialog, text="", wraplength=520, justify="left",
            text_color="#e06c75", anchor="w")
        status_label.pack(fill="x", padx=18, pady=(8, 0))

        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(fill="x", pady=(10, 2))
        ctk.CTkLabel(
            row, text=t("proxy.scope_hint", "生效范围：全部网络请求 + Patreon 浏览器"),
            anchor="w", text_color=("gray40", "gray60"),
        ).pack(side="left")
        test_btn = ctk.CTkButton(
            row, text=t("proxy.test_connection", "测试连接"),
            width=110, height=26, font=self._font(11),
            command=lambda: self._test_proxy_connection(
                dialog, proxy_var, status_label, test_btn))
        test_btn.pack(side="right")

        bottom = ctk.CTkFrame(dialog, fg_color="transparent")
        bottom.pack(fill="x", padx=18, pady=(10, 14))

        def save():
            proxy = proxy_var.get().strip()
            if proxy:
                if "://" not in proxy:
                    proxy = "http://" + proxy
                parsed = urlparse(proxy)
                if parsed.scheme not in ("http", "https"):
                    status_label.configure(
                        text=t("proxy.socks_not_supported",
                               "仅支持 http/https 代理"),
                        text_color="#e06c75")
                    return
                try:
                    valid = bool(parsed.hostname and parsed.port)
                except ValueError:
                    valid = False
                if not valid:
                    status_label.configure(
                        text=t("proxy.invalid_url", "代理地址格式不正确"),
                        text_color="#e06c75")
                    return
            ConfigManager.set_proxy(proxy)
            dialog.destroy()
            # 延迟到旧对话框销毁、grab 释放处理完成后再弹确认框，避免
            # 新窗口在未映射时 grab_set 造成事件循环卡死
            self.root.after(150, self._confirm_proxy_restart)

        ctk.CTkButton(
            bottom, text=t("proxy.save", "保存"), width=100,
            command=save).pack(side="right")
        ctk.CTkButton(
            bottom, text=t("proxy.cancel", "取消"), width=100,
            fg_color="transparent", border_width=1,
            command=dialog.destroy).pack(side="right", padx=(0, 8))

        dialog.grab_set()

    def _test_proxy_connection(self, dialog, proxy_var, status_label, test_btn):
        proxy = proxy_var.get().strip()
        if proxy and "://" not in proxy:
            proxy = "http://" + proxy
        proxy = proxy or None
        test_btn.configure(state="disabled")
        status_label.configure(
            text=t("proxy.testing", "正在测试连接..."), text_color="gray")

        def job():
            try:
                response = httpx.get(
                    "https://www.google.com/generate_204",
                    proxy=proxy, timeout=10, follow_redirects=True)
                ok = response.status_code < 400
                message = (t("proxy.test_ok", "连接成功") if ok
                           else t("proxy.test_fail", "连接失败：HTTP {code}").format(
                               code=response.status_code))
            except Exception as exc:
                ok = False
                message = t("proxy.test_fail", "连接失败：{error}").format(
                    error=exc)

            def apply():
                try:
                    if not dialog.winfo_exists():
                        return
                except Exception:
                    return
                test_btn.configure(state="normal")
                status_label.configure(
                    text=message,
                    text_color=("green", "light green") if ok else "#e06c75")

            try:
                self.root.after(0, apply)
            except Exception:
                pass

        threading.Thread(
            target=job, name="proxy-test", daemon=True).start()

    def _confirm_proxy_restart(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("proxy.restart_title", "代理设置已保存"))
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.lift()
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(
            dialog,
            text=t("proxy.restart_msg", "代理设置已保存，重启后生效。\n是否立即重启？"),
        ).pack(padx=24, pady=(24, 16))

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=(0, 20))

        ctk.CTkButton(
            btn_frame, text=t("proxy.restart_now", "立即重启"),
            command=self._restart_app,
        ).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(
            btn_frame, text=t("proxy.later", "稍后"),
            fg_color="transparent", border_width=1,
            command=dialog.destroy,
        ).pack(side="right", expand=True, fill="x", padx=(5, 0))

        dialog.bind("<Escape>", lambda e: dialog.destroy())

        dialog.update_idletasks()
        dw = dialog.winfo_width()
        dh = dialog.winfo_height()
        px = self.root.winfo_rootx()
        py = self.root.winfo_rooty()
        pw = self.root.winfo_width()
        ph = self.root.winfo_height()
        x = max(0, px + (pw - dw) // 2)
        y = max(0, py + (ph - dh) // 2)
        dialog.geometry("+{}+{}".format(x, y))

        dialog.grab_set()

    def _restart_app(self):
        if getattr(sys, "frozen", False):
            cmd = [sys.executable] + sys.argv[1:]
        else:
            cmd = [sys.executable] + sys.argv
        try:
            subprocess.Popen(cmd)
        except Exception:
            return
        try:
            self._patreon_frame.destroy()
        except Exception:
            pass
        os._exit(0)

    def _load_config_and_refresh(self, defer=False):
        game_path = ConfigManager.get_game_path()
        if game_path:
            self.path_label.configure(text=os.path.basename(game_path) or game_path)
        else:
            self.path_label.configure(text=t("top.no_folder", "未选择文件夹"))
        self._update_browse_btn_visibility()
        if defer:
            # Windows 完成顶层窗口映射后，滚动区才具有可用于计算卡片列数的实际宽度。
            self.root.after(10, self._refresh_when_layout_ready)
        else:
            self._refresh()

    def _refresh_when_layout_ready(self, attempt=0):
        self.root.update_idletasks()
        if self.scroll_frame.winfo_width() < 500 and attempt < 50:
            self.root.after(
                10, lambda: self._refresh_when_layout_ready(attempt + 1),
            )
            return
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
        cleanup_target_temporaries(
            [self.mod_manager.mods_dir, self.mod_manager.disabled_dir])

        self.mods_data = self.mod_manager.scan_mods()
        valid_names = {m["name"] for m in self.mods_data}
        ConfigManager.cleanup_mod_data(valid_names)
        self._local_state.prune_selection(valid_names)

        self._render_mod_list()
        self._update_stats()
        self._rebuild_alphabet_bar()

        if created_disabled:
            self.root.after(100, lambda: showinfo(
                t("dialog.title_hint", "提示"),
                t("dialog.disabled_dir_created", "检测到游戏目录中没有 Disabled_Mods 文件夹，已自动创建。\n\n"
                  "路径: {path}").format(path=self.mod_manager.disabled_dir)
            ))

    def _show_empty_state(self, message):
        self._render_generation += 1
        self._preview_targets.clear()
        self._readme_targets.clear()
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._checkbox_vars.clear()
        self._group_checkbox_vars.clear()
        self._group_headers.clear()
        self._group_contents.clear()
        self._group_first_mod.clear()
        self._mod_to_group.clear()
        self._group_mods.clear()
        self._mod_rows.clear()
        self._primary_alpha_index.clear()
        self._sorted_group_names.clear()
        self._preview_ctk_images.clear()
        self._group_mini_alpha_bars.clear()
        self.mods_data = []
        self._local_state.selected_names.clear()

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
        anchor = self._capture_scroll_anchor()
        self._render_generation += 1
        self._preview_targets.clear()
        self._readme_targets.clear()
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._checkbox_vars.clear()
        self._group_checkbox_vars.clear()
        self._group_headers.clear()
        self._group_contents.clear()
        self._group_first_mod.clear()
        self._mod_to_group.clear()
        self._group_mods.clear()
        self._mod_rows.clear()
        self._preview_ctk_images.clear()
        self._group_mini_alpha_bars.clear()
        if self._view_mode != CARD:
            self._card_columns = None
        self._local_state.prune_selection(m["name"] for m in self.mods_data)

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

        if self.mods_data:
            self._restore_scroll_anchor(anchor)
            self._sync_all_group_checkboxes()

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
        self._group_mods[gname] = [m["name"] for m in mods]

        if mods:
            self._group_first_mod[gname] = mods[0]["name"]

        # 左栏：Mod 行或卡片网格
        left_frame = ctk.CTkFrame(content, fg_color=("gray95", "gray14"))
        left_frame.pack(side="left", fill="both", expand=True)

        if self._view_mode == CARD:
            self.root.update_idletasks()
            columns = self._get_card_column_count()
            self._card_columns = columns
            card_width = round(self.CARD_WIDTH * self._dpi_scale)
            card_grid = ctk.CTkFrame(
                left_frame,
                width=columns * (self.CARD_WIDTH + self.CARD_GAP),
                fg_color="transparent",
            )
            card_grid.pack(anchor="n")
            card_pixel_width = round(self.CARD_WIDTH * self._dpi_scale)
            card_pixel_padding = math.ceil(
                (self.CARD_GAP // 2) * self._dpi_scale,
            )
            slot_width = card_pixel_width + card_pixel_padding * 2
            for column in range(columns):
                card_grid.grid_columnconfigure(column, minsize=slot_width)
        else:
            card_grid = left_frame

        cards = []
        for index, mod in enumerate(mods):
            self._mod_to_group[mod["name"]] = gname
            if self._view_mode == CARD:
                cards.append(self._create_mod_card(
                    card_grid, mod, notes.get(mod["name"], ""),
                    images.get(mod["name"], ""), index, columns, card_width,
                ))
            elif self._view_mode == DETAILED:
                self._create_mod_detailed_row(
                    left_frame, mod, notes.get(mod["name"], ""),
                    images.get(mod["name"], ""))
            else:
                self._create_mod_row(left_frame, mod, notes.get(mod["name"], ""),
                                     images.get(mod["name"], ""))

        if cards:
            self.root.update_idletasks()
            uniform_height = max(
                1, round(max(
                    card.winfo_reqheight() for card in cards) / self._dpi_scale),
            )
            for card in cards:
                card.configure(width=self.CARD_WIDTH, height=uniform_height)
                card.pack_propagate(False)

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

    def _schedule_card_preview(self, label, source_path, image_size,
                               display_size, preview_height):
        generation = self._render_generation
        target_id = id(label)
        self._preview_targets[target_id] = (
            generation, label, source_path, display_size, preview_height)
        try:
            future = self._track_background_future(
                self._preview_executor.submit(
                    self._local_preview_cache.load, source_path, image_size))
        except RuntimeError:
            return

        def completed(done):
            try:
                image = done.result()
            except Exception:
                image = None
            try:
                self.root.after(
                    0, self._apply_card_preview, target_id, generation, image)
            except Exception:
                pass

        future.add_done_callback(completed)

    def _apply_card_preview(self, target_id, generation, image):
        target = self._preview_targets.get(target_id)
        if (self._closing or target is None or target[0] != generation or
                generation != self._render_generation):
            return
        _generation, label, source_path, display_size, preview_height = target
        try:
            if not label.winfo_exists():
                return
        except Exception:
            return
        if image is None:
            label.configure(
                image=None,
                text=f"▧\n{t('mod_list.no_preview', '暂无预览图')}",
                font=self._font(11), text_color=("gray48", "gray55"),
                fg_color=("gray84", "gray19"),
            )
            return
        ctk_img = CTkImage(
            light_image=image, dark_image=image, size=display_size)
        self._preview_ctk_images[target_id] = ctk_img
        label.configure(image=ctk_img, text="", fg_color="transparent")
        label.bind(
            "<Button-1>", lambda _event, path=source_path:
            self._show_full_image(path))
        label.configure(height=preview_height, cursor="hand2")

    def _schedule_card_readmes(self, controls, mod):
        generation = self._render_generation
        mod_path = mod["path"]
        key = (generation, os.path.normcase(os.path.abspath(mod_path)))
        target = (controls, mod_path)
        targets = self._readme_targets.setdefault(key, [])
        targets.append(target)
        if len(targets) > 1:
            return
        try:
            future = self._track_background_future(
                self._readme_executor.submit(find_readme_files, mod_path))
        except RuntimeError:
            return

        def completed(done):
            try:
                readme_files = done.result()
            except Exception:
                readme_files = []
            try:
                self.root.after(
                    0, self._apply_card_readmes,
                    key, generation, tuple(readme_files))
            except Exception:
                pass

        future.add_done_callback(completed)

    def _apply_card_readmes(self, key, generation, readme_files):
        targets = self._readme_targets.pop(key, [])
        if self._closing or generation != self._render_generation:
            return
        for controls, _mod_path in targets:
            try:
                if not controls.winfo_exists():
                    continue
            except Exception:
                continue
            self._create_card_readme_button(controls, readme_files)

    def _create_card_readme_button(self, controls, readme_files, side="right"):
        if not readme_files:
            return
        readme_count = len(readme_files)
        rf_name, rf_path = readme_files[0]
        button_text = (
            README_LABELS.get(rf_name, f"📄 {rf_name}")
            if readme_count == 1
            else f"📄 README x{readme_count}"
        )
        readme_btn = ctk.CTkButton(
            controls, text=button_text,
            width=72, height=24, font=self._font(8),
            fg_color=("gray80", "gray25"),
            hover_color=("gray70", "gray35"),
            text_color=("gray25", "gray85"),
        )
        if readme_count == 1:
            readme_btn.configure(
                command=lambda path=rf_path: self.mod_manager.open_file(path))
        else:
            readme_btn.configure(
                command=lambda button=readme_btn, files=readme_files:
                self._show_readme_menu(button, files))
        readme_btn.pack(side=side, padx=2)

    def _create_mod_row(self, parent, mod, note, image_path):
        name = mod["name"]
        enabled = mod["enabled"]

        row = ctk.CTkFrame(parent, height=44, corner_radius=4,
                           fg_color=("gray95", "gray13"))
        row.pack(fill="x", padx=2, pady=2)
        row.pack_propagate(False)

        # ---- 复选框 ----
        var = ctk.BooleanVar(value=name in self._local_state.selected_names)
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

        # ---- 预览图（异步，走本地二级缓存）----
        resolved_img = self._resolve_preview_path(mod["path"], image_path)
        if resolved_img and HAS_PIL:
            preview = ctk.CTkLabel(
                row, text="",
                width=self.PREVIEW_SIZE[0], height=self.PREVIEW_SIZE[1],
                fg_color=("gray84", "gray19"), corner_radius=4,
            )
            self._schedule_card_preview(
                preview, resolved_img, self.PREVIEW_SIZE,
                self.PREVIEW_SIZE, self.PREVIEW_SIZE[1])
        else:
            preview = ctk.CTkLabel(
                row,
                text=f"▧\n{t('mod_list.no_preview', '暂无预览图')}",
                width=self.PREVIEW_SIZE[0], height=self.PREVIEW_SIZE[1],
                font=self._font(7),
                text_color=("gray48", "gray55"),
                fg_color=("gray84", "gray19"),
                corner_radius=4,
            )
        preview.pack(side="left", padx=(0, 6))

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

        readme_slot = ctk.CTkFrame(right_frame, fg_color=("gray95", "gray13"))
        readme_slot.pack(side="left", padx=2)
        if self.mod_manager:
            self._schedule_card_readmes(readme_slot, mod)

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
        )
        more_btn.configure(
            command=lambda m=mod, b=more_btn: self._show_more_menu(m, b))
        more_btn.pack(side="left", padx=2)

        self._mod_rows.setdefault(name, []).append({
            "row_frame": row,
            "switch": switch,
            "switch_var": switch_var,
            "status_label": status_label,
            "checkbox_var": var,
            "name_label": name_label,
            "original_name_label": original_name_label,
            "mod": mod,
        })

    def _create_mod_detailed_row(self, parent, mod, note, image_path):
        """详情列表行：大预览 + 名称/原名 + README 摘要 + 状态/开关 + 文件夹/更多。"""
        name = mod["name"]
        enabled = mod["enabled"]
        scale = self._dpi_scale
        display_size = (150, 84)
        image_size = (max(60, round(150 * scale)), max(34, round(84 * scale)))

        row = ctk.CTkFrame(parent, height=96, corner_radius=6,
                           fg_color=("gray95", "gray13"))
        row.pack(fill="x", padx=2, pady=2)
        row.pack_propagate(False)

        var = ctk.BooleanVar(value=name in self._local_state.selected_names)
        self._checkbox_vars[name] = var
        cb = ctk.CTkCheckBox(
            row, text="",
            checkbox_width=18, checkbox_height=18,
            width=18,
            variable=var,
            onvalue=True, offvalue=False,
            command=lambda n=name: self._on_mod_checkbox_toggle(n),
        )
        cb.pack(side="left", padx=(10, 8), pady=36)

        resolved_img = self._resolve_preview_path(mod["path"], image_path)
        if resolved_img and HAS_PIL:
            preview = ctk.CTkLabel(
                row, text="",
                width=display_size[0], height=display_size[1],
                fg_color=("gray84", "gray19"), corner_radius=6,
            )
            self._schedule_card_preview(
                preview, resolved_img, image_size,
                display_size, display_size[1])
        else:
            preview = ctk.CTkLabel(
                row,
                text=f"▧\n{t('mod_list.no_preview', '暂无预览图')}",
                width=display_size[0], height=display_size[1],
                font=self._font(9),
                text_color=("gray48", "gray55"),
                fg_color=("gray84", "gray19"),
                corner_radius=6,
            )
        preview.pack(side="left", padx=(0, 8), pady=6)

        info = ctk.CTkFrame(row, fg_color=("gray95", "gray13"))
        info.pack(side="left", fill="x", expand=True, padx=(0, 8))

        display_name = note if note else name
        name_label = ctk.CTkLabel(
            info, text=display_name,
            font=self._font(13, weight="bold"), anchor="w",
        )
        name_label.pack(fill="x", pady=(14, 0))

        original_name_label = None
        if note:
            original_name_label = ctk.CTkLabel(
                info, text=name,
                font=self._font(9), text_color="gray", anchor="w",
            )
            original_name_label.pack(fill="x")

        right_frame = ctk.CTkFrame(row, fg_color=("gray95", "gray13"))
        right_frame.pack(side="right", padx=(0, 8), pady=24)

        readme_slot = ctk.CTkFrame(right_frame, fg_color=("gray95", "gray13"))
        readme_slot.pack(side="left", padx=2)
        if self.mod_manager:
            self._schedule_card_readmes(readme_slot, mod)

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
            text_color="#3fb950" if enabled else "gray",
        )
        status_label.pack(side="left", padx=(0, 4))

        open_btn = ctk.CTkButton(
            right_frame, text="📂",
            width=30, height=30,
            font=self._font(12),
            fg_color=("gray95", "gray13"),
            hover_color=("gray85", "gray25"),
            text_color=("gray40", "gray70"),
            command=lambda m=mod: self._open_mod_folder(m),
        )
        open_btn.pack(side="left", padx=2)

        more_btn = ctk.CTkButton(
            right_frame, text="⋯",
            width=30, height=30,
            font=self._font(14, weight="bold"),
            fg_color=("gray95", "gray13"),
            hover_color=("gray85", "gray25"),
            text_color=("gray40", "gray70"),
        )
        more_btn.configure(
            command=lambda m=mod, b=more_btn: self._show_more_menu(m, b))
        more_btn.pack(side="left", padx=2)

        self._mod_rows.setdefault(name, []).append({
            "row_frame": row,
            "switch": switch,
            "switch_var": switch_var,
            "status_label": status_label,
            "checkbox_var": var,
            "name_label": name_label,
            "original_name_label": original_name_label,
            "mod": mod,
        })
        return row

    def _create_mod_card(self, parent, mod, note, image_path, index, columns, card_width):
        name = mod["name"]
        enabled = mod["enabled"]
        image_width = max(210, card_width - 16)
        image_size = (image_width, max(118, round(image_width * 9 / 16)))
        preview_height = max(94, round(image_size[1] / self._dpi_scale))
        display_image_size = (
            max(168, round(image_size[0] / self._dpi_scale)),
            preview_height,
        )

        display_name = note if note else name
        title_font = self._font(12, weight="bold")
        title_text_width = max(
            80, round((image_width - 50) / self._dpi_scale) - 4,
        )
        fitted_title = fit_card_text(
            display_name, title_font, title_text_width,
        )
        # 统一高度：标题恒为两行、原名区恒为两行，保证组内卡片等高。
        title_height = 40

        original_name_font = self._font(9)
        fitted_original_name = ""
        if note:
            original_text_width = max(
                80, round((image_width - 44) / self._dpi_scale) - 4,
            )
            fitted_original_name = fit_card_text(
                name, original_name_font, original_text_width,
            )
        original_height = 32

        card = ctk.CTkFrame(
            parent, width=self.CARD_WIDTH, corner_radius=8,
            fg_color=("gray92", "gray13"),
            border_width=1, border_color=("gray78", "gray23"),
        )
        card.grid(
            row=index // columns, column=index % columns,
            padx=self.CARD_GAP // 2, pady=4,
        )
        card.grid_propagate(False)

        resolved_img = self._resolve_preview_path(mod["path"], image_path)
        if resolved_img and HAS_PIL:
            preview = ctk.CTkLabel(
                card, text="", width=display_image_size[0],
                height=preview_height, fg_color=("gray84", "gray19"),
                corner_radius=7,
            )
            self._schedule_card_preview(
                preview, resolved_img, image_size,
                display_image_size, preview_height)
        else:
            preview = ctk.CTkLabel(
                card,
                text=f"▧\n{t('mod_list.no_preview', '暂无预览图')}",
                width=display_image_size[0], height=preview_height,
                font=self._font(11), text_color=("gray48", "gray55"),
                fg_color=("gray84", "gray19"), corner_radius=7,
            )
        preview.pack(fill="x", padx=6, pady=(6, 0))

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(fill="both", expand=True, padx=10, pady=(8, 8))

        title_row = ctk.CTkFrame(info, fg_color="transparent")
        title_row.pack(fill="x")
        var = ctk.BooleanVar(value=name in self._local_state.selected_names)
        self._checkbox_vars[name] = var
        cb = ctk.CTkCheckBox(
            title_row, text="", width=18,
            checkbox_width=18, checkbox_height=18,
            variable=var, onvalue=True, offvalue=False,
            command=lambda n=name: self._on_mod_checkbox_toggle(n),
        )
        cb.pack(side="left", padx=(0, 6))

        title_container = ctk.CTkFrame(
            title_row, width=1,
            height=title_height,
            fg_color="transparent",
        )
        title_container.pack(side="left", fill="x", expand=True)
        title_container.pack_propagate(False)
        name_label = ctk.CTkLabel(
            title_container, text=fitted_title,
            font=title_font, anchor="w", justify="left",
        )
        name_label.place(x=0, y=0, relwidth=1, relheight=1)

        original_name_label = None
        original_container = ctk.CTkFrame(
            info, width=1,
            height=original_height,
            fg_color="transparent",
        )
        original_container.pack(fill="x", padx=(24, 0), pady=(0, 2))
        original_container.pack_propagate(False)
        if note:
            original_name_label = ctk.CTkLabel(
                original_container, text=fitted_original_name,
                font=original_name_font,
                text_color="gray", anchor="w", justify="left",
            )
            original_name_label.place(x=0, y=0, relwidth=1, relheight=1)

        controls = ctk.CTkFrame(info, fg_color="transparent")
        controls.pack(fill="x", pady=(6, 0))

        switch_var = ctk.BooleanVar(value=enabled)
        switch = ctk.CTkSwitch(
            controls, text="", variable=switch_var,
            onvalue=True, offvalue=False, width=42,
            switch_width=38, switch_height=20,
            command=lambda n=name, sv=switch_var: self._on_switch_toggled(n, sv.get()),
        )
        switch.pack(side="left")
        status_label = ctk.CTkLabel(
            controls,
            text=t("mod_list.status_enabled", "启用") if enabled else t("mod_list.status_disabled", "禁用"),
            font=self._font(9), text_color="#3fb950" if enabled else "gray",
        )
        status_label.pack(side="left", padx=(0, 4))

        more_btn = ctk.CTkButton(
            controls, text="⋯", width=28, height=28,
            font=self._font(14, weight="bold"),
            fg_color="transparent", hover_color=("gray82", "gray25"),
            text_color=("gray40", "gray70"),
        )
        more_btn.configure(
            command=lambda m=mod, b=more_btn: self._show_more_menu(m, b))
        more_btn.pack(side="right", padx=(2, 0))
        open_btn = ctk.CTkButton(
            controls, text="📂", width=28, height=28,
            font=self._font(12), fg_color="transparent",
            hover_color=("gray82", "gray25"),
            text_color=("gray40", "gray70"),
            command=lambda m=mod: self._open_mod_folder(m),
        )
        open_btn.pack(side="right", padx=2)

        if self.mod_manager:
            self._schedule_card_readmes(controls, mod)

        self._mod_rows.setdefault(name, []).append({
            "row_frame": card,
            "switch": switch,
            "switch_var": switch_var,
            "status_label": status_label,
            "checkbox_var": var,
            "name_label": name_label,
            "original_name_label": original_name_label,
            "mod": mod,
        })
        return card

    # ============================================================
    # 复选框逻辑（选择状态以 _local_state.selected_names 为准）
    # ============================================================
    def _all_names_in_group(self, gname):
        return list(self._group_mods.get(gname, []))

    def _set_selected(self, name, selected):
        if selected:
            self._local_state.selected_names.add(name)
        else:
            self._local_state.selected_names.discard(name)

    def _sync_checkbox_vars(self, name):
        for handle in self._mod_rows.get(name, []):
            var = handle.get("checkbox_var")
            if var is not None:
                var.set(name in self._local_state.selected_names)

    def _reset_switch_visual(self, name, value):
        for handle in self._mod_rows.get(name, []):
            var = handle.get("switch_var")
            if var is not None:
                var.set(value)

    def _on_group_checkbox_toggle(self, gname):
        is_checked = self._group_checkbox_vars[gname].get()
        for name in self._all_names_in_group(gname):
            self._set_selected(name, is_checked)
            self._sync_checkbox_vars(name)
        self._sync_all_group_checkboxes()

    def _on_mod_checkbox_toggle(self, mod_name):
        var = self._checkbox_vars.get(mod_name)
        if var is None:
            return
        self._set_selected(mod_name, var.get())
        for handle in self._mod_rows.get(mod_name, []):
            other = handle.get("checkbox_var")
            if other is not None and other is not var:
                other.set(var.get())
        self._sync_all_group_checkboxes()

    def _select_all(self):
        self._local_state.selected_names = {
            m["name"] for m in self.mods_data}
        for name in self._local_state.selected_names:
            self._sync_checkbox_vars(name)
        self._sync_all_group_checkboxes()

    def _deselect_all(self):
        self._local_state.selected_names.clear()
        for handles in self._mod_rows.values():
            for handle in handles:
                var = handle.get("checkbox_var")
                if var is not None:
                    var.set(False)
        self._sync_all_group_checkboxes()

    def _invert_selection(self):
        names = {m["name"] for m in self.mods_data}
        self._local_state.selected_names = names - self._local_state.selected_names
        for name in names:
            self._sync_checkbox_vars(name)
        self._sync_all_group_checkboxes()

    def _sync_all_group_checkboxes(self):
        for gname, group_var in self._group_checkbox_vars.items():
            names = self._all_names_in_group(gname)
            if not names:
                group_var.set(False)
                continue
            group_var.set(
                all(n in self._local_state.selected_names for n in names))

    def _get_selected_mods(self):
        names = self._local_state.selected_names
        return [m for m in self.mods_data if m["name"] in names]

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
                showwarning(
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
            showinfo(
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
                showwarning(
                    t("dialog.title_warning", "提示"),
                    t("group_dialog.select_first", "请先选择一个分组"))
                return
            new_name = self._show_input_dialog(
                t("group_dialog.title_rename", "重命名分组"),
                t("group_dialog.prompt_rename", "将 \"{name}\" 重命名为：").format(name=gname))
            if new_name and new_name.strip() and new_name.strip() != gname:
                nn = new_name.strip()
                if nn in groups:
                    showwarning(
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
            if askyesno(
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
                    showwarning(
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
    def _show_readme_menu(self, button, readme_files):
        import tkinter as tk

        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#2b2b2b", fg="#e0e0e0",
            activebackground="#3B8ED0", activeforeground="white",
            font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))),
            bd=1, relief="flat",
        )
        for file_name, file_path in readme_files:
            menu.add_command(
                label=file_name,
                command=lambda p=file_path: self.mod_manager.open_file(p),
            )

        try:
            menu.tk_popup(
                button.winfo_rootx(),
                button.winfo_rooty() + button.winfo_height(),
            )
        finally:
            menu.grab_release()

    def _show_more_menu(self, mod, anchor=None):
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

        if anchor is not None:
            try:
                menu.tk_popup(
                    anchor.winfo_rootx(),
                    anchor.winfo_rooty() + anchor.winfo_height(),
                )
                menu.grab_release()
                return
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
            showwarning(
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

            win = ctk.CTkToplevel(self.root, fg_color="black")
            win.title(t("preview.title", "图片预览 - {name}").format(name=os.path.basename(image_path)))
            win.geometry(f"{new_w}x{new_h}")
            win.resizable(False, False)
            win.attributes("-topmost", True)
            win.lift()

            x = (screen_w - new_w) // 2
            y = (screen_h - new_h) // 2
            win.geometry(f"+{x}+{y}")

            ctk_img = CTkImage(light_image=display_img, dark_image=display_img, size=(new_w, new_h))
            img_label = ctk.CTkLabel(win, image=ctk_img, text="", fg_color="black")
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
            showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            self._reset_switch_visual(mod["name"], mod["enabled"])
            return

        name = mod["name"]
        currently_enabled = mod["enabled"]
        action_key = "disable" if currently_enabled else "enable"
        action_display = t("dialog.action_disable", "禁用") if currently_enabled else t("dialog.action_enable", "启用")

        if not askyesno(
            t("dialog.title_confirm", "确认操作"),
            t("dialog.toggle_confirm", "确定要{action} Mod \"{name}\" 吗？\n\n这将会移动整个 Mod 文件夹。").format(
                action=action_display, name=name)):
            self._reset_switch_visual(name, currently_enabled)
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
            showwarning(
                t("dialog.operation_in_progress", "操作中"),
                t("dialog.wait_for_current", "请等待当前操作完成"))
            return

        selected = self._get_selected_mods()
        if not selected:
            showinfo(
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

        if not askyesno(
            t("dialog.title_confirm", "确认批量操作"),
            t("dialog.batch_confirm", "确定要批量{action} {count} 个 Mod 吗？{skip}\n\n这将会移动 Mod 文件夹。").format(
                action=action_display, count=len(to_toggle), skip=skip_msg)):
            return

        if not to_toggle:
            showinfo(
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
            showwarning(
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
            showerror(
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
        self._settings_btn.configure(state=state)
        self._more_btn.configure(state=state)
        self._toolbar_widgets["install_zip"].configure(state=state)
        for handles in self._mod_rows.values():
            for row_info in handles:
                switch = row_info.get("switch")
                if switch is not None:
                    switch.configure(state=state)

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
