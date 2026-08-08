# -*- coding: utf-8 -*-
"""Patreon 订阅 Mod 浏览页。

左侧：已订阅/关注的创作者列表（可筛选）。
右侧：帖子三种视图（紧凑/详情/卡片，与 GameBanana 页一致），
点击帖子打开详情对话框（封面、正文、附件、外链）。
"""

import math
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from modules.dialogs import _apply_dialog_titlebar_color, showerror, showinfo

import customtkinter as ctk

from modules.catalog_view import (
    CARD,
    COMPACT,
    DETAILED,
    VIEW_MODE_ORDER,
    fit_card_text,
    normalize_view_mode,
)
from modules.config import (
    APP_DIR,
    ConfigManager,
    get_patreon_download_dir,
    get_patreon_profile_dir,
)
from modules.i18n import get_i18n, t
from modules.ai_translate import get_ai_api_key, translate_text
from modules.local_preview_cache import LocalPreviewCache
from modules.patreon import (
    PatreonNotLoggedIn,
    PatreonSession,
    render_content_blocks,
    render_content_text,
    sort_posts,
)

CARD_GAP = 4
# 与 GameBanana 卡片同一规格（宽 256、间距 4、16:9 预览），独立实现避免跨模块引用
CARD_WIDTH = 256
# 三种视图预览尺寸与本地/GameBanana 完全一致
COMPACT_PREVIEW = (85, 48)
DETAILED_PREVIEW = (150, 84)
DETAIL_COVER = (520, 292)


def _card_preview_size(card_width, dpi_scale=1.0):
    """与 GameBanana 同一套 16:9 预览尺寸公式（独立实现）。

    返回 (缓存目标像素尺寸, 显示尺寸, 预览高度)。
    """
    image_width = max(210, card_width - 16)
    image_size = (image_width, max(118, round(image_width * 9 / 16)))
    preview_height = max(94, round(image_size[1] / dpi_scale))
    display_size = (
        max(168, round(image_size[0] / dpi_scale)),
        preview_height,
    )
    return image_size, display_size, preview_height


