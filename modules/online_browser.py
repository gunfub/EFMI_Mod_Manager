# -*- coding: utf-8 -*-
"""Native customtkinter GameBanana browser page with three view modes."""

import os
import sys
import webbrowser
import math
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Lock

import customtkinter as ctk
from modules.dialogs import askyesno, showerror, showinfo

from modules.catalog_view import (
    CARD,
    COMPACT,
    DETAILED,
    VIEW_MODE_ORDER,
    OnlineCatalogState,
    fit_card_text,
    is_sensitive,
    normalize_view_mode,
    remote_image_cache_key,
)
from modules.config import ConfigManager, get_gb_cache_dir
from modules.ai_translate import get_ai_api_key, translate_text
from modules.gamebanana import (
    ALLOWED_MODELS,
    GameBananaClient,
    RemoteDetails,
)
from modules.gb_category_i18n import DEFAULT_URL as GB_CATEGORY_I18N_DEFAULT_URL
from modules.gb_category_i18n import GBCategoryI18n
from modules.i18n import get_i18n, t


DETAILED_PREVIEW = (150, 84)
COMPACT_PREVIEW = (85, 48)
# 与本地卡片同一规格：宽 256、间距 4、16:9 预览。
CARD_WIDTH = 256
CARD_GAP = 4
IMAGE_CACHE_MAX = 256


