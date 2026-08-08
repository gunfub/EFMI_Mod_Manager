# -*- coding: utf-8 -*-
"""Small, provider-specific GameBanana API and download client."""

from __future__ import annotations

import hashlib
import json
import os
import re
import ipaddress
import time
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx


BASE_URL = "https://gamebanana.com"
GAME_ID = 21842
USER_AGENT = "EFMI-Mod-Manager/1.0 (+https://gamebanana.com)"
DOWNLOAD_HOSTS = ("gamebanana.com", "files.gamebanana.com")
MEDIA_HOST = "images.gamebanana.com"
MAX_REDIRECTS = 5
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024
ALLOWED_MODELS = ("Mod", "Tool", "Sound")


def _normalize_model(model):
    return model if model in ALLOWED_MODELS else "Mod"


class GameBananaError(Exception):
    pass


class DownloadValidationError(GameBananaError):
    pass


@dataclass(frozen=True)
class Page:
    items: Tuple["RemoteMod", ...]
    record_count: int
    per_page: int
    page: int
    is_complete: bool

    @property
    def has_next(self):
        return not self.is_complete and bool(self.items)


@dataclass(frozen=True)
class RemoteImage:
    url: str
    thumbnail_url: str
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass(frozen=True)
class RemoteAuthor:
    name: str
    profile_url: Optional[str] = None


@dataclass(frozen=True)
class RemoteFile:
    id: int
    name: str
    size: int
    date_added: int
    download_url: Optional[str]
    md5: Optional[str]
    version: Optional[str]
    description: Optional[str]
    archived: bool = False


@dataclass(frozen=True)
class RemoteCategory:
    model: str
    category_id: int
    name: str
    item_count: int = 0
    icon_url: Optional[str] = None
    has_children: bool = False


@dataclass(frozen=True)
class RemoteMod:
    id: int
    name: str
    profile_url: str
    version: Optional[str]
    date_updated: Optional[int]
    author: Optional[RemoteAuthor]
    category: Optional[str]
    images: Tuple[RemoteImage, ...]
    has_files: bool
    model: str = "Mod"
    visibility: str = "show"
    has_content_ratings: bool = False
    is_obsolete: bool = False


@dataclass(frozen=True)
class RemoteDetails(RemoteMod):
    description: str = ""
    files: Tuple[RemoteFile, ...] = ()
    archived_files: Tuple[RemoteFile, ...] = ()
    unavailable_reason: Optional[str] = None


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _image(item):
    base = _text(item.get("_sBaseUrl"))
    file_name = _text(item.get("_sFile"))
    if not base or not file_name:
        return None
    full = base.rstrip("/") + "/" + file_name
    thumb = _text(item.get("_sFile220")) or file_name
    return RemoteImage(
        url=full,
        thumbnail_url=base.rstrip("/") + "/" + thumb,
        width=item.get("_wFile220"), height=item.get("_hFile220"))


def _images(payload):
    media = payload.get("_aPreviewMedia") or {}
    values = media.get("_aImages") or []
    result = [_image(item) for item in values if isinstance(item, dict)]
    return tuple(item for item in result if item is not None)


def _author(payload):
    value = payload.get("_aSubmitter") or {}
    name = _text(value.get("_sName"))
    if not name:
        return None
    return RemoteAuthor(name, _text(value.get("_sProfileUrl")))


def _mod(payload, model=None):
    root_category = payload.get("_aRootCategory") or payload.get("_aCategory") or {}
    return RemoteMod(
        id=int(payload.get("_idRow", 0)), name=_text(payload.get("_sName")) or "(Unnamed)",
        profile_url=_text(payload.get("_sProfileUrl")) or "",
        version=_text(payload.get("_sVersion")),
        date_updated=payload.get("_tsDateUpdated") or payload.get("_tsDateModified"),
        author=_author(payload),
        category=_text(root_category.get("_sName")),
        images=_images(payload), has_files=bool(payload.get("_bHasFiles")),
        model=_normalize_model(_text(payload.get("_sModelName")) or model),
        visibility=_text(payload.get("_sInitialVisibility")) or "show",
        has_content_ratings=bool(payload.get("_bHasContentRatings")),
        is_obsolete=bool(payload.get("_bIsObsolete")))


def _file(payload, archived=False):
    md5 = _text(payload.get("_sMd5Checksum"))
    if md5 and not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
        md5 = None
    return RemoteFile(
        id=int(payload.get("_idRow", 0)), name=_text(payload.get("_sFile")) or "download.zip",
        size=int(payload.get("_nFilesize") or 0), date_added=int(payload.get("_tsDateAdded") or 0),
        download_url=_text(payload.get("_sDownloadUrl")), md5=md5,
        version=_text(payload.get("_sVersion")), description=_text(payload.get("_sDescription")),
        archived=archived or bool(payload.get("_bIsArchived")))


