# -*- coding: utf-8 -*-
"""Renderer-independent catalog modes, item models, and page state."""

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Set, Tuple


COMPACT = "compact"
CARD = "card"
DETAILED = "detailed"
VIEW_MODES = (COMPACT, CARD, DETAILED)
# 切换器显示顺序：两个列表相邻，卡片最后。
VIEW_MODE_ORDER = (COMPACT, DETAILED, CARD)


def normalize_view_mode(mode, default=COMPACT):
    return mode if mode in VIEW_MODES else default


def is_sensitive(item):
    return bool(
        getattr(item, "has_content_ratings", False) or
        getattr(item, "visibility", "show") in ("warn", "hide")
    )


def readme_presentation(readme_files):
    files = tuple(readme_files)
    if not files:
        return None, files
    if len(files) == 1:
        return files[0][0], files
    return "README x{}".format(len(files)), files


def fit_card_text(text, font, max_width):
    """按自然断点换行，并将卡片文字限制为最多两行。"""
    if not text:
        return ""

    # 英文单词、版本号和带连接符的名称尽量保持完整；中文等字符可逐字换行。
    tokens = re.findall(
        r"\s+|[A-Za-z0-9]+(?:[._'-][A-Za-z0-9]+)*|.",
        text,
    )
    lines = []
    current = ""
    truncated = False

    while tokens and len(lines) < 2:
        token = tokens.pop(0)
        candidate = current + token
        if font.measure(candidate.rstrip()) <= max_width:
            current = candidate
            continue

        if current.strip():
            lines.append(current.rstrip())
            current = ""
            if len(lines) == 2:
                truncated = True
                break
            token = token.lstrip()
            if token:
                tokens.insert(0, token)
            continue

        # 单个连续名称本身超过一行时，只能在字符中间断开。
        fitted = ""
        for index, char in enumerate(token):
            if fitted and font.measure(fitted + char) > max_width:
                lines.append(fitted)
                remainder = token[index:]
                if remainder:
                    tokens.insert(0, remainder)
                break
            fitted += char
        else:
            current = fitted

    if len(lines) < 2 and current:
        lines.append(current.rstrip())

    if (tokens or truncated) and lines:
        last = lines[-1].rstrip()
        while last and font.measure(last + "...") > max_width:
            last = last[:-1].rstrip()
        lines[-1] = last + "..."

    return "\n".join(lines[:2])


@dataclass(frozen=True)
class ScrollAnchor:
    key: Optional[str] = None
    offset: int = 0


@dataclass(frozen=True)
class LocalItemViewModel:
    key: str
    folder_name: str
    display_name: str
    secondary_name: Optional[str]
    path: str
    enabled: bool
    selected: bool
    note: str = ""
    preview_ref: str = ""
    readme_files: Tuple[Tuple[str, str], ...] = ()

    @classmethod
    def from_mod(cls, mod, note="", preview_ref="", selected=False,
                 readme_files=()):
        folder_name = mod["name"]
        note = (note or "").strip()
        return cls(
            key=folder_name,
            folder_name=folder_name,
            display_name=note or folder_name,
            secondary_name=folder_name if note else None,
            path=mod["path"],
            enabled=bool(mod["enabled"]),
            selected=bool(selected),
            note=note,
            preview_ref=preview_ref or "",
            readme_files=tuple(readme_files),
        )


@dataclass(frozen=True)
class RemoteItemViewModel:
    submission_id: int
    title: str
    author: str
    category: str
    version: str
    preview_refs: Tuple[str, ...]
    sensitive: bool
    details_state: str = "idle"

    @classmethod
    def from_remote(cls, item, unknown_author=""):
        return cls(
            submission_id=item.id,
            title=item.name,
            author=item.author.name if item.author else unknown_author,
            category=item.category or "-",
            version=item.version or "-",
            preview_refs=tuple(image.thumbnail_url for image in item.images),
            sensitive=is_sensitive(item),
        )


@dataclass
class LocalCatalogState:
    view_mode: str = COMPACT
    selected_names: Set[str] = field(default_factory=set)
    scroll_anchor: ScrollAnchor = field(default_factory=ScrollAnchor)

    def prune_selection(self, valid_names: Iterable[str]):
        self.selected_names.intersection_update(valid_names)


@dataclass
class OnlineCatalogState:
    view_mode: str = DETAILED
    query: str = ""
    sort: str = "popular"
    category: Optional[Tuple[str, int]] = None
    successful_page: int = 0
    record_count: int = 0
    has_next: bool = False
    loading: bool = False
    request_generation: int = 0
    items: list = field(default_factory=list)
    item_by_id: Dict[int, object] = field(default_factory=dict)
    scroll_anchor: ScrollAnchor = field(default_factory=ScrollAnchor)
    details_in_flight: Set[int] = field(default_factory=set)

    def begin_search(self, query, sort, category=None):
        self.query = query.strip()
        self.sort = sort
        self.category = category
        self.request_generation += 1
        self.successful_page = 0
        self.record_count = 0
        self.has_next = False
        self.items.clear()
        self.item_by_id.clear()
        return self.request_generation

    @property
    def next_page(self):
        return self.successful_page + 1

    def accept_page(self, generation, page):
        if generation != self.request_generation:
            return False
        for item in page.items:
            if item.is_obsolete or item.id in self.item_by_id:
                continue
            self.item_by_id[item.id] = item
            self.items.append(item)
        self.successful_page = page.page
        self.record_count = page.record_count
        self.has_next = page.has_next
        return True

    def begin_details(self, item_id):
        if item_id in self.details_in_flight:
            return False
        self.details_in_flight.add(item_id)
        return True

    def finish_details(self, item_id):
        self.details_in_flight.discard(item_id)


def remote_image_cache_key(url, size, blur):
    return url, tuple(size), bool(blur)