def card_preview_size(card_width, dpi_scale=1.0):
    """与本地卡片同一套 16:9 预览尺寸公式。

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


def blur_thumbnail(hide_sensitive, item):
    """敏感内容开启且条目敏感时才模糊缩略图。"""
    return bool(hide_sensitive) and is_sensitive(item)


def online_card_columns(measured_width, card_width=CARD_WIDTH,
                        gap=CARD_GAP, dpi_scale=1.0):
    available_width = max(card_width, (measured_width - 24) / dpi_scale)
    return max(
        1,
        int((available_width + gap) // (card_width + gap)),
    )


def category_section_label(model, label_fn):
    """分类所在节的 UI 标签（Mods / 工具 / 声音）。"""
    return {
        "Mod": label_fn("online.section_mods", "Mods"),
        "Tool": label_fn("online.section_tools", "工具"),
        "Sound": label_fn("online.section_sounds", "声音"),
    }.get(model, model)


def category_menu_label(category_id, name, translate_fn):
    """分类菜单项标签：翻译名，缺失时回退英文原文。"""
    return translate_fn(category_id, name)


# 分类按钮宽度
CATEGORY_BUTTON_WIDTH = 220
# 分类树最大展开深度（级 0 节不计入；正常树远达不到，防御异常数据）
MAX_CATEGORY_DEPTH = 8

# 皮肤→干员/武器 的下一级（具体干员名/具体武器名）为最细一级，直接渲染为
# 叶子菜单项，悬停不再发 SubCategories 请求检测下一级。
LEAF_CHILD_CATEGORY_IDS = {42770, 42772}

# 静态分类骨架（数据来自 GameBanana 游戏 21842 真实接口）：
# (category_id, 英文原名, children_dynamic)。除「皮肤」的子分类会随游戏更新
# 变化外，其余各级均稳定；显示名仍走 gb_category_names.json 翻译。
STATIC_CATEGORY_TREE = {
    "Mod": [
        (35464, "Skins", True),
        (42706, "UI", False),
        (42780, "Other/Misc", False),
    ],
    "Tool": [
        (1990, "Other/Misc", False),
        (2258, "Blender Plugins", False),
        (2257, "Import Tools", False),
    ],
    "Sound": [
        (6252, "Other/Misc", False),
    ],
}


class OnlineBrowserFrame(ctk.CTkFrame):
    def __init__(self, master, root, on_install):
        super().__init__(master, fg_color=("gray95", "gray14"))
        self.root = root
        self.on_install = on_install
        self.client = GameBananaClient(
            cache_dir=get_gb_cache_dir(),
            proxy=ConfigManager.get_proxy() or None)
        self.state = OnlineCatalogState(
            view_mode=normalize_view_mode(
                ConfigManager.get_view_mode("online"), default=DETAILED))
        self._hide_sensitive = ConfigManager.get_hide_sensitive_content()
        self._gb_i18n = GBCategoryI18n(
            url=ConfigManager.get_gb_category_i18n_url()
            or GB_CATEGORY_I18N_DEFAULT_URL)
        self._category_nodes = {}
        self._category_path = []
        self._category_menus = []
        self._submenu_by_node = {}
        self._submenu_paths = {}
        self._category_menu_root = None
        self._category_popup_active = False
        self._popup_refresh_job = None
        self._popup_refresh_epoch = 0
        self._preloading = False
        self._preload_pending = 0
        self._preload_completed = False
        self._preload_had_error = False
        self._updating_labels = False
        self._pending_reload = False
        self._pending_force = False
        self._destroyed = False
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="online-worker")
        self._futures = set()
        self._futures_lock = Lock()
        self._image_cache = OrderedDict()
        self._image_pending = {}
        self._item_widgets = {}
        self._images = {}
        self._card_columns = None
        self._card_area_width = 0
        self._card_watch_job = None
        self._dpi_scale = 1.0
        try:
            if os.name == "nt":
                import ctypes
                hdc = ctypes.windll.user32.GetDC(0)
                if hdc:
                    dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
                    ctypes.windll.user32.ReleaseDC(0, hdc)
                    if dpi and dpi > 0:
                        self._dpi_scale = max(0.8, min(dpi / 96.0, 3.0))
        except Exception:
            pass
        self._build()
        self._seed_static_categories()

    # ============================================================
    # UI 构建
    # ============================================================
    def _view_mode_labels(self):
        return {
            COMPACT: t("toolbar.view_compact", "☷ 紧凑列表"),
            CARD: t("toolbar.view_card", "▦ 卡片"),
            DETAILED: t("toolbar.view_detailed", "☰ 详情列表"),
        }

    def _build(self):
        controls = ctk.CTkFrame(self, fg_color=("gray90", "gray17"))
        controls.pack(fill="x", padx=0, pady=0)

        row1 = ctk.CTkFrame(controls, fg_color="transparent")
        row1.pack(fill="x", padx=0, pady=(8, 8))

        self.search = ctk.CTkEntry(
            row1,
            placeholder_text=t("online.search_placeholder", "搜索 GameBanana Mod..."),
            width=320,
        )
        self.search.pack(side="left", padx=(12, 6))
        self.search.bind("<Return>", lambda _event: self.reload())

        self.search_button = ctk.CTkButton(
            row1, text=t("online.search", "搜索"), width=70,
            command=self.reload,
        )
        self.search_button.pack(side="left", padx=4)

        self._sort_labels = {
            "popular": t("online.popular", "🔥 热门"),
            "recent": t("online.recent", "🕐 最新"),
        }
        self.sort_button = ctk.CTkSegmentedButton(
            row1, width=170, command=self._sort_changed,
        )
        self._update_sort_button_labels()
        self.sort_button.pack(side="left", padx=6)

        ctk.CTkLabel(
            row1, text=t("online.category", "分类"),
        ).pack(side="left", padx=(12, 6))
        self.category_button = ctk.CTkButton(
            row1, text=self._category_button_text(),
            width=CATEGORY_BUTTON_WIDTH,
            command=self._show_category_popup,
        )
        self.category_button.pack(side="left", padx=4)

        self.update_labels_button = ctk.CTkButton(
            row1, text=t("online.update_category_labels", "更新分类翻译"),
            width=110, command=self._update_category_labels,
        )
        self.update_labels_button.pack(side="left", padx=(4, 6))

        self.refresh_button = ctk.CTkButton(
            row1, text=t("online.refresh", "刷新"), width=70,
            command=self._refresh_preserving_filters,
        )
        self.refresh_button.pack(side="left", padx=(6, 12))

        row2 = ctk.CTkFrame(controls, fg_color="transparent")
        row2.pack(fill="x", padx=0, pady=(0, 8))

        self._hide_sensitive_var = ctk.BooleanVar(value=self._hide_sensitive)
        self.hide_sensitive_switch = ctk.CTkSwitch(
            row2,
            text=t("online.hide_sensitive", "隐藏敏感内容"),
            variable=self._hide_sensitive_var,
            onvalue=True, offvalue=False,
            command=self._on_hide_sensitive_toggle,
        )
        self.hide_sensitive_switch.pack(side="right", padx=(8, 12))

        self._view_mode_var = ctk.StringVar(value=self.state.view_mode)
        self._view_switch = ctk.CTkSegmentedButton(
            row2,
            values=list(VIEW_MODE_ORDER),
            variable=self._view_mode_var,
            command=self._on_view_mode_change,
            width=220, height=28,
        )
        self._view_switch.pack(side="right", padx=(6, 8))

        self.status = ctk.CTkLabel(
            self, text=t("online.ready", "搜索或浏览 GameBanana"),
            text_color="gray",
        )
        self.status.pack(fill="x", padx=14, pady=(8, 2), anchor="w")
        self.scroll = ctk.CTkScrollableFrame(self, label_text="")
        self.scroll.pack(fill="both", expand=True, padx=8, pady=4)
        self.more = ctk.CTkButton(
            self, text=t("online.more", "加载更多"), command=self.load_more)
        self.more.pack(pady=(2, 10))
        self._update_view_switch_labels()
        self._more_button_state()
        self._card_watch_job = self.root.after(150, self._watch_card_area)

    def _update_sort_button_labels(self):
        """分段切换按钮：最新/热门，与 Patreon 页同一套 UI。"""
        labels = self._sort_labels
        self.sort_button.configure(
            values=[labels["recent"], labels["popular"]])
        self.sort_button.set(labels[self.state.sort])

    def _category_button_text(self):
        """分类按钮文案：当前选择面包屑 + 下拉提示标识。"""
        return self._breadcrumb_text() + "  ▾"

    def _update_view_switch_labels(self):
        labels = self._view_mode_labels()
        self._view_switch.configure(
            values=[labels[mode] for mode in VIEW_MODE_ORDER])
        self._view_mode_var.set(labels[self.state.view_mode])

    def apply_language(self):
        labels = self._view_mode_labels()
        self._view_switch.configure(
            values=[labels[mode] for mode in VIEW_MODE_ORDER])
        self._view_mode_var.set(labels[self.state.view_mode])
        self.search.configure(
            placeholder_text=t("online.search_placeholder", "搜索 GameBanana Mod..."))
        self.search_button.configure(text=t("online.search", "搜索"))
        self.refresh_button.configure(text=t("online.refresh", "刷新"))
        self.more.configure(text=t("online.more", "加载更多"))
        self.hide_sensitive_switch.configure(
            text=t("online.hide_sensitive", "隐藏敏感内容"))
        self._sort_labels = {
            "popular": t("online.popular", "🔥 热门"),
            "recent": t("online.recent", "🕐 最新"),
        }
        self._update_sort_button_labels()
        self.update_labels_button.configure(
            text=t("online.update_category_labels", "更新分类翻译"))
        self._rebuild_category_ui()
        self._update_status_idle()

    def _on_view_mode_change(self, selected_label):
        labels = self._view_mode_labels()
        by_label = {label: mode for mode, label in labels.items()}
        mode = by_label.get(selected_label)
        if mode is None or mode == self.state.view_mode:
            return
        self.state.view_mode = mode
        ConfigManager.set_view_mode("online", mode)
        self._rerender()

    def _on_hide_sensitive_toggle(self):
        self._hide_sensitive = bool(self._hide_sensitive_var.get())
        ConfigManager.set_hide_sensitive_content(self._hide_sensitive)
        self._rerender()

    def _sort_changed(self, selected_label):
        by_label = {label: key for key, label in self._sort_labels.items()}
        sort = by_label.get(selected_label, self.state.sort)
        if sort == self.state.sort:
            return
        self.state.sort = sort
        self.reload()

    # ============================================================
    # 分类级联筛选（单按钮 + 原生级联菜单，任意深度懒加载）
    # ============================================================
    def _category_label(self, model, name, category_id):
        lang = get_i18n().effective_lang
        return category_menu_label(
            category_id, name,
            lambda cid, raw: self._gb_i18n.translate(cid, raw, lang))

    def _node_label(self, node):
        if node["id"] is None:
            return category_section_label(node["model"], t)
        return self._category_label(
            node["model"], node["name"], node["id"])

    def _make_popup_menu(self):
        import tkinter as tk
        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#2b2b2b", fg="#e0e0e0",
            activebackground="#3B8ED0", activeforeground="white",
            font=("Microsoft YaHei UI", max(8, int(11 * self._dpi_scale))),
            bd=1, relief="flat",
        )
        self._category_menus.append(menu)
        return menu

    def _destroy_category_menus(self):
        for menu in self._category_menus:
            try:
                menu.destroy()
            except Exception:
                pass
        self._category_menus.clear()
        self._category_menu_root = None
        self._submenu_by_node.clear()
        self._submenu_paths.clear()

    def _show_category_popup(self):
        if self._destroyed:
            return
        try:
            if not self.category_button.winfo_exists():
                return
        except Exception:
            return
        self._destroy_category_menus()
        root = self._make_popup_menu()
        self._category_menu_root = root
        self._populate_root_menu(root)
        self._category_popup_active = True
        self._popup_refresh_epoch += 1
        try:
            root.tk_popup(
                self.category_button.winfo_rootx(),
                self.category_button.winfo_rooty()
                + self.category_button.winfo_height(),
            )
        finally:
            self._category_popup_active = False
            try:
                root.grab_release()
            except Exception:
                pass

    def _populate_root_menu(self, root):
        root.add_command(
            label=t("online.all", "全部"),
            command=lambda: self._set_category_selection([]))
        for index, node in enumerate(self._category_path):
            root.add_command(
                label=self._node_label(node),
                command=lambda k=index + 1: self._set_category_selection(
                    list(self._category_path[:k])))
        current = self._category_path[-1] if self._category_path else None
        if current is None:
            root.add_separator()
            for model in ALLOWED_MODELS:
                node = self._ensure_node((model, None))
                self._add_child_entry(root, node, [node])
        else:
            children = sorted(
                current["children"].values(),
                key=lambda item: item["name"].casefold())
            if children:
                root.add_separator()
            for child in children:
                self._add_child_entry(
                    root, child, self._category_path + [child])

    def _add_child_entry(self, parent_menu, node, node_path):
        if len(node_path) > MAX_CATEGORY_DEPTH:
            parent_menu.add_command(
                label=self._node_label(node),
                command=lambda: self._set_category_selection(node_path))
            return
        # 仅骨架静态叶子直接作为命令项；动态节点（API 返回）不信任 has_children：
        # SubCategories 响应不含 _nCategoryCount，干员/武器等深层分类会因此
        # 误判为叶子，必须一律建级联并懒加载（加载后确认为空再降级为命令项）。
        # 例外：干员/武器（LEAF_CHILD_CATEGORY_IDS）的下一级为具体干员名/
        # 具体武器名，已在 _as_child_node 标记为静态叶子，直接作为命令项。
        if not node.get("has_children") and node.get("static_children"):
            parent_menu.add_command(
                label=self._node_label(node),
                command=lambda: self._set_category_selection(node_path))
            return
        if node["children_loaded"] and not node["children"]:
            parent_menu.add_command(
                label=self._node_label(node),
                command=lambda: self._set_category_selection(node_path))
            return
        sub = self._make_popup_menu()
        node_key = node["key"]
        self._submenu_by_node[node_key] = sub
        self._submenu_paths[node_key] = node_path
        sub.configure(
            postcommand=lambda n=node, s=sub: self._ensure_submenu_loaded(n, s))
        self._repopulate_submenu(node, sub, node_path)
        parent_menu.add_cascade(label=self._node_label(node), menu=sub)

    def _repopulate_submenu(self, node, sub, node_path):
        self._destroy_subtree_menus(node)
        sub.delete(0, "end")
        if node["children_loading"]:
            sub.add_command(
                label=t("online.loading_categories", "正在加载分类..."),
                state="disabled")
            return
        if node.get("load_error"):
            sub.add_command(
                label=t("online.load_failed", "（加载失败）"),
                state="disabled")
            return
        if not node["children_loaded"]:
            sub.add_command(
                label=t("online.loading_categories", "正在加载分类..."),
                state="disabled")
            return
        sub.add_command(
            label=t("online.select_this_category",
                    "选择「{name}」").format(name=self._node_label(node)),
            command=lambda: self._set_category_selection(node_path))
        sub.add_separator()
        children = sorted(
            node["children"].values(),
            key=lambda item: item["name"].casefold())
        if not children:
            sub.add_command(
                label=t("online.no_subcategories", "（无子分类）"),
                state="disabled")
            return
        for child in children:
            self._add_child_entry(sub, child, node_path + [child])

    def _destroy_subtree_menus(self, node):
        """销毁 node 子树下所有子菜单并清理索引（重填前的孤儿回收）。"""
        doomed = []
        for key, path in self._submenu_paths.items():
            if any(ancestor is node for ancestor in path[:-1]):
                doomed.append(key)
        for key in doomed:
            old = self._submenu_by_node.pop(key, None)
            self._submenu_paths.pop(key, None)
            if old is None:
                continue
            try:
                old.destroy()
            except Exception:
                pass
            try:
                self._category_menus.remove(old)
            except ValueError:
                pass

    def _ensure_submenu_loaded(self, node, sub):
        if self._destroyed:
            return
        if node.get("load_error"):
            path = self._submenu_paths.get(node["key"])
            if path is not None:
                try:
                    self._repopulate_submenu(node, sub, path)
                except Exception:
                    pass
        if not node["children_loaded"]:
            self._load_children(node)
            return
        node_key = node["key"]
        path = self._submenu_paths.get(node_key)
        if path is not None:
            self._repopulate_submenu(node, sub, path)

    def _refresh_submenu_of(self, node):
        if self._category_popup_active:
            return
        node_key = node["key"]
        sub = self._submenu_by_node.get(node_key)
        path = self._submenu_paths.get(node_key)
        if sub is None or path is None:
            return
        try:
            self._repopulate_submenu(node, sub, path)
        except Exception:
            pass

    def _schedule_popup_refresh(self):
        """子分类加载成功后，若菜单仍打开，防抖地原位刷新。

        Windows 上 TrackPopupMenu 是模态的：绝不嵌套 tk_popup，必须先把
        旧弹出完整关闭（unpost 并等待旧 tk_popup 返回）再重新弹出。
        """
        if self._destroyed or not self._category_popup_active:
            return
        if self._popup_refresh_job is not None:
            try:
                self.root.after_cancel(self._popup_refresh_job)
            except Exception:
                pass
        epoch = self._popup_refresh_epoch
        try:
            self._popup_refresh_job = self.root.after(
                80, lambda: self._popup_refresh_go(epoch))
        except Exception:
            self._popup_refresh_job = None

    def _popup_refresh_go(self, epoch):
        self._popup_refresh_job = None
        if self._destroyed or not self._category_popup_active:
            return
        if epoch != self._popup_refresh_epoch:
            return
        root_menu = self._category_menu_root
        if root_menu is not None:
            try:
                if root_menu.winfo_exists():
                    root_menu.unpost()
            except Exception:
                pass
            try:
                root_menu.grab_release()
            except Exception:
                pass
        self._popup_refresh_epoch += 1
        self._poll_reopen(self._popup_refresh_epoch, 0)

    def _poll_reopen(self, epoch, tries):
        if self._destroyed or tries > 50:
            return
        if self._category_popup_active:
            try:
                self.root.after(
                    10, lambda: self._poll_reopen(epoch, tries + 1))
            except Exception:
                pass
            return
        if epoch != self._popup_refresh_epoch:
            return
        try:
            self._popup_refresh_job = self.root.after(
                0, lambda: self._reopen_popup(epoch))
        except Exception:
            self._popup_refresh_job = None

    def _reopen_popup(self, epoch):
        self._popup_refresh_job = None
        if self._destroyed or self._category_popup_active:
            return
        if epoch != self._popup_refresh_epoch:
            return
        self._show_category_popup()

    def _breadcrumb_text(self):
        if not self._category_path:
            return t("online.all", "全部")
        return " › ".join(
            self._node_label(node) for node in self._category_path)

    def _set_category_selection(self, path):
        category = None
        if path:
            category = (path[-1]["model"], path[-1]["id"])
        self._category_path = list(path)
        try:
            self.category_button.configure(text=self._category_button_text())
        except Exception:
            pass
        if category != self.state.category:
            self.state.category = category
            self.reload()

    def _rebuild_category_ui(self):
        """语言切换后按当前路径重建按钮文案（菜单下次打开时重建）。"""
        try:
            if not self._preloading:
                self.category_button.configure(text=self._category_button_text())
        except Exception:
            pass

    def _make_node(self, model, category_id, name="", has_children=False):
        return {
            "model": model, "id": category_id, "name": name,
            "key": (model, category_id),
            "children": {}, "children_loaded": False,
            "children_loading": False, "load_error": None,
            "has_children": bool(has_children),
            "static_children": False,
        }

    def _seed_static_categories(self):
        """按内置骨架预置节与根分类节点：稳定部分零等待，皮肤留作动态。"""
        for model in ALLOWED_MODELS:
            section = self._ensure_node((model, None))
            section["has_children"] = True
            section["children_loaded"] = True
            section["static_children"] = True
            for category_id, raw_name, dynamic in \
                    STATIC_CATEGORY_TREE.get(model, []):
                child = self._ensure_node((model, category_id))
                child["name"] = raw_name
                child["has_children"] = bool(dynamic)
                child["static_children"] = not dynamic
                if not dynamic:
                    child["children_loaded"] = True
                section["children"][category_id] = child

    def begin_preload(self):
        """进入在线页时后台预加载分类数据；期间分类按钮置灰显示加载中。

        预载内容：三节根分类（静默合并）+ 皮肤子分类 + 干员/武器下一级。
        完成后按钮恢复可点；失败也恢复（悬停懒加载兜底，下次进入重试）。
        """
        if self._destroyed:
            return
        if self._preloading:
            return
        if self._preload_completed and not self._preload_had_error:
            self._set_category_button_ready()
            return
        self._preloading = True
        self._preload_pending = 0
        self._preload_had_error = False
        try:
            self.category_button.configure(
                state="disabled",
                text=t("online.loading_categories", "正在加载分类..."))
        except Exception:
            pass
        for model in ALLOWED_MODELS:
            node = self._category_nodes.get((model, None))
            if node is not None and not node.get("merging_roots"):
                self._preload_pending += 1
                self._merge_roots_async(
                    node, force=False, on_done=self._preload_task_done)
        section = self._category_nodes.get(("Mod", None))
        if section is not None:
            skins = section["children"].get(35464)
            if skins is not None \
                    and not skins["children_loaded"] \
                    and not skins["children_loading"]:
                self._preload_pending += 1
                self._load_children(
                    skins, quiet=True, on_done=self._preload_task_done)
        for category_id in (42770, 42771, 42772, 42778, 42779):
            node = self._ensure_node(("Mod", category_id))
            if not node["children_loaded"] \
                    and not node["children_loading"]:
                self._preload_pending += 1
                self._load_children(
                    node, quiet=True, on_done=self._preload_task_done)
        self._preload_finish_if_idle()

    def _preload_task_done(self, error):
        if error:
            self._preload_had_error = True
        self._preload_pending -= 1
        if self._preload_pending > 0:
            return
        self._preloading = False
        self._preload_completed = True
        self._set_category_button_ready()

    def _preload_finish_if_idle(self):
        if self._preloading and self._preload_pending == 0:
            self._preloading = False
            self._preload_completed = True
            self._set_category_button_ready()

    def _set_category_button_ready(self):
        try:
            self.category_button.configure(
                state="normal", text=self._category_button_text())
        except Exception:
            pass

    def _ensure_node(self, selection):
        """为节/分类选择取节点；首次访问（含失败后重试）时创建。"""
        if not selection:
            return None
        node = self._category_nodes.get(selection)
        if node is not None:
            return node
        model, category_id = selection
        node = self._make_node(model, category_id)
        self._category_nodes[selection] = node
        return node

    def _load_children(self, node, quiet=False, on_done=None):
        if node.get("children_loaded") or node.get("children_loading"):
            return
        node["children_loading"] = True
        node["load_error"] = None
        self._refresh_submenu_of(node)
        model, category_id = node["model"], node["id"]
        if category_id is None:
            future = self._executor.submit(self.client.categories, model)
        else:
            future = self._executor.submit(
                self.client.subcategories, model, category_id)
        self._track_future(future)

        def completed(done):
            try:
                children = done.result()
                error = None
            except Exception as exc:
                children = []
                error = str(exc)
            self._post(self._on_children_loaded, node, children, error,
                       quiet, on_done)

        future.add_done_callback(completed)

    def _as_child_node(self, cat, parent_id):
        """把 API 返回的子分类构建为菜单节点。

        干员/武器（LEAF_CHILD_CATEGORY_IDS）的下一级为最细一级：直接标记为
        静态叶子，_add_child_entry 将渲染为命令项，悬停不再触发懒加载请求。
        """
        key = (cat.model, cat.category_id)
        child = self._ensure_node(key)
        child["name"] = cat.name
        child["model"] = cat.model
        child["id"] = cat.category_id
        child["has_children"] = bool(getattr(cat, "has_children", False))
        if child.get("static_children"):
            child["children_loaded"] = False
            child["children"] = {}
        if parent_id in LEAF_CHILD_CATEGORY_IDS:
            child["has_children"] = False
            child["children_loaded"] = True
            child["static_children"] = True
        else:
            child["static_children"] = False
        return child

    def _on_children_loaded(self, node, children, error, quiet=False,
                            on_done=None):
        if self._destroyed:
            return
        node["children_loading"] = False
        node["load_error"] = error or None
        if error:
            node["children_loaded"] = False
            if not quiet:
                self.status.configure(
                    text=t("online.categories_error",
                           "分类加载失败：{error}").format(error=error))
            # 失败不自动重弹：避免「悬停→失败→重弹→再悬停→再失败」死循环；
            # 子菜单显示（加载失败），重新悬停即重试。
            self._refresh_submenu_of(node)
            if on_done is not None:
                on_done(error)
            return
        node["children_loaded"] = True
        new_children = {}
        for cat in children:
            new_children[cat.category_id] = self._as_child_node(cat, node["id"])
        node["children"] = new_children
        self._refresh_submenu_of(node)
        if not quiet and node["key"] in self._submenu_by_node:
            self._schedule_popup_refresh()
        if on_done is not None:
            on_done(None)

    def _refresh_category_branch(self):
        """刷新时后台强制重拉当前分类路径（保留选择）。

        节 → 静默合并新根分类；稳定叶子 → 跳过；动态分支（皮肤等）→ 强制重拉子分类。
        """
        for node in self._category_path:
            if node.get("children_loading"):
                continue
            if node["id"] is None:
                self._merge_roots_async(node, force=True)
                continue
            if node.get("static_children"):
                continue
            node["children_loading"] = True
            node["load_error"] = None
            self._refresh_submenu_of(node)
            model, category_id = node["model"], node["id"]
            future = self._executor.submit(
                self.client.subcategories, model, category_id, force=True)
            self._track_future(future)

            def completed(done, n=node):
                try:
                    children = done.result()
                    error = None
                except Exception as exc:
                    children = []
                    error = str(exc)
                self._post(self._on_children_loaded, n, children, error)

            future.add_done_callback(completed)

    def _merge_roots(self, node, roots):
        """把新根分类静默追加到节节点末尾（不动静态项顺序）。"""
        if node is None:
            return
        for cat in roots:
            if cat.category_id in node["children"]:
                continue
            node["children"][cat.category_id] = self._as_child_node(cat, node["id"])
        self._refresh_submenu_of(node)

    def _merge_roots_async(self, node, force=False, on_done=None):
        """后台拉取某节的根分类并静默合并；失败忽略，重复合并去重。"""
        if node is None or node.get("merging_roots"):
            return
        node["merging_roots"] = True
        model = node["model"]
        future = self._executor.submit(
            self.client.categories, model, force=force)
        self._track_future(future)

        def completed(done, n=node):
            try:
                roots = done.result()
                error = None
            except Exception as exc:
                roots = []
                error = str(exc)
            self._post(self._on_roots_fetched, n, roots, error, on_done)

        future.add_done_callback(completed)

    def _on_roots_fetched(self, node, roots, error, on_done=None):
        if self._destroyed:
            return
        node["merging_roots"] = False
        if error:
            if on_done is not None:
                on_done(error)
            return
        self._merge_roots(node, roots)
        if on_done is not None:
            on_done(None)

    def _refresh_preserving_filters(self):
        """刷新：保留搜索词与分类筛选，强制重拉列表与当前分类分支。"""
        self.reload(True)
        self._refresh_category_branch()

    # ============================================================
    # 分类名翻译热更新（仅手动触发）
    # ============================================================
    def _update_category_labels(self):
        if self._updating_labels:
            return
        self._updating_labels = True
        self.update_labels_button.configure(state="disabled")
        self.status.configure(
            text=t("online.updating_category_labels", "正在更新分类翻译..."))
        future = self._executor.submit(self._gb_i18n.refresh)
        self._track_future(future)

        def completed(done):
            try:
                error = done.result()
            except Exception as exc:
                error = str(exc)
            self._post(self._on_category_labels_updated, error)

        future.add_done_callback(completed)

    def _on_category_labels_updated(self, error):
        if self._destroyed:
            return
        self._updating_labels = False
        self.update_labels_button.configure(state="normal")
        if error:
            self.status.configure(
                text=t("online.category_labels_failed",
                       "分类翻译更新失败：{error}").format(error=error))
        else:
            self.status.configure(
                text=t("online.category_labels_updated", "分类翻译已更新"))
        self._rebuild_category_ui()

    # ============================================================
    # 浏览请求（快照驱动，successful_page 只在成功后递增）
    # ============================================================
    def reload(self, force=False):
        if self.state.loading:
            self._pending_reload = True
            self._pending_force = bool(force)
            self.state.request_generation += 1
            return
        self._pending_reload = False
        self._pending_force = False
        query = self.search.get().strip()
        generation = self.state.begin_search(
            query, self.state.sort, self.state.category)
        self._request(generation, force=force)

    def load_more(self):
        if self.state.loading or not self.state.has_next:
            return
        generation = self.state.request_generation
        snapshot = (
            generation, self.state.next_page,
            self.state.query, self.state.sort, self.state.category, False, False,
        )
        self._begin_request(snapshot)

    def _request(self, generation, force=False):
        snapshot = (
            generation, self.state.next_page,
            self.state.query, self.state.sort, self.state.category, force, True,
        )
        self._begin_request(snapshot)

    def _begin_request(self, snapshot):
        generation, _page, _query, _sort, _category, _force, _clear = snapshot
        self.state.loading = True
        self.status.configure(text=t("online.loading", "正在加载 GameBanana..."))
        self._more_button_state()
        future = self._executor.submit(self._fetch_browse, snapshot)
        self._track_future(future)

        def completed(done):
            try:
                result = done.result()
                error = None
            except Exception as exc:
                result = None
                error = str(exc)
            self._post(self._on_page_result, snapshot, result, error)

        future.add_done_callback(completed)

    def _fetch_browse(self, snapshot):
        generation, page, query, sort, category, force, _clear = snapshot
        return self.client.browse(page, query=query, sort=sort,
                                  category=category, force=force)

    def _on_page_result(self, snapshot, page, error):
        generation, requested_page, _query, _sort, _category, _force, _clear = snapshot
        if self._destroyed:
            return
        if generation != self.state.request_generation:
            if self._pending_reload:
                self._pending_reload = False
                self.state.loading = False
                self.reload(force=self._pending_force)
            return
        self.state.loading = False
        if error:
            self.status.configure(
                text=t("online.error", "在线加载失败：{error}").format(error=error))
            self._more_button_state()
            return
        self.state.accept_page(generation, page)
        self._rerender()
        self._update_status_idle()
        self._more_button_state()

    def _more_button_state(self):
        if self.state.loading:
            self.more.configure(state="disabled")
        else:
            self.more.configure(
                state="normal" if self.state.has_next else "disabled")

    def _update_status_idle(self):
        if self.state.loading:
            self.status.configure(
                text=t("online.loading", "正在加载 GameBanana..."))
        elif self.state.items:
            self.status.configure(
                text=t("online.result_count", "显示 {shown} / {total} 个结果").format(
                    shown=len(self.state.items), total=self.state.record_count))
        else:
            self.status.configure(
                text=t("online.ready", "搜索或浏览 GameBanana"))

    # ============================================================
    # 渲染：三种布局共享同一个累计结果集
    # ============================================================
    def _render_item_title(self, item):
        title = item.name
        if is_sensitive(item):
            title = t("online.sensitive_prefix", "[敏感] ") + title
        return title

    def _render_item_detailed(self, item):
        card = ctk.CTkFrame(self.scroll, corner_radius=8)
        card.pack(fill="x", padx=4, pady=4)
        self._item_widgets[item.id] = card

        title = self._render_item_title(item)
        image = item.images[0] if item.images else None
        if image:
            label = ctk.CTkLabel(
                card, text=t("online.preview", "预览"),
                width=DETAILED_PREVIEW[0], height=DETAILED_PREVIEW[1],
            )
            label.pack(side="left", padx=8, pady=8)
            self._load_image(
                image.thumbnail_url, DETAILED_PREVIEW,
                blur_thumbnail(self._hide_sensitive, item),
                label, ("browse", self.state.request_generation, item.id),
                fit=False,
            )
        else:
            placeholder = ctk.CTkLabel(
                card, text=f"▧\n{t('online.preview', '预览')}",
                width=DETAILED_PREVIEW[0], height=DETAILED_PREVIEW[1],
                text_color=("gray48", "gray55"),
                fg_color=("gray84", "gray19"),
            )
            placeholder.pack(side="left", padx=8, pady=8)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        ctk.CTkLabel(
            info, text=title, anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(fill="x")
        ctk.CTkLabel(
            info,
            text="{}  |  {}  |  {}".format(
                item.author.name if item.author else t("online.unknown_author", "未知作者"),
                item.category or "-", item.version or "-"),
            anchor="w", text_color="gray",
        ).pack(fill="x", pady=(4, 0))
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(side="right", padx=10, pady=8)
        ctk.CTkButton(
            buttons, text=t("online.details", "详情"), width=70,
            command=lambda i=item.id: self.show_details(i),
        ).pack(pady=3)

    def _render_item_compact(self, item):
        row = ctk.CTkFrame(self.scroll, corner_radius=6, height=60)
        row.pack(fill="x", padx=4, pady=3)
        row.pack_propagate(False)
        self._item_widgets[item.id] = row

        title = self._render_item_title(item)
        image = item.images[0] if item.images else None
        if image:
            label = ctk.CTkLabel(
                row, text=t("online.preview", "预览"),
                width=COMPACT_PREVIEW[0], height=COMPACT_PREVIEW[1],
            )
            label.pack(side="left", padx=(8, 6), pady=7)
            self._load_image(
                image.thumbnail_url, COMPACT_PREVIEW,
                blur_thumbnail(self._hide_sensitive, item),
                label, ("browse", self.state.request_generation, item.id),
                fit=False,
            )
        else:
            placeholder = ctk.CTkLabel(
                row, text=f"▧\n{t('online.preview', '预览')}",
                width=COMPACT_PREVIEW[0], height=COMPACT_PREVIEW[1],
                text_color=("gray48", "gray55"),
                fg_color=("gray84", "gray19"),
            )
            placeholder.pack(side="left", padx=(8, 6), pady=7)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(4, 8))
        ctk.CTkLabel(
            info, text=title, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(fill="x")
        ctk.CTkLabel(
            info,
            text="{}  |  {}  |  {}".format(
                item.author.name if item.author else t("online.unknown_author", "未知作者"),
                item.category or "-", item.version or "-"),
            anchor="w", text_color="gray",
        ).pack(fill="x")
        ctk.CTkButton(
            row, text=t("online.details", "详情"), width=70,
            command=lambda i=item.id: self.show_details(i),
        ).pack(side="right", padx=10, pady=14)

    def _render_item_card(self, item, grid, index, columns, card_width):
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
        self._item_widgets[item.id] = card

        title = self._render_item_title(item)
        image_size, display_image_size, preview_height = card_preview_size(
            card_width, self._dpi_scale)
        image = item.images[0] if item.images else None
        if image:
            preview = ctk.CTkLabel(
                card, text="", width=display_image_size[0],
                height=preview_height, fg_color=("gray84", "gray19"),
                corner_radius=7,
            )
            self._load_image(
                image.thumbnail_url, display_image_size,
                blur_thumbnail(self._hide_sensitive, item),
                preview, ("browse", self.state.request_generation, item.id),
                fit=True, source_size=image_size,
            )
        else:
            preview = ctk.CTkLabel(
                card, text=f"▧\n{t('online.preview', '预览')}",
                width=display_image_size[0], height=preview_height,
                text_color=("gray48", "gray55"),
                fg_color=("gray84", "gray19"), corner_radius=7,
            )
        preview.pack(fill="x", padx=6, pady=(6, 0))

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(fill="both", expand=True, padx=10, pady=(8, 8))

        title_font = ctk.CTkFont(size=12, weight="bold")
        text_width = max(
            80, round((card_width - 50) / self._dpi_scale) - 4)
        fitted_title = fit_card_text(title, title_font, text_width)
        title_container = ctk.CTkFrame(
            info, width=1, height=40, fg_color="transparent")
        title_container.pack(fill="x")
        title_container.pack_propagate(False)
        title_label = ctk.CTkLabel(
            title_container, text=fitted_title,
            font=title_font, anchor="w", justify="left",
        )
        title_label.place(x=0, y=0, relwidth=1, relheight=1)

        meta_text = "{}  |  {}  |  {}".format(
            item.author.name if item.author else t("online.unknown_author", "未知作者"),
            item.category or "-", item.version or "-")
        meta_font = ctk.CTkFont(size=9)
        fitted_meta = fit_card_text(meta_text, meta_font, text_width)
        meta_container = ctk.CTkFrame(
            info, width=1, height=18, fg_color="transparent")
        meta_container.pack(fill="x", pady=(2, 0))
        meta_container.pack_propagate(False)
        meta_label = ctk.CTkLabel(
            meta_container, text=fitted_meta,
            font=meta_font, anchor="w", justify="left", text_color="gray",
        )
        meta_label.place(x=0, y=0, relwidth=1, relheight=1)

        ctk.CTkButton(
            info, text=t("online.details", "详情"), width=70, height=28,
            command=lambda i=item.id: self.show_details(i),
        ).pack(pady=(6, 2))
        return card

    def _watch_card_area(self):
        """卡片模式下监听宽度变化，列数改变时重渲染（与本地同一模式）。"""
        self._card_watch_job = None
        try:
            if self._destroyed or not self.root.winfo_exists():
                return
            self.root.update_idletasks()
            canvas = self.scroll._parent_canvas
            width = canvas.winfo_width()
            self._card_area_width = width
            if self.state.view_mode == CARD and self.state.items:
                columns = online_card_columns(
                    width, dpi_scale=self._dpi_scale)
                if columns != self._card_columns:
                    self._card_columns = columns
                    self._rerender()
        except Exception:
            pass
        if not self._destroyed:
            try:
                self._card_watch_job = self.root.after(
                    150, self._watch_card_area)
            except Exception:
                pass

    def _rerender(self):
        anchor = self._capture_anchor()
        for widget in self.scroll.winfo_children():
            widget.destroy()
        self._item_widgets.clear()
        items = self.state.items
        if not items:
            self._restore_anchor(anchor)
            return
        mode = self.state.view_mode
        if mode == COMPACT:
            for item in items:
                self._render_item_compact(item)
        elif mode == CARD:
            try:
                self.root.update_idletasks()
                canvas = self.scroll._parent_canvas
                width = canvas.winfo_width() or 800
            except Exception:
                width = 800
            columns = online_card_columns(width, dpi_scale=self._dpi_scale)
            self._card_columns = columns
            grid = ctk.CTkFrame(
                self.scroll,
                width=columns * (CARD_WIDTH + CARD_GAP),
                fg_color="transparent",
            )
            grid.pack(anchor="n")
            card_pixel_width = round(CARD_WIDTH * self._dpi_scale)
            card_pixel_padding = math.ceil(
                (CARD_GAP // 2) * self._dpi_scale,
            )
            slot_width = card_pixel_width + card_pixel_padding * 2
            for column in range(columns):
                grid.grid_columnconfigure(column, minsize=slot_width)
            cards = []
            for index, item in enumerate(items):
                cards.append(self._render_item_card(
                    item, grid, index, columns, card_pixel_width))
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
        else:
            for item in items:
                self._render_item_detailed(item)
        self._restore_anchor(anchor)

    # ---- 滚动锚点 ----
    def _capture_anchor(self):
        if not self._item_widgets:
            return None
        canvas = self.scroll._parent_canvas
        try:
            canvas_top = canvas.winfo_rooty()
            canvas_height = canvas.winfo_height()
        except Exception:
            return None
        best = None
        for item_id, widget in self._item_widgets.items():
            try:
                if not widget.winfo_exists() or not widget.winfo_manager():
                    continue
                delta = widget.winfo_rooty() - canvas_top
            except Exception:
                continue
            if -50 <= delta < canvas_height and (best is None or delta < best[1]):
                best = (item_id, delta)
        return best

    def _restore_anchor(self, anchor):
        if not anchor:
            return
        item_id, offset = anchor
        widget = self._item_widgets.get(item_id)
        if not widget:
            return
        try:
            self.root.update_idletasks()
            canvas = self.scroll._parent_canvas
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
    # 远程图片：有界执行器 + 处理后内存缓存（键含尺寸与模糊策略）
    # ============================================================
    def _load_image(self, url, display_size, blur, label, token,
                    fit=False, source_size=None):
        if self._destroyed:
            return
        key = remote_image_cache_key(url, display_size, blur)
        cached = self._image_cache.get(key)
        if cached is not None:
            self._apply_image(label, cached, token)
            return
        if key in self._image_pending:
            self._image_pending[key].append((label, token))
            return
        self._image_pending[key] = [(label, token)]
        future = self._executor.submit(
            self._fetch_image_worker, url, display_size, blur, fit, source_size)
        self._track_future(future)

        def completed(done):
            try:
                image = done.result()
            except Exception:
                image = None
            self._post(self._on_image_ready, key, display_size, token, image)

        future.add_done_callback(completed)

    def _fetch_image_worker(self, url, display_size, blur, fit, source_size):
        from PIL import Image, ImageFilter, ImageOps
        raw = self.client.fetch_image(url)
        image = Image.open(BytesIO(raw)).convert("RGB")
        if blur:
            image = image.filter(ImageFilter.GaussianBlur(12))
        if fit:
            target = source_size or (
                max(120, round(display_size[0] * self._dpi_scale)),
                max(68, round(display_size[1] * self._dpi_scale)),
            )
            image = ImageOps.fit(image, target, method=Image.LANCZOS)
            image.thumbnail(display_size)
        else:
            image.thumbnail(display_size)
        return image

    def _on_image_ready(self, key, display_size, token, image):
        if self._destroyed:
            return
        targets = self._image_pending.pop(key, [])
        if image is None:
            return
        try:
            ctk_image = ctk.CTkImage(
                light_image=image, dark_image=image, size=image.size)
        except Exception:
            return
        self._image_cache[key] = ctk_image
        while len(self._image_cache) > IMAGE_CACHE_MAX:
            self._image_cache.popitem(last=False)
        self._apply_image(None, ctk_image, token)
        for label, target_token in targets:
            self._apply_image(label, ctk_image, target_token)

    def _apply_image(self, label, ctk_image, token):
        if label is None:
            return
        try:
            if not label.winfo_exists():
                return
        except Exception:
            return
        if token is None:
            pass
        elif token[0] == "browse":
            if token[1] != self.state.request_generation:
                return
            if token[2] not in self.state.item_by_id:
                return
        try:
            label.configure(image=ctk_image, text="")
        except Exception:
            pass

    # ============================================================
    # 详情与安装
    # ============================================================
    def show_details(self, item_id):
        if self._destroyed or self.state.loading:
            return
        if not self.state.begin_details(item_id):
            return
        item = self.state.item_by_id.get(item_id)
        if self._hide_sensitive and item is not None and is_sensitive(item):
            if not askyesno(
                    t("online.sensitive_title", "敏感内容确认"),
                    t("online.sensitive_confirm", "此 Mod 可能包含敏感内容，继续查看详情？"),
                    parent=self.root):
                self.state.finish_details(item_id)
                self._update_status_idle()
                return
        self.status.configure(text=t("online.loading_details", "正在加载 Mod 详情..."))
        item = self.state.item_by_id.get(item_id)
        model = getattr(item, "model", "Mod") if item is not None else "Mod"
        future = self._executor.submit(
            self.client.details, item_id, model=model)
        self._track_future(future)

        def completed(done):
            try:
                details = done.result()
                error = None
            except Exception as exc:
                details = None
                error = str(exc)
            self._post(self._show_details_dialog, details, error, item_id)

        future.add_done_callback(completed)

    def _show_details_dialog(self, details, error, item_id):
        self.state.finish_details(item_id)
        if self._destroyed:
            return
        if error:
            self.status.configure(
                text=t("online.error", "在线加载失败：{error}").format(error=error))
            return
        dialog = ctk.CTkToplevel(self.root, fg_color="black")
        dialog.title(details.name)
        dialog.geometry("760x620")
        dialog.transient(self.root)
        dialog.grab_set()
        body = ctk.CTkScrollableFrame(dialog, label_text="", fg_color="black")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(
            body, text=details.name,
            font=ctk.CTkFont(size=20, weight="bold"), anchor="w",
        ).pack(fill="x", pady=(4, 8))
        if details.author:
            ctk.CTkLabel(
                body,
                text=t("online.author", "作者：{name}").format(name=details.author.name),
                anchor="w", text_color="gray",
            ).pack(fill="x")
        description_text = details.description or ""
        desc_section = ctk.CTkFrame(body, fg_color="transparent")
        desc_section.pack(fill="x", pady=10)
        ctk.CTkLabel(
            desc_section,
            text=description_text or t("online.no_description", "没有描述"),
            anchor="w", justify="left", wraplength=690,
        ).pack(fill="x")
        if description_text.strip():
            desc_actions = ctk.CTkFrame(desc_section, fg_color="transparent")
            desc_actions.pack(anchor="w", pady=(6, 0))
            translate_btn = ctk.CTkButton(
                desc_actions, text=t("ai.translate", "🌐 翻译"),
                width=90, height=26, font=ctk.CTkFont(size=11),
                command=lambda: self._translate_description(
                    dialog, desc_section, translate_btn, description_text))
            translate_btn.pack(side="left")
        if details.images:
            gallery = ctk.CTkScrollableFrame(
                body, label_text=t("online.screenshots", "截图预览"),
                orientation="horizontal", height=220,
                fg_color=("gray95", "gray17"))
            gallery.pack(fill="x", pady=8)
            blur = blur_thumbnail(self._hide_sensitive, details)
            for index, remote_image in enumerate(details.images):
                preview = ctk.CTkLabel(
                    gallery,
                    text=t("online.loading_image", "正在加载..."),
                    text_color="gray",
                    width=300, height=200,
                    fg_color=("gray90", "gray18"), corner_radius=6)
                preview.pack(side="left", padx=4, pady=4)
                preview.bind(
                    "<Button-1>",
                    lambda _event, url=remote_image.url, name=details.name,
                    parent=dialog: self._show_full_image(url, name, parent))
                # 原图等比缩放显示（不裁剪），与 Patreon 详情页同一套表现
                self._load_image(
                    remote_image.url, (300, 200), blur,
                    preview, ("dialog", id(preview)), fit=False)
        if details.unavailable_reason:
            ctk.CTkLabel(
                body,
                text=t("online.unavailable", "此 Mod 不可安装：{reason}").format(
                    reason=details.unavailable_reason),
                text_color="#e3a008", anchor="w",
            ).pack(fill="x", pady=4)
        files_frame = ctk.CTkFrame(body, fg_color="transparent")
        files_frame.pack(fill="x", pady=8)
        for remote_file in details.files:
            self._file_row(files_frame, details, remote_file, dialog)
        if details.archived_files:
            archived_frame = ctk.CTkFrame(body, fg_color="transparent")
            for remote_file in details.archived_files:
                self._file_row(archived_frame, details, remote_file, dialog)

            def toggle_archived():
                if archived_frame.winfo_manager():
                    archived_frame.pack_forget()
                else:
                    archived_frame.pack(fill="x")

            ctk.CTkButton(
                body,
                text=t("online.archived", "历史文件（已归档）") +
                     " ({})".format(len(details.archived_files)),
                anchor="w", fg_color=("gray75", "gray25"),
                command=toggle_archived,
            ).pack(fill="x", pady=(12, 4))
        if details.profile_url:
            ctk.CTkButton(
                body, text=t("online.open_page", "在浏览器打开原页面"),
                command=lambda: webbrowser.open(details.profile_url),
            ).pack(pady=12)
        if not self.state.loading:
            self.status.configure(text=t("online.ready", "搜索或浏览 GameBanana"))

    # ============================================================
    # 描述 AI 翻译（译文显示在原文下方，不替换、不持久化）
    # ============================================================
    def _translate_description(self, dialog, section, button, text):
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
            text_color="gray", justify="left", wraplength=690, anchor="w")
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
                wraplength=690, anchor="w",
            ).pack(fill="x", pady=(6, 0))
            return
        ctk.CTkLabel(
            section, text="🌐 " + result,
            justify="left", wraplength=690, anchor="w",
            text_color=("gray20", "gray85"),
        ).pack(fill="x", pady=(6, 0))
        button.configure(
            state="disabled", text=t("ai.translated", "已翻译"))

    def _file_row(self, parent, details, remote_file, dialog):
        row = ctk.CTkFrame(parent)
        row.pack(fill="x", pady=2)
        label = "{}  |  {}  |  {}".format(
            remote_file.name, remote_file.version or "-",
            _format_bytes(remote_file.size))
        ctk.CTkLabel(
            row, text=label, anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=8, pady=6)
        enabled = bool(remote_file.download_url) and not details.unavailable_reason
        ctk.CTkButton(
            row, text=t("online.install", "安装"), width=64,
            state="normal" if enabled else "disabled",
            command=lambda: (dialog.destroy(), self.on_install(details, remote_file)),
        ).pack(side="right", padx=6, pady=4)

    def _show_full_image(self, url, name, parent):
        if self._destroyed:
            return
        max_width = int(self.root.winfo_screenwidth() * 0.75)
        max_height = int(self.root.winfo_screenheight() * 0.75)
        future = self._executor.submit(
            self._fetch_full_image, url, max_width, max_height)
        self._track_future(future)

        def completed(done):
            try:
                image = done.result()
                self._post(self._open_image_window, name, image, parent)
            except Exception as exc:
                def error_ui(error):
                    try:
                        if parent.winfo_exists():
                            showerror(
                                t("online.error", "在线加载失败：{error}").format(
                                    error=error),
                                error, parent=parent)
                    except Exception:
                        pass
                self._post(error_ui, str(exc))

        future.add_done_callback(completed)

    def _fetch_full_image(self, url, max_width, max_height):
        from PIL import Image
        image = Image.open(BytesIO(self.client.fetch_image(url))).convert("RGB")
        image.thumbnail((max_width, max_height))
        return image

    def _open_image_window(self, name, image, parent):
        if self._destroyed:
            return
        try:
            if not parent.winfo_exists():
                return
        except Exception:
            return
        window = ctk.CTkToplevel(parent, fg_color="black")
        try:
            # customtkinter 在 Windows 上重应用标题栏深色时会 withdraw 窗口
            # （__init__ 内同步一次，resizable/transient 又各延迟一次），此时
            # 立即 grab_set() 会把抓取挂到隐藏窗口上，吞掉全部输入导致界面
            # 卡死；禁用该窗口的标题栏色操纵，彻底避免抓取中的窗口被隐藏。
            # 深色标题栏改由 finish_show 里直接重设 DWM 属性（不 withdraw）。
            window._deactivate_windows_window_header_manipulation = True
        except Exception:
            pass
        window.title(name)
        window.transient(parent)
        window.resizable(False, False)
        ctk_image = ctk.CTkImage(
            light_image=image, dark_image=image, size=image.size)
        self._images[("full", id(window))] = ctk_image
        ctk.CTkLabel(
            window, text="", image=ctk_image, fg_color="black"
        ).pack(fill="both", expand=True)

        def close_window():
            self._images.pop(("full", id(window)), None)
            try:
                window.grab_release()
            except Exception:
                pass
            try:
                if window.winfo_exists():
                    window.destroy()
            except Exception:
                pass
            try:
                if parent.winfo_exists():
                    parent.grab_set()
                    parent.lift()
                    parent.focus_force()
            except Exception:
                pass

        window.protocol("WM_DELETE_WINDOW", close_window)
        window.bind("<Escape>", lambda _event: close_window())

        def finish_show():
            try:
                if self._destroyed or not window.winfo_exists():
                    return
                _apply_windows_titlebar_color(window, ctk.get_appearance_mode())
                window.grab_set()
                window.lift()
                window.focus_force()
            except Exception:
                pass

        # 延迟抓取：等窗口经过标题栏色 withdraw/revert 周期（最晚约 25ms）
        # 稳定可见后再 grab_set，避免抓取作用在隐藏窗口上导致 Tk 事件循环卡死。
        window.after(60, finish_show)

    # ============================================================
    # 生命周期
    # ============================================================
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

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        if self._popup_refresh_job is not None:
            try:
                self.root.after_cancel(self._popup_refresh_job)
            except Exception:
                pass
            self._popup_refresh_job = None
        self._destroy_category_menus()
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
            self.client.close()
        except Exception:
            pass
        super().destroy()


def _apply_windows_titlebar_color(window, appearance_mode):
    """仅 Windows：直接设置 DWM 深色/浅色标题栏属性，不做库的 withdraw+update。

    库的 _windows_set_titlebar_color() 会 withdraw 窗口强制重绘，在窗口已被
    grab_set 后会导致 Tk 事件循环卡死；这里只设置 DWM 属性，窗口下次重绘即生效。
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


def _format_bytes(value):
    value = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return "{:.1f} {}".format(value, unit)
        value /= 1024