def _card_columns(measured_width, card_width=CARD_WIDTH,
                  gap=CARD_GAP, dpi_scale=1.0):
    """与 GameBanana 同款动态列数公式（独立实现）。"""
    available_width = max(card_width, (measured_width - 24) / dpi_scale)
    return max(
        1,
        int((available_width + gap) // (card_width + gap)),
    )


def _apply_windows_titlebar_color(window, appearance_mode):
    """仅 Windows：直接设置 DWM 深色/浅色标题栏属性，不做库的 withdraw+update。

    与 GameBanana 同款独立实现：库的 _windows_set_titlebar_color() 会 withdraw
    窗口强制重绘，在窗口已被 grab_set 后会导致 Tk 事件循环卡死。
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if appearance_mode.lower() == "dark" else 0)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def split_creators_by_hidden(creators, hidden_ids):
    """将创作者列表按屏蔽 campaign_id 集合分为 (可见, 已屏蔽) 两组。"""
    hidden = {str(cid) for cid in (hidden_ids or [])}
    visible, blocked = [], []
    for creator in creators:
        if str(creator.get("campaign_id")) in hidden:
            blocked.append(creator)
        else:
            visible.append(creator)
    return visible, blocked


def filter_posts_by_access(posts, hide_unentitled):
    """按设置过滤帖子列表：开启时隐藏无权限查看的帖子（can_view=False）。"""
    if not hide_unentitled:
        return posts
    return [post for post in posts if post.get("can_view")]


class PatreonBrowserFrame(ctk.CTkFrame):
    def __init__(self, master, root, on_install_post, on_open_external):
        super().__init__(master, fg_color=("gray95", "gray14"))
        self.root = root
        self.on_install_post = on_install_post
        self.on_open_external = on_open_external

        self._destroyed = False
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="patreon-worker")
        self._image_executor = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="patreon-img")
        self._futures = set()
        self._futures_lock = threading.Lock()

        self._session = None
        self._session_lock = threading.Lock()
        self._logged_in = None
        self._creators = []
        self._posts_state = {}
        self._collections_cache = {}
        self._collections = []
        self._collections_menu = None
        self._collection_posts = []
        self._post_source = {"type": "all"}
        self._selected_campaign_id = None
        self._loading = False
        self._more_widget = None

        self._view_mode = normalize_view_mode(
            ConfigManager.get_view_mode("patreon"), default=DETAILED)
        self._sort = "latest"
        self._current_posts = []
        self._current_campaign_id = None
        self._card_area_width = 0
        self._card_columns = None
        self._card_grid = None
        self._card_watch_job = None
        self._dpi_scale = self._detect_dpi_scale()
        self._details_cache = {}
        self._details_pending = set()

        self._thumb_cache = LocalPreviewCache(
            os.path.join(APP_DIR, "data", "cache", "patreon_thumbs"))
        self._raw_cache_dir = os.path.join(APP_DIR, "data", "cache", "patreon_raw")
        self._image_pending = {}
        self._image_tokens = {}

        self._hidden_creators = {
            str(cid) for cid in ConfigManager.get_patreon_hidden_creators()}
        self._show_hidden_var = ctk.BooleanVar(value=False)
        self._hide_unentitled = ConfigManager.get_patreon_hide_unentitled()
        self._hide_unentitled_var = ctk.BooleanVar(value=self._hide_unentitled)
        self._build()
        self._card_watch_job = self.root.after(300, self._watch_card_area)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build(self):
        # 控制区两排（与 GameBanana 同款结构）
        controls = ctk.CTkFrame(self, fg_color=("gray90", "gray17"))
        controls.pack(fill="x", padx=0, pady=0)

        row1 = ctk.CTkFrame(controls, fg_color="transparent")
        row1.pack(fill="x", padx=0, pady=(8, 8))

        self._login_button = ctk.CTkButton(
            row1, text=t("patreon.login", "登录 Patreon"),
            width=110, command=self._on_login)
        self._login_button.pack(side="left", padx=(12, 4))

        self._reload_button = ctk.CTkButton(
            row1, text=t("patreon.reload_creators", "🔄 刷新订阅"),
            width=110, command=self._on_reload)
        self._reload_button.pack(side="left", padx=4)

        self._sort_switch = ctk.CTkSegmentedButton(
            row1, width=170, command=self._on_sort_change)
        self._sort_switch.pack(side="left", padx=(6, 4))
        self._update_sort_switch_labels()

        # 合集入口：前缀文字 + 当前选择按钮（参考 GameBanana 分类按钮）
        self._collections_label = ctk.CTkLabel(
            row1, text=t("patreon.collections_label", "合集"))
        self._collections_label.pack(side="left", padx=(12, 6))
        self._collections_button = ctk.CTkButton(
            row1, text=self._collections_button_text(),
            width=220, command=self._show_collections_menu)
        self._collections_button.pack(side="left", padx=4)
        self._update_collections_button()

        row2 = ctk.CTkFrame(controls, fg_color="transparent")
        row2.pack(fill="x", padx=0, pady=(0, 8))

        # 右对齐：隐藏无权限帖子（右）+ 三种显示方式切换（左）
        self._hide_unentitled_switch = ctk.CTkSwitch(
            row2, text=t("patreon.hide_unentitled", "隐藏无权限帖子"),
            variable=self._hide_unentitled_var,
            onvalue=True, offvalue=False,
            command=self._toggle_hide_unentitled)
        self._hide_unentitled_switch.pack(side="right", padx=(8, 12))

        self._view_switch = ctk.CTkSegmentedButton(
            row2, width=250, command=self._on_view_mode_change)
        self._view_switch.pack(side="right", padx=(6, 8))
        self._update_view_switch_labels()

        # 状态栏：与 GameBanana 同位置（控制区下方，灰色靠左）
        self._status_label = ctk.CTkLabel(
            self, text=t("patreon.status_starting", "正在启动 Patreon 会话..."),
            text_color="gray")
        self._status_label.pack(fill="x", padx=14, pady=(8, 2), anchor="w")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        left_col = ctk.CTkFrame(body, fg_color="transparent", width=230)
        left_col.pack(side="left", fill="y", padx=(0, 8))
        left_col.pack_propagate(False)

        # 左侧栏顶部：显示隐藏创作者开关（在所有创作者上方）
        self._show_hidden_switch = ctk.CTkSwitch(
            left_col, text=t("patreon.show_hidden", "显示隐藏创作者"),
            variable=self._show_hidden_var,
            onvalue=True, offvalue=False,
            command=self._render_creators)
        self._show_hidden_switch.pack(fill="x", padx=8, pady=(0, 6))

        self._creators_frame = ctk.CTkScrollableFrame(
            left_col, fg_color=("gray90", "gray17"))
        self._creators_frame.pack(fill="both", expand=True)

        self._posts_frame = ctk.CTkScrollableFrame(
            body, fg_color=("gray90", "gray17"))
        self._posts_frame.pack(side="left", fill="both", expand=True)

    def _sort_labels(self):
        return {
            "latest": t("patreon.sort_latest", "🕐 最新"),
            "popular": t("patreon.sort_popular", "🔥 热门"),
        }

    def _sort_param(self):
        return "-like_count" if self._sort == "popular" else "-published_at"

    def _update_sort_switch_labels(self):
        labels = self._sort_labels()
        self._sort_switch.configure(values=[labels["latest"], labels["popular"]])
        self._sort_switch.set(labels[self._sort])

    def _on_sort_change(self, selected_label):
        labels = self._sort_labels()
        by_label = {label: key for key, label in labels.items()}
        sort = by_label.get(selected_label)
        if sort is None or sort == self._sort:
            return
        self._sort = sort
        if self._post_source.get("type") == "collection":
            # 合集模式：合集帖子已全量加载，本地按新排序重排即可
            self._collection_posts = sort_posts(
                self._collection_posts, self._sort_param())
            self._current_posts = self._filter_posts(self._collection_posts)
            self._rerender_posts()
            self._set_status(t(
                "patreon.collection_count",
                "合集：{title}（{count} 篇）").format(
                title=self._post_source.get("title") or "-",
                count=len(self._current_posts)))
            return
        campaign_id = self._current_campaign_id
        if campaign_id is None:
            return
        # 全部帖子模式：清空缓存并按新排序重新加载第一页
        self._posts_state.pop(campaign_id, None)
        self._post_source = {"type": "all"}
        self._collection_posts = []
        self._current_posts = []
        self._set_status(t("patreon.loading_posts", "正在加载帖子..."))
        self._run_worker(self._load_posts, campaign_id)

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
        self._view_switch.set(labels[self._view_mode])

    def _on_view_mode_change(self, selected_label):
        labels = self._view_mode_labels()
        by_label = {label: mode for mode, label in labels.items()}
        mode = by_label.get(selected_label)
        if mode is None or mode == self._view_mode:
            return
        self._view_mode = mode
        ConfigManager.set_view_mode("patreon", mode)
        self._rerender_posts()

    @staticmethod
    def _detect_dpi_scale():
        if os.name != "nt":
            return 1.0
        try:
            import ctypes
            hdc = ctypes.windll.user32.GetDC(0)
            if hdc:
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
                ctypes.windll.user32.ReleaseDC(0, hdc)
                if dpi and dpi > 0:
                    return max(0.8, min(dpi / 96.0, 3.0))
        except Exception:
            pass
        return 1.0

    # ============================================================
    # 会话管理
    # ============================================================
    def ensure_session(self):
        """获取（必要时启动）Patreon 浏览器会话。"""
        with self._session_lock:
            if self._session is None:
                session = PatreonSession(
                    get_patreon_profile_dir(), get_patreon_download_dir())
                session.start(timeout=90)
                self._session = session
            return self._session

    def _post(self, fn, *args):
        if self._destroyed:
            return
        try:
            self.root.after(0, fn, *args)
        except Exception:
            pass

    def _track_future(self, future):
        with self._futures_lock:
            self._futures.add(future)

        def discard(_done):
            with self._futures_lock:
                self._futures.discard(future)

        future.add_done_callback(discard)
        return future

    def _set_status(self, text):
        def update():
            if not self._destroyed:
                self._status_label.configure(text=text)
        self._post(update)

    # ============================================================
    # 对外入口（gui 调用）
    # ============================================================
    def begin(self):
        """进入页面时调用：检查登录态，加载已保存的创作者列表。"""
        self._creators = [c for c in ConfigManager.get_patreon_creators() if c]
        self._prune_hidden_creators()
        self._render_creators()
        self._update_collections_button()
        if self._selected_campaign_id is None:
            self._show_hint(t("patreon.choose_creator",
                              "← 选择左侧创作者查看帖子"))
        if self._session is None:
            self._run_worker(self._refresh_login_state)

    def _prune_hidden_creators(self):
        """清理已屏蔽列表中已不存在的 campaign_id（避免配置文件残留）。"""
        valid = {str(c.get("campaign_id")) for c in self._creators}
        stale = self._hidden_creators - valid
        if stale:
            self._hidden_creators -= stale
            ConfigManager.set_patreon_hidden_creators(
                sorted(self._hidden_creators))

    def reload(self):
        self._on_reload()

    def apply_language(self):
        self._post(self._apply_language_ui)

    def _apply_language_ui(self):
        if self._destroyed:
            return
        self._login_button.configure(text=t("patreon.login", "登录 Patreon"))
        self._reload_button.configure(
            text=t("patreon.reload_creators", "🔄 刷新订阅"))
        self._show_hidden_switch.configure(
            text=t("patreon.show_hidden", "显示隐藏创作者"))
        self._hide_unentitled_switch.configure(
            text=t("patreon.hide_unentitled", "隐藏无权限帖子"))
        self._collections_label.configure(
            text=t("patreon.collections_label", "合集"))
        self._update_collections_button()
        self._update_view_switch_labels()
        self._update_sort_switch_labels()
        self._update_login_label()

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        if self._card_watch_job is not None:
            try:
                self.root.after_cancel(self._card_watch_job)
            except Exception:
                pass
            self._card_watch_job = None
        with self._futures_lock:
            futures = tuple(self._futures)
        for future in futures:
            try:
                future.cancel()
            except Exception:
                pass
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass
        try:
            self._image_executor.shutdown(wait=False)
        except Exception:
            pass
        if self._session is not None:
            session = self._session
            self._session = None
            threading.Thread(
                target=session.close, name="patreon-close", daemon=True).start()
        super().destroy()

    # ============================================================
    # 登录
    # ============================================================
    def _refresh_login_state(self):
        try:
            session = self.ensure_session()
            logged = session.is_logged_in()
        except Exception:
            logged = False
        self._logged_in = logged
        self._post(self._update_login_label)

    def _update_login_label(self):
        if self._destroyed:
            return
        if self._logged_in:
            self._login_button.configure(text=t("patreon.relogin", "重新登录"))
            self._status_label.configure(
                text=t("patreon.status_logged_in", "已登录 Patreon"))
        else:
            self._login_button.configure(text=t("patreon.login", "登录 Patreon"))
            self._status_label.configure(
                text=t("patreon.status_logged_out", "未登录 Patreon"))

    def _on_login(self):
        if self._loading:
            return
        self._login_button.configure(state="disabled")
        self._set_status(t("patreon.login_waiting", "请在打开的浏览器窗口中登录..."))

        def worker():
            try:
                session = self.ensure_session()
                logged = session.ensure_login(timeout=None)
                self._logged_in = bool(logged)
                self._post(self._update_login_label)
                if logged:
                    self._reload_creators()
                else:
                    self._set_status(t("patreon.status_logged_out", "未登录 Patreon"))
            except Exception as exc:
                self._post(self._show_error, str(exc))
            finally:
                self._post(lambda: self._login_button.configure(state="normal"))

        self._track_future(self._executor.submit(worker))

    # ============================================================
    # 创作者
    # ============================================================
    def _on_reload(self):
        if self._loading:
            return
        self._run_worker(self._reload_creators)

    def _reload_creators(self):
        if self._loading:
            return
        self._loading = True
        self._post(lambda: self._reload_button.configure(state="disabled"))
        self._set_status(t("patreon.loading_creators", "正在读取订阅列表..."))

        def worker():
            try:
                session = self.ensure_session()
                if not session.is_logged_in():
                    self._post(self._update_login_label)
                    self._post(self._show_hint,
                               t("patreon.need_login",
                                 "需要登录 Patreon 才能读取订阅列表，请点击「登录 Patreon」"))
                    return
                creators = session.list_subscribed_creators()
                if creators:
                    ConfigManager.set_patreon_creators(creators)
                self._creators = creators
                self._prune_hidden_creators()
                self._posts_state = {}
                self._collections_cache = {}
                self._collections = []
                self._collection_posts = []
                self._post_source = {"type": "all"}
                self._post(self._render_creators)
                self._set_status(t(
                    "patreon.creators_loaded", "已加载 {count} 个创作者").format(
                    count=len(creators)))
            except Exception as exc:
                self._post(self._show_error, str(exc))
            finally:
                self._loading = False
                self._post(lambda: self._reload_button.configure(state="normal"))

        self._track_future(self._executor.submit(worker))

    def _render_creators(self):
        if self._destroyed:
            return
        for child in self._creators_frame.winfo_children():
            child.destroy()
        visible, blocked = split_creators_by_hidden(
            self._creators, self._hidden_creators)
        rows = visible + (blocked if self._show_hidden_var.get() else [])
        if not rows:
            if self._show_hidden_var.get() and not visible and blocked:
                text = t("patreon.all_creators_hidden",
                         "所有创作者已隐藏\n关闭「显示隐藏创作者」可收起列表")
            else:
                text = t("patreon.no_creators",
                         "未找到创作者\n点击「刷新订阅」从 Patreon 读取")
            label = ctk.CTkLabel(
                self._creators_frame, text=text,
                text_color="gray", justify="left")
            label.pack(fill="x", padx=6, pady=8)
            return
        for creator in rows:
            campaign_id = creator.get("campaign_id")
            is_hidden = str(campaign_id) in self._hidden_creators
            name = creator.get("name") or str(campaign_id)
            row = ctk.CTkFrame(self._creators_frame, fg_color="transparent")
            row.pack(fill="x", padx=2, pady=2)
            button = ctk.CTkButton(
                row, text=name, anchor="w",
                fg_color="transparent" if is_hidden else None,
                text_color=("gray50", "gray50") if is_hidden else None,
                command=lambda cid=campaign_id: self._select_creator(cid))
            button.pack(side="left", fill="x", expand=True)
            action = ctk.CTkButton(
                row, height=26, width=58, font=ctk.CTkFont(size=11),
                text=(t("patreon.restore_creator", "恢复") if is_hidden
                      else t("patreon.hide_creator", "屏蔽")),
                command=lambda cid=campaign_id: self._toggle_hidden_creator(cid))
            action.pack(side="right", padx=(4, 0))

    def _toggle_hidden_creator(self, campaign_id):
        key = str(campaign_id)
        if key in self._hidden_creators:
            self._hidden_creators.discard(key)
        else:
            self._hidden_creators.add(key)
            if (self._selected_campaign_id is not None
                    and str(self._selected_campaign_id) == key):
                self._selected_campaign_id = None
                self._post_source = {"type": "all"}
                self._collections = []
                self._collection_posts = []
                self._current_posts = []
                self._current_campaign_id = None
                for widget in self._posts_frame.winfo_children():
                    widget.destroy()
                self._update_collections_button()
        ConfigManager.set_patreon_hidden_creators(
            sorted(self._hidden_creators))
        self._render_creators()

    def _filter_posts(self, posts):
        """按「隐藏无权限帖子」设置过滤帖子列表。"""
        return filter_posts_by_access(posts, self._hide_unentitled)

    def _toggle_hide_unentitled(self):
        self._hide_unentitled = bool(self._hide_unentitled_var.get())
        ConfigManager.set_patreon_hide_unentitled(self._hide_unentitled)
        if self._post_source.get("type") == "collection":
            self._current_posts = self._filter_posts(self._collection_posts)
            self._rerender_posts()
            self._set_status(t(
                "patreon.collection_count",
                "合集：{title}（{count} 篇）").format(
                title=self._post_source.get("title") or "-",
                count=len(self._current_posts)))
        elif self._current_campaign_id is not None:
            state = self._posts_state.get(self._current_campaign_id)
            if state:
                self._current_posts = self._filter_posts(state["posts"])
                self._rerender_posts()
                self._update_status_count()

    def _select_creator(self, campaign_id):
        if self._loading:
            return
        self._selected_campaign_id = campaign_id
        self._post_source = {"type": "all"}
        self._collection_posts = []
        self._update_collections_button()
        self._set_status(t("patreon.loading_posts", "正在加载帖子..."))
        self._run_worker(self._load_posts, campaign_id)
        self._run_worker(self._load_collections_meta, campaign_id)

    # ============================================================
    # 合集（分类入口，一层；位于最新/热门旁的「合集」按钮弹层）
    # ============================================================
    def _load_collections_meta(self, campaign_id):
        """轻量拉取该创作者的合集列表（弹层菜单按需读取）。"""
        try:
            session = self.ensure_session()
            collections, _posts = session.campaign_collections(
                campaign_id, with_posts=False)
        except Exception:
            collections = []
        if (self._selected_campaign_id is not None
                and str(campaign_id) == str(self._selected_campaign_id)):
            self._collections = collections

    def _collections_button_text(self):
        """合集按钮文案：当前选择 + 下拉提示标识（参考 GameBanana 分类按钮）。"""
        source = self._post_source
        if source.get("type") == "collection":
            title = (source.get("title")
                     or t("patreon.collections_title", "合集"))
            return "📁 {title}  ▾".format(title=title[:16])
        return t("patreon.all_posts", "🗂 全部帖子") + "  ▾"

    def _update_collections_button(self):
        """未选择创作者时置灰并提示，选中后显示当前选择（样式同 GameBanana）。"""
        if self._destroyed:
            return
        if self._selected_campaign_id is None:
            self._collections_button.configure(
                state="disabled",
                text=t("patreon.select_creator_first", "请先选择创作者"))
        else:
            self._collections_button.configure(
                state="normal", text=self._collections_button_text())

    def _show_collections_menu(self):
        """合集弹层菜单（tk.Menu 样式参考 GameBanana 分类弹层）。"""
        if self._destroyed or self._selected_campaign_id is None:
            return
        try:
            if not self._collections_button.winfo_exists():
                return
        except Exception:
            return
        self._destroy_collections_menu()
        import tkinter as tk
        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#2b2b2b", fg="#e0e0e0",
            activebackground="#3B8ED0", activeforeground="white",
            font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))),
            bd=1, relief="flat",
        )
        self._collections_menu = menu
        menu.add_command(
            label=t("patreon.all_posts", "🗂 全部帖子"),
            command=self._select_all_posts)
        if self._collections:
            menu.add_separator()
            for collection in self._collections:
                collection_id = collection.get("id")
                title_text = (collection.get("title")
                              or t("patreon.collections_title", "合集"))
                count = len(collection.get("post_ids") or [])
                label = "📁 {title}".format(title=title_text[:16])
                if count:
                    label += "（{count}）".format(count=count)
                menu.add_command(
                    label=label,
                    command=lambda cid=collection_id, t=title_text:
                        self._select_collection(cid, t))
        else:
            menu.add_separator()
            menu.add_command(
                label=t("patreon.no_collections", "该创作者暂无合集"),
                state="disabled")
        try:
            menu.tk_popup(
                self._collections_button.winfo_rootx(),
                self._collections_button.winfo_rooty()
                + self._collections_button.winfo_height())
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _destroy_collections_menu(self):
        if self._collections_menu is not None:
            try:
                self._collections_menu.destroy()
            except Exception:
                pass
            self._collections_menu = None

    def _select_collection(self, collection_id, collection_title):
        if self._loading:
            return
        campaign_id = self._selected_campaign_id
        if campaign_id is None:
            return
        self._post_source = {
            "type": "collection", "campaign_id": campaign_id,
            "collection_id": collection_id, "title": collection_title}
        self._update_collections_button()
        self._set_status(t(
            "patreon.loading_collection",
            "正在加载合集：{title}...").format(title=collection_title))
        self._run_worker(self._load_collection, campaign_id, collection_id)

    def _load_collection(self, campaign_id, collection_id):
        self._loading = True
        try:
            session = self.ensure_session()
            if campaign_id not in self._collections_cache:
                collections, posts_map = session.campaign_collections(
                    campaign_id, with_posts=True)
                self._collections_cache[campaign_id] = (collections, posts_map)
                self._collections = collections
            else:
                collections, posts_map = self._collections_cache[campaign_id]
            collection = next(
                (c for c in collections if c.get("id") == collection_id), None)
            if not collection:
                raise PatreonError("合集不存在: %s" % collection_id)
            posts = [posts_map[post_id] for post_id in collection.get("post_ids", [])
                     if post_id in posts_map]
            posts = sort_posts(posts, self._sort_param())
            self._collection_posts = posts
            self._post(self._render_collection, collection_id, posts)
        except Exception as exc:
            self._post(self._show_error, str(exc))
        finally:
            self._loading = False
            self._post(self._update_more_area)

    def _render_collection(self, collection_id, posts):
        if (self._destroyed or self._selected_campaign_id is None
                or str(self._selected_campaign_id) in self._hidden_creators):
            return
        self._current_campaign_id = self._selected_campaign_id
        self._current_posts = self._filter_posts(posts)
        self._post_source = {
            "type": "collection", "campaign_id": self._selected_campaign_id,
            "collection_id": collection_id,
            "title": self._post_source.get("title")}
        self._rerender_posts()
        self._update_collections_button()
        self._set_status(t(
            "patreon.collection_count",
            "合集：{title}（{count} 篇）").format(
            title=self._post_source.get("title") or "-",
            count=len(self._current_posts)))

    def _select_all_posts(self):
        if self._loading or self._selected_campaign_id is None:
            return
        campaign_id = self._selected_campaign_id
        if self._post_source.get("type") == "all":
            return
        self._post_source = {"type": "all"}
        self._collection_posts = []
        self._update_collections_button()
        state = self._posts_state.get(campaign_id)
        if state and state.get("posts"):
            self._current_posts = self._filter_posts(state["posts"])
            self._current_campaign_id = campaign_id
            self._rerender_posts()
            self._update_status_count()
        else:
            self._set_status(t("patreon.loading_posts", "正在加载帖子..."))
            self._run_worker(self._load_posts, campaign_id)

    # ============================================================
    # 帖子加载与渲染（三视图，30 篇/页 + 加载更多）
    # ============================================================
    def _load_posts(self, campaign_id):
        self._loading = True
        try:
            session = self.ensure_session()
            posts, cursor, total = session.creator_posts(
                campaign_id, sort=self._sort_param())
            self._posts_state[campaign_id] = {
                "posts": posts, "cursor": cursor, "total": total}
            self._post(self._render_posts, campaign_id)
            self._post(self._update_status_count)
        except PatreonNotLoggedIn:
            self._post(self._show_hint,
                       t("patreon.need_login",
                         "需要登录 Patreon 才能加载付费帖子，请点击「登录 Patreon」"))
        except Exception as exc:
            self._post(self._show_error, str(exc))
        finally:
            self._loading = False
            # 重新渲染"加载更多"区域：_render_posts 的回调可能在 _loading
            # 仍为 True 时执行（显示"正在加载更多"占位），完成后必须恢复按钮
            self._post(self._update_more_area)

    def _load_more(self):
        if self._loading or self._current_campaign_id is None:
            return
        state = self._posts_state.get(self._current_campaign_id)
        if not state or not state.get("cursor"):
            return
        self._loading = True
        self._update_more_area()

        def worker():
            try:
                session = self.ensure_session()
                posts, cursor, total = session.creator_posts(
                    self._current_campaign_id, cursor=state.get("cursor"),
                    sort=self._sort_param())
                rendered_before = len(self._current_posts)
                state["posts"].extend(posts)
                state["cursor"] = cursor
                if total is not None:
                    state["total"] = total
                self._current_posts = self._filter_posts(state["posts"])
                self._post(self._append_posts_widgets, rendered_before)
                self._post(self._update_status_count)
            except Exception as exc:
                self._post(self._show_error, str(exc))
            finally:
                self._loading = False
                self._post(self._update_more_area)

        self._track_future(self._executor.submit(worker))

    def _update_status_count(self):
        state = self._posts_state.get(self._current_campaign_id)
        if not state:
            return
        shown = len(self._current_posts or [])
        total = state.get("total")
        if total:
            self._set_status(t(
                "patreon.shown_total",
                "显示 {shown} / {total} 篇帖子").format(
                shown=shown, total=total))
        else:
            self._set_status(t(
                "patreon.shown_count", "已显示 {shown} 篇帖子").format(shown=shown))

    def _render_posts(self, campaign_id):
        if self._destroyed or str(campaign_id) in self._hidden_creators:
            return
        self._current_campaign_id = campaign_id
        self._current_posts = self._filter_posts(
            (self._posts_state.get(campaign_id) or {}).get("posts") or [])
        self._rerender_posts()

    def _rerender_posts(self):
        if self._destroyed:
            return
        for child in self._posts_frame.winfo_children():
            child.destroy()
        if not self._current_posts:
            filtered_empty = (
                self._hide_unentitled
                and self._post_source.get("type") != "collection"
                and bool((self._posts_state.get(
                    self._current_campaign_id) or {}).get("posts")))
            if filtered_empty:
                text = t(
                    "patreon.no_posts_filtered",
                    "没有可查看的帖子\n（已开启「隐藏无权限帖子」，可取消勾选查看全部）")
            else:
                text = t(
                    "patreon.no_posts",
                    "该创作者暂无可见帖子\n（免费与付费帖子都会显示，付费内容需订阅后可见）")
            label = ctk.CTkLabel(
                self._posts_frame, text=text,
                text_color="gray", justify="center", wraplength=480)
            label.pack(fill="x", padx=20, pady=60)
            self._update_more_area()
            return
        if self._view_mode == CARD:
            self._render_cards(0)
        elif self._view_mode == DETAILED:
            for post in self._current_posts:
                self._render_row(post, DETAILED_PREVIEW, detailed=True)
        else:
            for post in self._current_posts:
                self._render_row(post, COMPACT_PREVIEW, detailed=False)
        self._update_more_area()

    def _append_posts_widgets(self, start_index):
        """追加渲染 start_index 起的帖子（加载更多时调用）。"""
        if self._destroyed or not self._current_posts:
            return
        if start_index >= len(self._current_posts):
            self._update_more_area()
            return
        self._remove_more_widget()
        if self._view_mode == CARD:
            self._render_cards(0)
        elif self._view_mode == DETAILED:
            for post in self._current_posts[start_index:]:
                self._render_row(post, DETAILED_PREVIEW, detailed=True)
        else:
            for post in self._current_posts[start_index:]:
                self._render_row(post, COMPACT_PREVIEW, detailed=False)
        self._update_more_area()

    def _update_more_area(self):
        if self._destroyed:
            return
        self._remove_more_widget()
        if self._post_source.get("type") == "collection":
            return  # 合集帖子一次性加载，无分页
        state = self._posts_state.get(self._current_campaign_id)
        has_next = bool(state and state.get("cursor"))
        if not has_next:
            return
        columns = max(1, self._card_columns or 1)
        parent = (self._card_grid if self._card_grid is not None
                  else self._posts_frame)
        if self._loading:
            self._more_widget = ctk.CTkLabel(
                parent, text=t("patreon.loading_more", "正在加载更多..."),
                text_color="gray")
        else:
            self._more_widget = ctk.CTkButton(
                parent, text=t("patreon.load_more", "加载更多"),
                width=200, height=32, command=self._load_more)
        if self._view_mode == CARD and self._card_grid is not None:
            row = -(-len(self._current_posts) // columns)
            self._more_widget.grid(
                row=row, column=0, columnspan=columns, pady=10)
        else:
            self._more_widget.pack(fill="x", pady=10)

    def _remove_more_widget(self):
        if self._more_widget is not None:
            try:
                self._more_widget.destroy()
            except Exception:
                pass
            self._more_widget = None

    def _watch_card_area(self):
        """卡片模式下监听宽度变化，列数改变时重渲染（与 GameBanana 同一模式）。"""
        self._card_watch_job = None
        if self._destroyed or not self.winfo_exists():
            return
        try:
            self.root.update_idletasks()
            canvas = self._posts_frame._parent_canvas
            width = canvas.winfo_width() or self._posts_frame.winfo_width()
            self._card_area_width = width
            if width and self._view_mode == CARD and self._current_posts:
                columns = _card_columns(width, dpi_scale=self._dpi_scale)
                if columns != self._card_columns:
                    self._card_columns = columns
                    self._rerender_posts()
        except Exception:
            pass
        if not self._destroyed:
            try:
                self._card_watch_job = self.root.after(
                    150, self._watch_card_area)
            except Exception:
                pass

    def _render_cards(self, start_index=0):
        """卡片视图：与 GameBanana 同款动态网格布局（网格容器 + 列 minsize
        + 卡片等高）。重新构建整个网格（加载更多时也整体重渲染）。"""
        for child in self._posts_frame.winfo_children():
            child.destroy()
        posts = self._current_posts
        if not posts:
            return
        try:
            self.root.update_idletasks()
            canvas = self._posts_frame._parent_canvas
            width = canvas.winfo_width() or self._posts_frame.winfo_width() or 800
        except Exception:
            width = 800
        columns = _card_columns(width, dpi_scale=self._dpi_scale)
        self._card_columns = columns
        grid = ctk.CTkFrame(
            self._posts_frame,
            width=columns * (CARD_WIDTH + CARD_GAP),
            fg_color="transparent",
        )
        grid.pack(anchor="n")
        self._card_grid = grid
        card_pixel_width = round(CARD_WIDTH * self._dpi_scale)
        card_pixel_padding = math.ceil((CARD_GAP // 2) * self._dpi_scale)
        slot_width = card_pixel_width + card_pixel_padding * 2
        for column in range(columns):
            grid.grid_columnconfigure(column, minsize=slot_width)
        cards = []
        for index, post in enumerate(posts):
            cards.append(self._build_card(post, grid, index, columns))
        if cards:
            try:
                self.root.update_idletasks()
                uniform_height = max(
                    1, round(max(
                        card.winfo_reqheight() for card in cards)
                        / self._dpi_scale))
                for card in cards:
                    card.configure(
                        width=CARD_WIDTH, height=uniform_height)
                    card.pack_propagate(False)
            except Exception:
                pass

    def _build_card(self, post, grid, index, columns):
        """卡片本体：样式与 GameBanana 卡片一致（圆角/描边/预览/信息区布局）。"""
        card = ctk.CTkFrame(
            grid, width=CARD_WIDTH, corner_radius=8,
            fg_color=("gray92", "gray13"),
            border_width=1, border_color=("gray78", "gray23"),
        )
        card.grid(
            row=index // columns, column=index % columns,
            padx=CARD_GAP // 2, pady=4,
        )
        card.grid_propagate(False)

        image_size, display_size, _ = _card_preview_size(
            round(CARD_WIDTH * self._dpi_scale), dpi_scale=self._dpi_scale)

        cover = ctk.CTkLabel(
            card, text=t("patreon.no_cover", "无封面"),
            text_color=("gray48", "gray55"),
            width=display_size[0], height=display_size[1],
            fg_color=("gray84", "gray19"), corner_radius=7)
        cover.pack(fill="x", padx=6, pady=(6, 0))
        self._load_image(
            post.get("cover_thumb_url") or post.get("cover_url"),
            cover, display_size, post.get("post_id"))

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(fill="both", expand=True, padx=10, pady=(8, 8))

        title = post.get("title") or t("patreon.untitled", "(无标题)")
        title_font = ctk.CTkFont(size=12, weight="bold")
        text_width = max(
            80, round((CARD_WIDTH - 50) / self._dpi_scale) - 4)
        fitted_title = fit_card_text(title, title_font, text_width)
        title_container = ctk.CTkFrame(
            info, width=1, height=40, fg_color="transparent")
        title_container.pack(fill="x")
        title_container.pack_propagate(False)
        title_label = ctk.CTkLabel(
            title_container, text=fitted_title,
            font=title_font, anchor="w", justify="left")
        title_label.place(x=0, y=0, relwidth=1, relheight=1)

        meta_text = self._post_meta(post)
        meta_font = ctk.CTkFont(size=9)
        fitted_meta = fit_card_text(meta_text, meta_font, text_width)
        meta_container = ctk.CTkFrame(
            info, width=1, height=18, fg_color="transparent")
        meta_container.pack(fill="x", pady=(2, 0))
        meta_container.pack_propagate(False)
        meta_label = ctk.CTkLabel(
            meta_container, text=fitted_meta,
            font=meta_font, anchor="w", justify="left", text_color="gray")
        meta_label.place(x=0, y=0, relwidth=1, relheight=1)

        ctk.CTkButton(
            info, text=t("patreon.details", "📄 详情"), width=70, height=28,
            command=lambda p=post: self._show_post_details(p),
        ).pack(pady=(6, 2))

        self._bind_click(card, lambda e=None, p=post: self._show_post_details(p))
        self._bind_click(cover, lambda e=None, p=post: self._show_post_details(p))
        self._bind_click(title_label, lambda e=None, p=post: self._show_post_details(p))
        return card

    def _render_row(self, post, preview_size, detailed):
        row = ctk.CTkFrame(self._posts_frame, fg_color=("gray95", "gray18"),
                           corner_radius=8)
        row.pack(fill="x", padx=2, pady=3)

        cover = ctk.CTkLabel(row, text=t("patreon.no_cover", "无封面"),
                             text_color="gray", width=preview_size[0],
                             height=preview_size[1], fg_color=("gray85", "gray20"),
                             corner_radius=6)
        cover.pack(side="left", padx=(8, 8), pady=8)
        self._load_image(
            post.get("cover_thumb_url") or post.get("cover_url"),
            cover, preview_size, post.get("post_id"))

        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True, pady=8)

        title = post.get("title") or t("patreon.untitled", "(无标题)")
        title_label = ctk.CTkLabel(
            text_frame, text=title, font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w", justify="left", wraplength=520)
        title_label.pack(fill="x")

        meta_parts = [self._post_meta(post)]
        if detailed:
            teaser = (post.get("teaser_text") or "").strip()
            if teaser:
                meta_parts.append(teaser[:160])
        meta_label = ctk.CTkLabel(
            text_frame, text=" · ".join(meta_parts), text_color="gray",
            font=ctk.CTkFont(size=11), anchor="w", justify="left", wraplength=520)
        meta_label.pack(fill="x", pady=(2, 0))

        ctk.CTkButton(
            row, text=t("patreon.details", "📄 详情"), width=80, height=28,
            font=ctk.CTkFont(size=11), fg_color="transparent", border_width=1,
            command=lambda p=post: self._show_post_details(p)
        ).pack(side="right", padx=(4, 10), pady=8)

        self._bind_click(row, lambda e=None, p=post: self._show_post_details(p))
        self._bind_click(text_frame, lambda e=None, p=post: self._show_post_details(p))
        self._bind_click(cover, lambda e=None, p=post: self._show_post_details(p))

    def _post_meta(self, post):
        parts = []
        published = post.get("published_at")
        if published:
            try:
                from datetime import datetime
                parts.append(datetime.strptime(
                    published.split("+")[0].split(".")[0],
                    "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d"))
            except (ValueError, TypeError):
                parts.append(str(published))
        if post.get("is_paid"):
            parts.append(t("patreon.paid_badge", "💰 付费"))
        if not post.get("can_view"):
            parts.append(t("patreon.not_entitled",
                           "当前订阅等级不可查看此帖附件"))
        return " · ".join(parts)

    def _copy_link(self, url):
        import subprocess
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command",
                 "Set-Clipboard -Value '{}'".format(url.replace("'", "''"))],
                creationflags=0x08000000)
        except Exception:
            pass

    @staticmethod
    def _bind_click(widget, callback):
        widget.bind("<Button-1>", callback)

    # ============================================================
    # 帖子详情对话框（正文/附件/外链按需加载）
    # ============================================================
    def _show_post_details(self, post):
        if self._destroyed:
            return
        post_id = post.get("post_id")
        if post_id in self._details_pending:
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("patreon.details_title", "帖子详情"))
        dialog.geometry("840x720")
        dialog.minsize(640, 480)
        dialog.transient(self.root)

        body = ctk.CTkScrollableFrame(dialog, fg_color=("gray95", "gray14"))
        body.pack(fill="both", expand=True, padx=12, pady=10)

        cover = ctk.CTkLabel(body, text=t("patreon.no_cover", "无封面"),
                             text_color="gray", height=DETAIL_COVER[1],
                             width=DETAIL_COVER[0], fg_color=("gray85", "gray20"),
                             corner_radius=8)
        cover.pack(fill="x", pady=(0, 8))
        self._load_image(post.get("cover_url"), cover, DETAIL_COVER,
                         "detail-" + str(post_id))

        title = post.get("title") or t("patreon.untitled", "(无标题)")
        ctk.CTkLabel(body, text=title, font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w", justify="left", wraplength=780
                     ).pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(body, text=self._post_meta(post), text_color="gray",
                     font=ctk.CTkFont(size=11), anchor="w", justify="left"
                     ).pack(fill="x", pady=(0, 8))

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", padx=12, pady=(0, 10))
        post_url = post.get("post_url")
        if post_url:
            ctk.CTkButton(
                footer, text=t("patreon.open_page", "🌐 打开帖子页面"),
                width=150, height=30, fg_color="transparent", border_width=1,
                command=lambda u=post_url: self._open_post_page(u)
            ).pack(side="left")
        ctk.CTkButton(
            footer, text=t("patreon.close", "关闭"), width=90, height=30,
            command=dialog.destroy
        ).pack(side="right")

        def close_on_escape(_event):
            dialog.destroy()
        dialog.bind("<Escape>", close_on_escape)
        dialog.after(1, lambda: dialog.focus_set())
        # 非模态窗口不经过 grab_set()，需在此显式完成标题栏深色重绘
        _apply_dialog_titlebar_color(dialog)

        cached = self._details_cache.get(post_id)
        if cached is not None:
            # 与异步加载路径一致：在事件循环内渲染（窗口映射后再建控件，
            # 避免窗口未映射时同步创建 CTkButton 等控件导致 Tk 挂起）
            self._post(
                lambda: self._populate_details(body, post, cached, dialog))
            return

        self._details_pending.add(post_id)
        loading = ctk.CTkLabel(
            body, text=t("patreon.loading_details", "正在加载详情..."),
            text_color="gray")
        loading.pack(fill="x", pady=20)

        def worker():
            try:
                session = self.ensure_session()
                details = session.post_details(post_id)
                self._details_cache[post_id] = details
                error = None
            except Exception as exc:
                details = None
                error = str(exc)
            finally:
                self._details_pending.discard(post_id)
            self._post(self._on_details_ready, dialog, body, post, details, error, loading)

        self._track_future(self._executor.submit(worker))

    def _on_details_ready(self, dialog, body, post, details, error, loading):
        if self._destroyed or not dialog.winfo_exists():
            return
        loading.destroy()
        if error is not None or details is None:
            ctk.CTkLabel(
                body, text=t("patreon.details_failed", "详情加载失败：{error}").format(
                    error=error or "?"),
                text_color="#e06c75", justify="left", wraplength=780
            ).pack(fill="x", pady=(0, 10))
            return
        self._populate_details(body, post, details, dialog)

    def _populate_details(self, body, post, details, dialog):
        blocks = render_content_blocks(details.get("content_json"))
        texts = [block["text"] for block in blocks if block["type"] == "text"]
        content = "\n\n".join(texts)
        if content:
            ctk.CTkLabel(body, text=t("patreon.content_title", "正文"),
                         font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
                         ).pack(fill="x", pady=(0, 2))
            # 正文直接显示为自动换行文本（不嵌套滚动框）
            content_section = ctk.CTkFrame(body, fg_color="transparent")
            content_section.pack(fill="x", pady=(0, 12))
            ctk.CTkLabel(
                content_section, text=content, justify="left", anchor="w",
                wraplength=780, font=ctk.CTkFont(size=12)
            ).pack(fill="x")
            content_actions = ctk.CTkFrame(
                content_section, fg_color="transparent")
            content_actions.pack(anchor="w", pady=(6, 0))
            translate_btn = ctk.CTkButton(
                content_actions, text=t("ai.translate", "🌐 翻译"),
                width=90, height=26, font=ctk.CTkFont(size=11),
                command=lambda: self._translate_content(
                    dialog, content_section, translate_btn, content))
            translate_btn.pack(side="left")

        # 帖子图片：正文 image 块（按顺序）+ 图集（去重补充），横向滚动，点击看全图
        image_urls = []
        seen = set()
        for block in blocks:
            if block["type"] == "image":
                key = block["url"].split("?")[0]
                if key not in seen:
                    seen.add(key)
                    image_urls.append(block["url"])
        for url in details.get("images") or []:
            key = url.split("?")[0]
            if key not in seen:
                seen.add(key)
                image_urls.append(url)
        if image_urls:
            ctk.CTkLabel(body, text=t("patreon.images_title", "帖子图片"),
                         font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
                         ).pack(fill="x", pady=(0, 2))
            hscroll = ctk.CTkScrollableFrame(
                body, orientation="horizontal", height=220,
                fg_color=("gray95", "gray17"))
            hscroll.pack(fill="x", pady=(0, 12))
            for url in image_urls:
                image_label = ctk.CTkLabel(
                    hscroll, text=t("patreon.loading_details", "正在加载..."),
                    text_color="gray", width=300, height=200,
                    fg_color=("gray90", "gray18"), corner_radius=6)
                image_label.pack(side="left", padx=4, pady=4)
                image_label.bind(
                    "<Button-1>",
                    lambda _event, u=url: self._show_full_image(dialog, u))
                self._load_image_contain(
                    url, image_label, 300, 200,
                    "detail-img-" + url.split("?")[0][-24:])
            ctk.CTkLabel(body, text="", height=4).pack()

        file_items = []
        if details.get("post_file"):
            file_items.append((details["post_file"]["name"], details["post_file"]))
        file_items.extend(
            (a.get("name"), a) for a in (details.get("attachments") or []))

        external = details.get("external_links") or []
        embed = details.get("embed_url")
        if embed and embed not in external:
            external = [embed] + external

        if file_items:
            ctk.CTkLabel(body, text=t("patreon.attachments_title", "附件"),
                         font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
                         ).pack(fill="x", pady=(0, 2))
            can_view = details.get("can_view", False)
            for name, attachment in file_items:
                row = ctk.CTkFrame(body, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text="⬇ {}".format(name)[:70], anchor="w",
                             font=ctk.CTkFont(size=12)
                             ).pack(side="left", fill="x", expand=True)
                if can_view:
                    ctk.CTkButton(
                        row, text=t("patreon.install", "下载并安装"),
                        width=110, height=26, font=ctk.CTkFont(size=11),
                        command=lambda d=dialog, p=details, f=attachment:
                            self._install_from_details(d, p, f)
                    ).pack(side="right")
                else:
                    ctk.CTkLabel(row, text=t("patreon.subscribe_hint", "🔒 需订阅"),
                                 text_color="#e06c75", font=ctk.CTkFont(size=11)
                                 ).pack(side="right")
            ctk.CTkLabel(body, text="", height=4).pack()

        if external:
            ctk.CTkLabel(body, text=t("patreon.external_links_title", "外部下载链接"),
                         font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
                         ).pack(fill="x", pady=(0, 2))
            for index, url in enumerate(external, start=1):
                row = ctk.CTkFrame(body, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text="🔗 {}".format(url)[:80], anchor="w",
                             text_color="gray", font=ctk.CTkFont(size=11)
                             ).pack(side="left", fill="x", expand=True)
                ctk.CTkButton(
                    row, text=t("patreon.open_in_window", "打开并捕获"),
                    width=110, height=26, font=ctk.CTkFont(size=11),
                    command=lambda d=dialog, p=details, u=url:
                        self._open_external_from_details(d, p, u)
                ).pack(side="right", padx=(4, 0))
                ctk.CTkButton(
                    row, text=t("patreon.copy", "复制"), width=60, height=26,
                    font=ctk.CTkFont(size=11), fg_color="transparent",
                    border_width=1, command=lambda u=url: self._copy_link(u)
                ).pack(side="right")

    def _install_from_details(self, dialog, post, attachment):
        self.on_install_post(self._current_campaign_id, post, attachment)
        dialog.destroy()

    def _open_external_from_details(self, dialog, post, url):
        self.on_open_external(self._current_campaign_id, post, url)
        dialog.destroy()

    # ============================================================
    # 正文 AI 翻译（译文显示在原文下方，不替换、不持久化）
    # ============================================================
    def _translate_content(self, dialog, section, button, text):
        base = ConfigManager.get_ai_base_url()
        api_key = get_ai_api_key()
        if not base or not api_key:
            showinfo(
                t("ai.translate_title", "AI 翻译"),
                t("ai.not_configured",
                  "请先在「设置 → AI 翻译设置」中填写 Base URL 与 API Key"),
                parent=dialog)
            return
        target = get_i18n().effective_lang
        button.configure(
            state="disabled", text=t("ai.translating", "翻译中..."))
        status_label = ctk.CTkLabel(
            section, text=t("ai.translating", "翻译中..."),
            text_color="gray", justify="left", wraplength=780, anchor="w")
        status_label.pack(fill="x", pady=(6, 0))

        def worker():
            try:
                result = translate_text(
                    base, api_key, ConfigManager.get_ai_model(),
                    text, target)
                error = None
            except Exception as exc:
                result = None
                error = str(exc)
            self._post(self._apply_translation, dialog, section, button,
                       status_label, result, error)

        self._track_future(self._executor.submit(worker))

    def _apply_translation(self, dialog, section, button, status_label,
                           result, error):
        if self._destroyed:
            return
        try:
            if not dialog.winfo_exists():
                return
        except Exception:
            return
        status_label.destroy()
        if error:
            button.configure(
                state="normal", text=t("ai.translate", "🌐 翻译"))
            ctk.CTkLabel(
                section,
                text=t("ai.translate_failed", "翻译失败：{error}").format(
                    error=error),
                text_color="#e06c75", justify="left",
                wraplength=780, anchor="w",
            ).pack(fill="x", pady=(6, 0))
            return
        ctk.CTkLabel(
            section, text="🌐 " + result,
            justify="left", wraplength=780, anchor="w",
            text_color=("gray20", "gray85"),
        ).pack(fill="x", pady=(6, 0))
        button.configure(
            state="disabled", text=t("ai.translated", "已翻译"))

    def _open_post_page(self, url):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # ============================================================
    # 图片加载（列表封面 / 详情图文 / 全屏查看）
    # ============================================================
    def _load_image(self, url, label, display_size, token):
        if not url:
            return
        key = url.split("?")[0]
        pending_key = (key, display_size)
        if pending_key in self._image_pending:
            return
        self._image_pending[pending_key] = True

        def worker():
            try:
                image = self._fetch_image(key, url, display_size)
            except Exception:
                image = None
            finally:
                self._image_pending.pop(pending_key, None)
            if image is None:
                return
            self._post(self._apply_image, label, image, token)

        self._track_future(self._image_executor.submit(worker))

    def _load_image_contain(self, url, label, max_width, max_height, token):
        """等比缩放加载图片（详情页图文，不裁剪）。"""
        if not url:
            return
        key = url.split("?")[0]
        pending_key = ("contain", key)
        if pending_key in self._image_pending:
            return
        self._image_pending[pending_key] = True

        def worker():
            try:
                image = self._fetch_image_contain(
                    key, url, max_width, max_height)
            except Exception:
                image = None
            finally:
                self._image_pending.pop(pending_key, None)
            if image is None:
                return
            self._post(self._apply_image, label, image, token)

        self._track_future(self._image_executor.submit(worker))

    def _ensure_raw_image(self, key, url):
        """下载原图到磁盘缓存，返回本地路径。"""
        import hashlib
        import tempfile

        import httpx

        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        raw_path = os.path.join(
            self._raw_cache_dir, digest + os.path.splitext(key)[1][:6].lower())
        if not os.path.isfile(raw_path) or os.path.getsize(raw_path) == 0:
            os.makedirs(self._raw_cache_dir, exist_ok=True)
            response = httpx.get(
                url, timeout=30, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
                proxy=ConfigManager.get_proxy() or None)
            response.raise_for_status()
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=self._raw_cache_dir)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(response.content)
                os.replace(tmp, raw_path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        return raw_path

    def _fetch_image(self, key, url, display_size):
        from PIL import Image, ImageFilter, ImageOps

        raw_path = self._ensure_raw_image(key, url)
        if not ConfigManager.get_hide_sensitive_content():
            return self._thumb_cache.load(raw_path, display_size)
        try:
            with Image.open(raw_path) as source:
                image = ImageOps.fit(
                    source.convert("RGB"), display_size, method=Image.LANCZOS)
                image = image.filter(ImageFilter.GaussianBlur(14))
                image.load()
                return image
        except (OSError, ValueError):
            return None

    def _fetch_image_contain(self, key, url, max_width, max_height):
        """原图按比例缩放到 max_width x max_height 内（不裁剪）。"""
        from PIL import Image

        raw_path = self._ensure_raw_image(key, url)
        with Image.open(raw_path) as source:
            image = source.convert("RGB")
            ratio = min(
                1.0,
                max_width / float(image.width) if image.width else 1.0,
                max_height / float(image.height) if image.height else 1.0)
            if ratio < 1.0:
                new_size = (max(1, int(image.width * ratio)),
                            max(1, int(image.height * ratio)))
                image = image.resize(new_size, Image.LANCZOS)
            image.load()
            return image

    def _apply_image(self, label, image, token):
        if self._destroyed or not label.winfo_exists():
            return
        width, height = image.size
        photo = ctk.CTkImage(light_image=image, dark_image=image,
                             size=(width, height))
        label.configure(image=photo, text="")
        label.image = photo

    def _show_full_image(self, parent, url):
        """点击详情图片弹出全屏查看窗口（以详情对话框为父窗口，模态置顶）。

        参照 GameBanana 全屏逻辑：父窗口 + grab_set + lift，确保显示在最前；
        禁用标题栏色操纵，避免 customtkinter 的 withdraw 周期吞掉 grab。
        """
        if self._destroyed:
            return
        win = ctk.CTkToplevel(parent, fg_color=("gray90", "gray16"))
        try:
            win._deactivate_windows_window_header_manipulation = True
        except Exception:
            pass
        win.title(t("patreon.full_image", "查看图片"))
        win.geometry("900x700")
        win.transient(parent)
        label = ctk.CTkLabel(
            win, text=t("patreon.loading_details", "正在加载..."),
            text_color="gray")
        label.pack(fill="both", expand=True, padx=8, pady=8)

        def close_window():
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                if win.winfo_exists():
                    win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", close_window)
        win.bind("<Escape>", lambda _event: close_window())

        def finish_show():
            try:
                if self._destroyed or not win.winfo_exists():
                    return
                # 深色标题栏：直接设 DWM 属性（不 withdraw），与 GameBanana 全屏一致
                _apply_windows_titlebar_color(win, ctk.get_appearance_mode())
                # 先确保窗口映射可见并置顶（grab_set 在未映射窗口上会抛
                # TclError，且不能阻断 lift）
                win.update_idletasks()
                win.deiconify()
                win.lift()
                win.focus_force()
                try:
                    win.grab_set()
                except Exception:
                    pass
            except Exception:
                pass

        # 延迟置顶抓取：等窗口稳定可见后再 lift/grab，避免作用在隐藏窗口上
        win.after(60, finish_show)

        def worker():
            try:
                key = url.split("?")[0]
                raw_path = self._ensure_raw_image(key, url)
                image = self._fetch_image_contain(key, url, 880, 660)
            except Exception:
                image = None
            self._post(self._apply_full_image, win, label, image)

        self._track_future(self._image_executor.submit(worker))

    def _apply_full_image(self, win, label, image):
        if self._destroyed or not win.winfo_exists():
            return
        if image is None:
            label.configure(
                text=t("patreon.image_failed", "图片加载失败"), text_color="#e06c75")
            return
        width, height = image.size
        photo = ctk.CTkImage(light_image=image, dark_image=image,
                             size=(width, height))
        label.configure(image=photo, text="")
        label.image = photo

    # ============================================================
    # 工具
    # ============================================================
    def _run_worker(self, fn, *args):
        self._track_future(self._executor.submit(fn, *args))

    def _show_hint(self, text):
        if self._destroyed:
            return
        self._remove_more_widget()
        label = ctk.CTkLabel(
            self._posts_frame, text=text, text_color="gray", justify="center",
            wraplength=520)
        label.pack(fill="x", padx=20, pady=60)

    def _show_error(self, text):
        if self._destroyed:
            return
        showerror(t("patreon.error_title", "Patreon 操作失败"), text)