def _as_records(payload):
    """分类接口在只有一条记录时返回单对象而不是数组，统一归一化。"""
    if payload is None:
        return []
    if isinstance(payload, dict):
        return [payload]
    return [item for item in payload if isinstance(item, dict)]


def _category(payload, model, id_from_url=False):
    category_id = _text(payload.get("_sUrl")) if id_from_url else payload.get("_idRow")
    try:
        if id_from_url:
            category_id = int(category_id.rstrip("/").rsplit("/", 1)[-1])
        else:
            category_id = int(category_id or 0)
    except (TypeError, ValueError, AttributeError):
        category_id = 0
    return RemoteCategory(
        model=model, category_id=category_id,
        name=_text(payload.get("_sName")) or "(Unnamed)",
        item_count=int(payload.get("_nItemCount") or 0),
        icon_url=_text(payload.get("_sIconUrl")),
        has_children=int(payload.get("_nCategoryCount") or 0) > 0)


def _category_filter(category):
    """把 RemoteCategory 或 (model, category_id) 归一化为 (model, category_id or None)。"""
    if category is None:
        return "Mod", None
    if isinstance(category, RemoteCategory):
        return category.model, category.category_id or None
    model, category_id = category
    return model or "Mod", category_id or None


class GameBananaClient:
    def __init__(self, client=None, cache_dir=None, timeout=20.0, cache_ttl=300,
                 proxy=None):
        self.client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            proxy=proxy)
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl

    def close(self):
        close = getattr(self.client, "close", None)
        if close:
            close()

    def _get_json(self, path, params=None, force=False):
        url = BASE_URL + path
        cache_path = self._cache_path(url, params)
        if not force and cache_path and os.path.isfile(cache_path):
            if time.time() - os.path.getmtime(cache_path) < self.cache_ttl:
                try:
                    with open(cache_path, "r", encoding="utf-8") as handle:
                        return json.load(handle)
                except (OSError, ValueError):
                    pass
        try:
            response = self.client.get(url, params=params)
            if response.status_code == 404:
                raise GameBananaError("GameBanana 内容不存在或已删除")
            response.raise_for_status()
            payload = response.json()
            if cache_path:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                temp_path = cache_path + ".tmp"
                with open(temp_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                os.replace(temp_path, cache_path)
            return payload
        except GameBananaError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise GameBananaError("GameBanana 请求失败: {}".format(exc)) from exc

    def browse(self, page=1, per_page=30, sort="popular", query="",
               category=None, model=None, force=False):
        if page < 1:
            raise ValueError("page must be >= 1")
        base_model, category_id = _category_filter(category)
        model = _normalize_model(model or base_model)
        if query.strip():
            if model != "Mod":
                raise GameBananaError(
                    "该分类不支持搜索，请先选择「全部」或 Mods 分类")
            params = {"_sModelName": "Mod", "_sOrder": "best_match",
                      "_idGameRow": GAME_ID, "_sSearchString": query.strip(),
                      "_csvFields": "name,description,article,attribs,studio,owner,credits",
                      "_nPerpage": min(per_page, 30), "_nPage": page}
            if category_id:
                params["_aFilters[Generic_Category]"] = category_id
            payload = self._get_json("/apiv11/Util/Search/Results", params, force=force)
        else:
            params = {"_nPerpage": min(per_page, 30), "_nPage": page,
                      "_aFilters[Generic_Game]": GAME_ID,
                      "_sSort": "Generic_NewAndUpdated" if sort == "recent" else "Generic_MostDownloaded"}
            if category_id:
                params["_aFilters[Generic_Category]"] = category_id
            payload = self._get_json("/apiv11/{}/Index".format(model), params, force=force)
        metadata = payload.get("_aMetadata") or {}
        items = tuple(_mod(item, model) for item in payload.get("_aRecords") or [])
        return Page(items, int(metadata.get("_nRecordCount") or 0),
                    int(metadata.get("_nPerpage") or per_page), page,
                    bool(metadata.get("_bIsComplete")))

    def categories(self, model="Mod", game_id=GAME_ID, force=False):
        model = _normalize_model(model)
        payload = self._get_json("/apiv11/{}/Categories".format(model),
                                 {"_idGameRow": int(game_id), "_sSort": "count"},
                                 force=force)
        return tuple(_category(item, model)
                     for item in _as_records(payload)
                     if not bool(item.get("_bIsObsolete")))

    def subcategories(self, model, category_id, force=False):
        model = _normalize_model(model)
        payload = self._get_json(
            "/apiv11/{}Category/{}/SubCategories".format(model, int(category_id)),
            force=force)
        return tuple(_category(item, model, id_from_url=True)
                     for item in _as_records(payload))

    def details(self, mod_id, model="Mod", force=False):
        model = _normalize_model(model)
        payload = self._get_json(
            "/apiv11/{}/{}/ProfilePage".format(model, int(mod_id)), force=force)
        base = _mod(payload, model)
        private = bool(payload.get("_bIsPrivate"))
        trashed = bool(payload.get("_bIsTrashed"))
        withheld = bool(payload.get("_bIsWithheld"))
        reason = "Private" if private else "Trashed" if trashed else "Withheld" if withheld else None
        active = tuple(_file(item) for item in payload.get("_aFiles") or [])
        archived = tuple(_file(item, True) for item in payload.get("_aArchivedFiles") or [])
        return RemoteDetails(**base.__dict__, description=_strip_html(payload.get("_sDescription") or payload.get("_sText") or ""),
                             files=active, archived_files=archived, unavailable_reason=reason)

    def download(self, remote_file, destination, cancel_event=None,
                 progress_callback=None):
        if not remote_file.download_url or remote_file.id <= 0:
            raise DownloadValidationError("GameBanana 文件没有可用下载地址")
        parsed = urlparse(remote_file.download_url)
        if (parsed.scheme != "https" or parsed.hostname != "gamebanana.com" or
                parsed.path != "/dl/{}".format(remote_file.id) or
                parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise DownloadValidationError("下载地址不是预期的 GameBanana 文件地址")
        os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
        temp = str(destination) + ".partial"
        current = remote_file.download_url
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            host = (parsed.hostname or "").lower()
            if (parsed.scheme != "https" or not _allowed_download_host(host) or
                    parsed.username or parsed.password or parsed.port not in (None, 443) or
                    _is_ip_literal(host)):
                raise DownloadValidationError("下载重定向目标不受信任")
            with self.client.stream("GET", current, follow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadValidationError("下载重定向缺少目标地址")
                    current = str(httpx.URL(current).join(location))
                    continue
                if response.status_code != 200:
                    raise DownloadValidationError(
                        "下载请求失败: HTTP {}".format(response.status_code))
                try:
                    digest = hashlib.md5(usedforsecurity=False)
                except TypeError:  # Python 3.8/OpenSSL combinations without the keyword.
                    digest = hashlib.md5()
                count = 0
                try:
                    with open(temp, "wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if cancel_event is not None and cancel_event.is_set():
                                raise DownloadValidationError("下载已取消")
                            count += len(chunk)
                            if count > MAX_DOWNLOAD_BYTES or (remote_file.size and count > remote_file.size):
                                raise DownloadValidationError("下载文件超过允许大小")
                            digest.update(chunk)
                            output.write(chunk)
                            if progress_callback:
                                progress_callback(count, remote_file.size)
                    if remote_file.size and count != remote_file.size:
                        raise DownloadValidationError("下载大小校验失败")
                    actual_md5 = digest.hexdigest()
                    if remote_file.md5 and actual_md5.lower() != remote_file.md5.lower():
                        raise DownloadValidationError("下载 MD5 校验失败")
                    os.replace(temp, destination)
                    return destination
                finally:
                    if os.path.exists(temp):
                        os.remove(temp)
        raise DownloadValidationError("下载重定向次数过多")

    def fetch_image(self, url):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != MEDIA_HOST or parsed.username or parsed.password:
            raise DownloadValidationError("预览图片地址不受信任")
        cache_path = self._cache_path(url)
        if cache_path and os.path.isfile(cache_path):
            try:
                with open(cache_path, "rb") as handle:
                    return handle.read()
            except OSError:
                pass
        response = self.client.get(url, follow_redirects=False)
        if response.status_code != 200:
            raise DownloadValidationError("预览图片请求失败")
        content = response.content
        if len(content) > MAX_IMAGE_BYTES:
            raise DownloadValidationError("预览图片超过允许大小")
        if cache_path:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            temp_path = cache_path + ".tmp"
            with open(temp_path, "wb") as handle:
                handle.write(content)
            os.replace(temp_path, cache_path)
        return content

    def _cache_path(self, url, params=None):
        if not self.cache_dir:
            return None
        serialized = url + "?" + json.dumps(params or {}, sort_keys=True, ensure_ascii=True)
        key = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        suffix = ".json" if "/api" in url or "/apiv" in url else ".bin"
        return os.path.join(self.cache_dir, key + suffix)


def _allowed_download_host(host):
    return host in DOWNLOAD_HOSTS or bool(re.fullmatch(r"filecache[0-9]+\.gamebanana\.com", host))


def _is_ip_literal(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _strip_html(value):
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()
