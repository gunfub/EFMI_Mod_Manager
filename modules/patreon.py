# -*- coding: utf-8 -*-
"""Patreon 订阅内容访问（httpx 直连优先 + WebView2 按需临时）。

设计要点（对应 参考/PatreonDownloader-master 的移植）：
- 常规数据请求（列表/详情/登录检测/附件下载）用 httpx + 导出的登录
  cookie 直连 Patreon 内部 API（/api/posts 等），零浏览器进程，内存占用极低；
- WebView2 仅在三种场景按需临时启动、用完立即关闭（内存归还）：
  登录（导出 cookie）、刷新订阅（memberships 页面 DOM 渲染）、外链下载
  （可见窗口手动操作 + 下载捕获）；
- httpx 遇 403（Cloudflare 策略变化）时自动用 WebView2 fetch 兜底重试。
"""

import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlparse

from modules.config import ConfigManager

PATREON_HOME = "https://www.patreon.com/"
PATREON_LOGIN = "https://www.patreon.com/login"
PATREON_MEMBERSHIPS = "https://www.patreon.com/memberships"
_API_ROOT = "https://www.patreon.com/api"
_COOKIE_FILE = "cookies.json"

# 系统钥匙串（Windows 凭据管理器）服务名：带 EFMI_Mod_Manager 前缀避免撞名
_KEYRING_SERVICE = "EFMI_Mod_Manager.Patreon"
# 单条凭据约 2560 字节（UTF-16 存储）上限，cookie JSON 需分块存入多条凭据：
# - cookies.count  : 分块数量（写入顺序的最后一步，作为提交标记）
# - cookies.{i}    : 第 i 块（每块 _KEYRING_CHUNK_CHARS 字符）
_KEYRING_USER_COUNT = "cookies.count"
_KEYRING_USER_CHUNK = "cookies.{index}"
_KEYRING_CHUNK_CHARS = 800
# 防御上限：64 块 × 800 字符 ≈ 51KB，远超任何真实 cookie 集合
_KEYRING_MAX_CHUNKS = 64

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
)

# /api/posts 查询参数，字段清单照抄 PatreonDownloader PatreonPageCrawler.CrawlStartUrl
_POSTS_FIELDS = {
    "post": "change_visibility_at,comment_count,content,current_user_can_delete,"
            "current_user_can_view,current_user_has_liked,embed,image,is_paid,like_count,"
            "min_cents_pledged_to_view,post_file,post_metadata,published_at,patron_count,"
            "patreon_url,post_type,pledge_url,thumbnail_url,teaser_text,title,upgrade_url,"
            "url,was_posted_by_campaign_owner,content_json_string",
    "user": "image_url,full_name,url",
    "campaign": "show_audio_post_download_links,avatar_photo_url,earnings_visibility,"
                "is_nsfw,is_monthly,name,url",
    "access_rule": "access_rule_type,amount_cents",
    "media": "id,image_urls,download_url,metadata,file_name",
}
# 列表页稀疏字段（不请求正文/附件，响应小、解析快）
_LIST_POST_FIELDS = (
    "title,published_at,is_paid,current_user_can_view,image,url,"
    "patreon_url,teaser_text"
)
# 帖子列表每页数量（与 GameBanana 页一致）
PAGE_SIZE = 30
# 详情页完整 include（含附件与图集）
_DETAIL_POST_INCLUDES = (
    "attachments_media,images.null,access_rules.tier.null,user,campaign"
)

_CAMPAIGN_ID_RE = re.compile(r'\\?"self\\?"\s*:\s*\\?"https://www\.patreon\.com/api/campaigns/(\d+)\\?"')
_SYSTEM_VANITY = {
    "login", "settings", "home", "pricing", "products", "explore", "search",
    "membership", "register", "apps", "help", "team", "careers", "blog",
    "newsroom", "contact", "legal", "privacy", "terms", "posts", "about",
    "creator", "patrons", "campaign", "community", "m", "c", "user", "users",
    "messages", "notifications", "upgrade", "my", "join", "signup", "browse",
    "create", "memberships", "profile", "home",
}
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*') | set(chr(i) for i in range(32))


class PatreonError(Exception):
    """Patreon 功能通用错误。"""


class PatreonNotLoggedIn(PatreonError):
    """未登录或登录已失效。"""


class CookieStore:
    """登录 cookie 持久化：优先系统钥匙串（keyring / Windows 凭据管理器），
    钥匙串不可用或数据超限时回退到 data/patreon_profile/cookies.json。

    服务名带 EFMI_Mod_Manager 前缀，避免与其他应用撞名；凭据管理器单条
    容量有限（约 2560 字节），cookie JSON 按 800 字符分块存入多条凭据，
    用 cookies.count 作为提交标记保证整体一致性；成功写入后自动删除
    明文旧文件（含首次启动时从旧文件的迁移）。
    """

    def __init__(self, profile_dir):
        self._path = os.path.join(profile_dir, _COOKIE_FILE)
        self._cookies = []
        self._lock = threading.Lock()

    @staticmethod
    def _keyring():
        try:
            import keyring
            return keyring
        except Exception:
            return None

    @staticmethod
    def _chunk_username(index):
        return _KEYRING_USER_CHUNK.format(index=index)

    def _load_keyring(self):
        """返回 (cookie 列表或 None, 钥匙串是否可用)。"""
        kr = self._keyring()
        if kr is None:
            return None, False
        try:
            count_raw = kr.get_password(_KEYRING_SERVICE, _KEYRING_USER_COUNT)
        except Exception:
            return None, False
        if not count_raw:
            return None, True  # 钥匙串可用但无数据（提交标记缺失视为空）
        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            return None, False
        if count < 0 or count > _KEYRING_MAX_CHUNKS:
            return None, False
        try:
            chunks = []
            for index in range(count):
                raw = kr.get_password(
                    _KEYRING_SERVICE, self._chunk_username(index))
                if not raw:
                    return None, False  # 分块不完整 → 视为不可用
                chunks.append(raw)
        except Exception:
            return None, False
        try:
            data = json.loads("".join(chunks))
        except (ValueError, TypeError):
            return None, False
        if not isinstance(data, list):
            return None, False
        return [c for c in data if isinstance(c, dict)], True

    def _delete_all_keyring(self, kr):
        """删除计数标记与全部分块（含旧长度残留）。"""
        try:
            kr.delete_password(_KEYRING_SERVICE, _KEYRING_USER_COUNT)
        except Exception:
            pass
        for index in range(_KEYRING_MAX_CHUNKS):
            try:
                kr.delete_password(
                    _KEYRING_SERVICE, self._chunk_username(index))
            except Exception:
                pass

    def _save_keyring(self, cookies):
        """将 cookie JSON 分块写入钥匙串；失败时回滚并返回 False。"""
        kr = self._keyring()
        if kr is None:
            return False
        payload = json.dumps(cookies, ensure_ascii=False)
        chunks = [
            payload[i:i + _KEYRING_CHUNK_CHARS]
            for i in range(0, len(payload), _KEYRING_CHUNK_CHARS)
        ]
        if len(chunks) > _KEYRING_MAX_CHUNKS:
            return False
        try:
            self._delete_all_keyring(kr)  # 清旧账再写入，保证无残留
            for index, chunk in enumerate(chunks):
                kr.set_password(
                    _KEYRING_SERVICE, self._chunk_username(index), chunk)
            # 最后写提交标记：写失败则整体回滚，由调用方回退文件
            kr.set_password(
                _KEYRING_SERVICE, _KEYRING_USER_COUNT, str(len(chunks)))
            return True
        except Exception:
            try:
                self._delete_all_keyring(kr)
            except Exception:
                pass
            return False

    def _delete_keyring(self):
        kr = self._keyring()
        if kr is None:
            return
        self._delete_all_keyring(kr)

    def _load_file(self):
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                return [c for c in data if isinstance(c, dict)]
        except (OSError, ValueError):
            pass
        return []

    def _save_file(self):
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._cookies, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            pass

    def _remove_file(self):
        try:
            if os.path.isfile(self._path):
                os.remove(self._path)
        except OSError:
            pass

    def load(self):
        with self._lock:
            self._cookies = []
            cookies, keyring_ok = self._load_keyring()
            if cookies is not None:
                self._cookies = cookies
                return list(self._cookies)
            # 钥匙串无数据或不可用：读取旧文件；钥匙串可用且旧文件有数据则迁移
            file_cookies = self._load_file()
            if keyring_ok and file_cookies:
                if self._save_keyring(file_cookies):
                    self._remove_file()
            self._cookies = file_cookies
            return list(self._cookies)

    def save(self, cookies):
        with self._lock:
            self._cookies = list(cookies)
            if self._save_keyring(self._cookies):
                self._remove_file()  # 已入钥匙串，删除明文旧文件
                return
            self._save_file()

    def clear(self):
        with self._lock:
            self._cookies = []
            self._delete_keyring()
            self._remove_file()

    def header(self):
        """构造 Cookie 请求头（patreon 域 cookie）。"""
        with self._lock:
            pairs = [
                "{}={}".format(c["name"], c["value"])
                for c in self._cookies
                if c.get("name") and "patreon" in (c.get("domain") or "")
            ]
        return "; ".join(pairs)


# ---------------------------------------------------------------------------
# 纯函数（可单测，不依赖 pywebview）
# ---------------------------------------------------------------------------

def sanitize_filename(name, max_length=80):
    """清洗文件名：非法字符替换、去首尾空白与点、超长截断（保留扩展名）。"""
    name = "".join("_" if ch in _INVALID_FILENAME_CHARS else ch for ch in (name or ""))
    name = name.strip().strip(".")
    if not name:
        name = "file"
    base, ext = os.path.splitext(name)
    ext = ext[:10]
    if len(base) > max_length:
        base = base[:max_length]
    return base + ext


def extract_campaign_id(html):
    """从创作者页面 HTML 提取 campaign id（PatreonDownloader 同款正则）。"""
    match = _CAMPAIGN_ID_RE.search(html or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_external_links(content_json):
    """从 content_json_string（ProseMirror doc）提取外链。

    支持两种结构：text 节点的 link marks（attrs.href）与旧式 link 块（url）。
    """
    links = []
    try:
        root = json.loads(content_json) if content_json else None
    except (TypeError, ValueError):
        return links
    if root is None:
        return links

    def walk(node):
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "link" and isinstance(node.get("url"), str):
                links.append(node["url"])
            attrs = node.get("attrs")
            if isinstance(attrs, dict) and isinstance(attrs.get("href"), str):
                links.append(attrs["href"])
            if node_type == "text":
                for mark in node.get("marks") or []:
                    if isinstance(mark, dict) and mark.get("type") == "link":
                        mark_attrs = mark.get("attrs")
                        if isinstance(mark_attrs, dict) and isinstance(
                                mark_attrs.get("href"), str):
                            links.append(mark_attrs["href"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(root)
    seen, out = set(), []
    for url in links:
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def render_content_blocks(content_json):
    """解析 content_json_string（ProseMirror doc）为有序展示块。

    返回 [{type: "text", text: str} | {type: "image", url: str}, ...]，
    保持正文中文字与图片的顺序。
    """
    try:
        root = json.loads(content_json) if content_json else None
    except (TypeError, ValueError):
        return []
    if not isinstance(root, dict) or root.get("type") != "doc":
        return []

    blocks = []
    for node in root.get("content") or []:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if node_type == "image":
            attrs = node.get("attrs") or {}
            src = attrs.get("src")
            if src:
                blocks.append({"type": "image", "url": src})
            continue
        if node_type in ("paragraph", "heading"):
            text = _node_text(node)
            if text:
                blocks.append({"type": "text", "text": text})
    return blocks


def _node_text(node):
    """提取 ProseMirror 节点的纯文本（递归拼接 text 节点）。"""
    parts = []
    for child in node.get("content") or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "text":
            text = child.get("text") or ""
            if text:
                parts.append(text)
        elif child.get("content"):
            parts.append(_node_text(child))
    return "".join(parts)


def parse_posts_page(payload):
    """解析 /api/posts 响应（JSON:API），返回 (posts, next_cursor)。

    posts 元素字段：post_id/title/published_at/is_paid/can_view/teaser_text/
    cover_url/cover_thumb_url/images/post_url/content_json/post_file/
    attachments/embed_url/external_links。稀疏列表响应中
    content_json/attachments/external_links 等为 None/空。
    """
    included = {
        (entry.get("type"), entry.get("id")): entry
        for entry in payload.get("included") or []
    }
    posts = []
    raw_data = payload.get("data") or []
    if isinstance(raw_data, dict):
        raw_data = [raw_data]
    for entry in raw_data:
        if entry.get("type") != "post":
            continue
        attrs = entry.get("attributes") or {}
        rels = entry.get("relationships") or {}
        image = attrs.get("image") or {}
        post = {
            "post_id": entry.get("id"),
            "title": attrs.get("title"),
            "published_at": attrs.get("published_at"),
            "is_paid": bool(attrs.get("is_paid")),
            "can_view": bool(attrs.get("current_user_can_view")),
            "teaser_text": attrs.get("teaser_text"),
            "cover_url": image.get("url") if isinstance(image, dict) else None,
            "cover_thumb_url": (image.get("thumb_url")
                                if isinstance(image, dict) else None),
            "images": _parse_media_urls(rels.get("images"), included),
            "post_url": attrs.get("url") or attrs.get("patreon_url"),
            "content_json": attrs.get("content_json_string"),
            "post_file": _parse_post_file(attrs.get("post_file")),
            "attachments": _parse_media(rels.get("attachments_media"), included),
            "embed_url": (attrs.get("embed") or {}).get("url"),
            "external_links": extract_external_links(attrs.get("content_json_string")),
        }
        posts.append(post)

    next_url = (payload.get("links") or {}).get("next")
    next_cursor = None
    if next_url:
        query = parse_qs(urlparse(next_url).query)
        cursor_values = query.get("page[cursor]")
        if cursor_values:
            next_cursor = cursor_values[0]
    return posts, next_cursor


def _parse_media_urls(relationship, included):
    """帖子图片图集（详情页展示）：media 的 original 原图 URL。

    Patreon 的 default 变体为方形裁剪图，原图（original）才是完整图片。
    """
    if not isinstance(relationship, dict):
        return []
    urls = []
    for ref in relationship.get("data") or []:
        if ref.get("type") != "media":
            continue
        entry = included.get(("media", ref.get("id")))
        if not entry:
            continue
        image_urls = (entry.get("attributes") or {}).get("image_urls") or {}
        url = (image_urls.get("original") or image_urls.get("default")
               or image_urls.get("url"))
        if url and url not in urls:
            urls.append(url)
    return urls


def _parse_post_file(post_file):
    if not isinstance(post_file, dict):
        return None
    url = post_file.get("url")
    if not url:
        return None
    return {
        "name": post_file.get("name") or os.path.basename(urlparse(url).path) or "file",
        "url": url,
    }


def _parse_media(relationship, included):
    if not isinstance(relationship, dict):
        return []
    result = []
    for ref in relationship.get("data") or []:
        if ref.get("type") != "media":
            continue
        entry = included.get(("media", ref.get("id")))
        if not entry:
            continue
        attrs = entry.get("attributes") or {}
        url = attrs.get("download_url")
        if not url:
            continue
        result.append({
            "file_id": entry.get("id"),
            "name": attrs.get("file_name") or os.path.basename(urlparse(url).path) or "file",
            "url": url,
        })
    return result


def is_creator_link(href):
    """判断链接是否为创作者页（排除 login/settings/posts 等系统页）。"""
    prefix = "https://www.patreon.com/"
    if not (href or "").startswith(prefix):
        return False
    path = href[len(prefix):]
    first = path.split("/", 1)[0].split("?", 1)[0].lower()
    if first in ("user", "c", "m"):
        return True
    return bool(first) and first not in _SYSTEM_VANITY


# 合集请求的帖子字段（多一个 like_count 供"热门"本地排序）
_COLLECTION_POST_FIELDS = _LIST_POST_FIELDS + ",like_count"


def sort_posts(posts, sort):
    """按排序方式排序帖子列表（合集场景本地排序）。

    最新（-published_at）：published_at 降序；热门（-like_count）：like_count 降序。
    字段缺失时降级（None 视为最旧/最少赞）。
    """
    def published_key(post):
        value = post.get("published_at") or ""
        if not value:
            return ""
        return value

    def like_key(post):
        value = post.get("like_count")
        return value if isinstance(value, (int, float)) else 0

    if sort == "-like_count":
        return sorted(posts, key=like_key, reverse=True)
    return sorted(posts, key=published_key, reverse=True)


def parse_collections_payload(payload):
    """解析 campaign 接口 include=collections(.posts) 响应。

    返回 (collections, posts_map)：
    collections: [{id, title, url, post_ids: [...]}]
    posts_map:   {post_id: post dict（列表字段，来自 included）}
    """
    included = {
        (entry.get("type"), entry.get("id")): entry
        for entry in payload.get("included") or []
    }
    posts_map = {}
    for key, entry in included.items():
        if key[0] != "post":
            continue
        attrs = entry.get("attributes") or {}
        rels = entry.get("relationships") or {}
        image = attrs.get("image") or {}
        posts_map[key[1]] = {
            "post_id": key[1],
            "title": attrs.get("title"),
            "published_at": attrs.get("published_at"),
            "is_paid": bool(attrs.get("is_paid")),
            "can_view": bool(attrs.get("current_user_can_view")),
            "like_count": attrs.get("like_count") or 0,
            "teaser_text": attrs.get("teaser_text"),
            "cover_url": image.get("url") if isinstance(image, dict) else None,
            "cover_thumb_url": (image.get("thumb_url")
                                if isinstance(image, dict) else None),
            "images": [],
            "post_url": attrs.get("url") or attrs.get("patreon_url"),
            "content_json": None,
            "post_file": None,
            "attachments": [],
            "embed_url": None,
            "external_links": [],
        }

    collections = []
    for key, entry in included.items():
        if key[0] != "collection":
            continue
        attrs = entry.get("attributes") or {}
        post_ids = []
        posts_rel = ((entry.get("relationships") or {}).get("posts") or {})
        for ref in posts_rel.get("data") or []:
            # 轻量模式（不带 .posts）时 included 无帖子条目，保留原始 id 供计数
            post_ids.append(ref.get("id"))
        collections.append({
            "id": key[1],
            "title": attrs.get("title") or "合集",
            "url": attrs.get("url") or "",
            "post_ids": post_ids,
        })
    return collections, posts_map


def parse_campaigns_payload(payload):
    """从 user 接口（includes=memberships.campaign）解析创作者列表。"""
    creators = []
    data = payload.get("data") or []
    if isinstance(data, list):
        root = data[0] if data else {}
    else:
        root = data
    rels = root.get("relationships") or {}
    memberships = rels.get("memberships") or {}
    for ref in memberships.get("data") or []:
        entry = _find_included(payload, ref.get("type"), ref.get("id"))
        if not entry:
            continue
        campaign_rel = (entry.get("relationships") or {}).get("campaign") or {}
        campaign_ref = campaign_rel.get("data")
        if not campaign_ref:
            continue
        campaign = _find_included(payload, campaign_ref.get("type"), campaign_ref.get("id"))
        if not campaign:
            continue
        attrs = campaign.get("attributes") or {}
        creators.append({
            "campaign_id": campaign.get("id"),
            "name": attrs.get("name") or "Creator",
            "url": attrs.get("url") or "",
            "avatar_url": attrs.get("avatar_photo_url"),
        })
    seen = set()
    unique = []
    for creator in creators:
        if creator["campaign_id"] in seen:
            continue
        seen.add(creator["campaign_id"])
        unique.append(creator)
    return unique


def _find_included(payload, resource_type, resource_id):
    for entry in payload.get("included") or []:
        if entry.get("type") == resource_type and entry.get("id") == resource_id:
            return entry
    return None


def render_content_text(content_json):
    """将 content_json_string 渲染为纯文本（兼容 ProseMirror doc 与旧数组结构）。"""
    text = ""
    try:
        root = json.loads(content_json) if content_json else None
    except (TypeError, ValueError):
        return ""
    if isinstance(root, dict):
        if root.get("type") == "doc":
            text = "\n".join(
                block.get("text", "") for block in render_content_blocks(content_json)
                if block.get("type") == "text")
            return text
        return ""
    if not isinstance(root, list):
        return ""
    parts = []
    for block in root:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        content = block.get("content") or ""
        if block_type in ("text", "heading", "subheading"):
            if content:
                parts.append(content)
        elif block_type == "link":
            text_part = block.get("text") or block.get("url") or ""
            url = block.get("url") or ""
            parts.append("{}: {}".format(text_part, url)
                         if text_part and url else (text_part or url))
    return "\n".join(parts)


def cookie_to_dict(simple_cookie):
    """将 pywebview get_cookies() 返回的 SimpleCookie 转为 dict。"""
    for morsel in simple_cookie.values():
        return {
            "name": morsel.key,
            "value": morsel.value,
            "domain": morsel["domain"],
            "path": morsel["path"],
            "secure": morsel["secure"],
            "httponly": morsel["httponly"],
        }
    return {}


# ---------------------------------------------------------------------------
# 兼容补丁：主线程名检查 + SIGINT + 下载重定向
# ---------------------------------------------------------------------------

_PATCHES_APPLIED = False
_DL_STATE = {"dir": None, "captured": []}
_ORIG_DOWNLOAD_HANDLER = None
_ORIG_EDGE_INIT = None


def _webview_proxy_arg(proxy):
    """把手动代理转为 WebView2 --proxy-server 参数；不支持时返回 None。

    Chromium --proxy-server 不支持内嵌账号密码；带凭据或非 http/https
    的代理不注入（浏览器回退跟随系统代理）。"""
    proxy = (proxy or "").strip()
    if not proxy:
        return None
    try:
        parsed = urlparse(proxy if "://" in proxy else "http://" + proxy)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        if parsed.username or parsed.password or not parsed.port:
            return None
        host = parsed.hostname
        if ":" in host:
            host = "[{}]".format(host)
        return "--proxy-server={}://{}:{}".format(
            parsed.scheme, host, parsed.port)
    except ValueError:
        return None


def apply_compat_patches():
    """pywebview 6 要求调用线程名为 MainThread，且 winforms 会在该线程注册
    SIGINT 处理器（非主线程 signal.signal 抛 ValueError）。下载处理器被
    补丁为重定向到 _DL_STATE["dir"]（WebView2 自动处理重名加序号）。"""
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED:
        return
    _PATCHES_APPLIED = True

    import signal as signal_module
    original_signal = signal_module.signal

    def safe_signal(signum, handler):
        try:
            return original_signal(signum, handler)
        except ValueError:
            return None

    signal_module.signal = safe_signal

    if sys.platform == "win32":
        try:
            from webview.platforms import edgechromium as ec

            global _ORIG_DOWNLOAD_HANDLER, _ORIG_EDGE_INIT
            _ORIG_DOWNLOAD_HANDLER = ec.EdgeChrome.on_download_starting
            _ORIG_EDGE_INIT = ec.EdgeChrome.__init__

            def patched_download_starting(self, sender, args):
                try:
                    name = os.path.basename(args.ResultFilePath)
                    target = os.path.join(_DL_STATE["dir"] or os.getcwd(), name)
                    args.set_Handled(True)
                    args.ResultFilePath = target
                    _DL_STATE["captured"].append(name)
                except Exception:
                    _ORIG_DOWNLOAD_HANDLER(self, sender, args)

            ec.EdgeChrome.on_download_starting = patched_download_starting

            def patched_edge_init(self, form, window, cache_dir):
                """EdgeChrome.__init__ 复制版（pywebview 6.2.1）。

                在 AdditionalBrowserArguments 注入 --proxy-server，让本应用
                进程内的 WebView2 跟随手动代理；任何异常回退原版实现。"""
                webview2 = None
                try:
                    webview2 = ec.WebView2()
                    props = ec.CoreWebView2CreationProperties()

                    runtime_path = ec.webview_settings['WEBVIEW2_RUNTIME_PATH']
                    if runtime_path:
                        if not os.path.isabs(runtime_path):
                            runtime_path = os.path.join(
                                ec.get_app_root(), runtime_path)
                        if os.path.exists(runtime_path):
                            props.BrowserExecutableFolder = runtime_path
                            ec.logger.debug(
                                'Using custom WebView2 runtime: %s',
                                runtime_path)
                        else:
                            ec.logger.warning(
                                'Custom WebView2 runtime path does not exist: '
                                '%s. Using system WebView2.', runtime_path)

                    props.UserDataFolder = cache_dir
                    self.user_data_folder = props.UserDataFolder
                    props.set_IsInPrivateModeEnabled(ec._state['private_mode'])
                    props.AdditionalBrowserArguments = (
                        '--disable-features=ElasticOverscroll')

                    if ec.webview_settings['ALLOW_FILE_URLS']:
                        props.AdditionalBrowserArguments += (
                            ' --allow-file-access-from-files')

                    if ec.webview_settings['REMOTE_DEBUGGING_PORT'] is not None:
                        props.AdditionalBrowserArguments += (
                            ' --remote-debugging-port={}'.format(
                                ec.webview_settings['REMOTE_DEBUGGING_PORT']))

                    proxy_arg = _webview_proxy_arg(
                        ConfigManager.get_proxy())
                    if proxy_arg:
                        props.AdditionalBrowserArguments += ' ' + proxy_arg

                    self.pywebview_window = window
                    self.webview = webview2
                    webview2.CreationProperties = props

                    self.form = form
                    form.Controls.Add(webview2)

                    self.js_results = {}
                    self.js_result_semaphore = ec.Semaphore(0)
                    webview2.Dock = ec.WinForms.DockStyle.Fill
                    webview2.BringToFront()
                    webview2.CoreWebView2InitializationCompleted += (
                        self.on_webview_ready)
                    webview2.NavigationStarting += self.on_navigation_start
                    webview2.NavigationCompleted += self.on_navigation_completed
                    webview2.WebMessageReceived += self.on_script_notify
                    self.syncContextTaskScheduler = (
                        ec.TaskScheduler
                        .FromCurrentSynchronizationContext())
                    webview2.DefaultBackgroundColor = ec.Color.FromArgb(
                        255,
                        int(window.background_color.lstrip('#')[0:2], 16),
                        int(window.background_color.lstrip('#')[2:4], 16),
                        int(window.background_color.lstrip('#')[4:6], 16),
                    )

                    if window.transparent:
                        webview2.DefaultBackgroundColor = ec.Color.Transparent

                    self.url = None
                    self.ishtml = False
                    self.html = ec.DEFAULT_HTML

                    webview2.EnsureCoreWebView2Async(None)
                except Exception:
                    if webview2 is not None:
                        try:
                            form.Controls.Remove(webview2)
                        except Exception:
                            pass
                    _ORIG_EDGE_INIT(self, form, window, cache_dir)

            ec.EdgeChrome.__init__ = patched_edge_init
        except Exception:
            pass


# ---------------------------------------------------------------------------
# PatreonSession
# ---------------------------------------------------------------------------

class _Bridge:
    """js_api 桥：JS 端 fetch 结果按 tag 分发到专属队列（并发安全）。"""

    def __init__(self):
        self._queues = {}
        self._lock = threading.Lock()

    def register(self, tag):
        result_queue = queue.Queue()
        with self._lock:
            self._queues[tag] = result_queue
        return result_queue

    def unregister(self, tag):
        with self._lock:
            self._queues.pop(tag, None)

    def onFetchResult(self, tag, payload):
        with self._lock:
            result_queue = self._queues.get(tag)
        if result_queue is not None:
            result_queue.put(("fetch", tag, payload))


class PatreonSession:
    """Patreon 访问会话。

    httpx 模式为默认（普通浏览零浏览器进程）；WebView2 浏览器在
    登录/刷新订阅/外链/下载兜底时按需启动，用完立即关闭。
    """

    def __init__(self, profile_dir, download_dir):
        self._profile_dir = profile_dir
        self._download_dir = download_dir
        os.makedirs(profile_dir, exist_ok=True)
        os.makedirs(download_dir, exist_ok=True)

        self._cookie_store = CookieStore(profile_dir)
        self._bridge = _Bridge()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._browser_lock = threading.Lock()
        self._thread = None

        self._hub = None
        self._login_win = None
        self._ext_win = None
        self._dl_win = None
        self._closed_flag = False

    # -- 生命周期 ----------------------------------------------------------

    def start(self, timeout=60):
        """初始化 httpx 模式（加载本地 cookie；浏览器按需惰性启动）。"""
        apply_compat_patches()
        self._cookie_store.load()

    def _ensure_browser(self, timeout=90):
        """按需启动 WebView2 浏览器（已启动则复用）。"""
        with self._browser_lock:
            if self._thread is not None and not self._closed_flag:
                return
            self._bridge = _Bridge()
            self._ready = threading.Event()
            self._closed = threading.Event()
            self._closed_flag = False
            self._thread = threading.Thread(
                target=self._webview_main, name="MainThread", daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout):
                raise PatreonError("WebView2 浏览器会话启动超时")

    def _close_browser(self, timeout=10):
        """关闭浏览器并等待 WebView2 进程退出（幂等）。"""
        with self._browser_lock:
            if self._thread is None or self._closed_flag:
                self._thread = None
                return
            for window in (self._hub, self._login_win, self._ext_win, self._dl_win):
                if window is not None:
                    try:
                        window.destroy()
                    except Exception:
                        pass
            self._closed.wait(timeout)
            self._thread = None
            self._closed_flag = True
            self._hub = self._login_win = self._ext_win = self._dl_win = None

    def _webview_main(self):
        import webview

        self._hub = webview.create_window(
            "Patreon", PATREON_HOME, hidden=True, js_api=self._bridge,
            width=1100, height=800)
        self._login_win = webview.create_window(
            "Patreon 登录", PATREON_LOGIN, hidden=True, js_api=self._bridge,
            width=1000, height=760)
        self._ext_win = webview.create_window(
            "Patreon 外链下载", PATREON_HOME, hidden=True, js_api=self._bridge,
            width=1100, height=800)
        self._dl_win = webview.create_window(
            "Patreon 下载", PATREON_HOME, hidden=True, js_api=self._bridge,
            width=900, height=700)
        self._ready.set()
        webview.start(private_mode=False, storage_path=self._profile_dir)
        self._closed_flag = True
        self._closed.set()

    def close(self, timeout=10):
        self._close_browser(timeout)

    @property
    def is_closed(self):
        return self._closed_flag

    @property
    def download_dir(self):
        return self._download_dir

    # -- 内部工具 ----------------------------------------------------------

    def _check_alive(self):
        if self._closed_flag or self._thread is None:
            raise PatreonError("Patreon 浏览器会话已关闭")

    def _http_headers(self):
        headers = {"User-Agent": _USER_AGENT}
        cookie_header = self._cookie_store.header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    def _http_json(self, path, params=None, timeout=60, allow_browser_fallback=True):
        """httpx 直连 API。403（疑似 Cloudflare 策略变化）时自动用浏览器兜底。"""
        import httpx

        url = _API_ROOT + path
        if params:
            url += "?" + urlencode(params)
        try:
            response = httpx.get(
                url, headers=self._http_headers(), timeout=timeout,
                follow_redirects=True, proxy=ConfigManager.get_proxy() or None)
        except httpx.HTTPError as exc:
            raise PatreonError("网络请求失败: %s" % exc)
        if response.status_code == 403 and allow_browser_fallback:
            try:
                self._ensure_browser()
                try:
                    return self._browser_json(path, params, timeout)
                finally:
                    self._close_browser()
            except Exception:
                pass
        if response.status_code in (401, 403):
            raise PatreonNotLoggedIn("登录已失效，请重新登录 Patreon")
        if response.status_code >= 400:
            raise PatreonError("Patreon API 错误 %d" % response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise PatreonError("Patreon 响应解析失败: %s" % exc)

    def _ensure_hub_ready(self, timeout=60):
        self._check_alive()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                current = self._hub.get_current_url() or ""
            except Exception:
                current = ""
            if current.startswith("https://www.patreon.com"):
                return True
            try:
                self._hub.load_url(PATREON_HOME)
            except Exception:
                pass
            time.sleep(1.5)
        return False

    def _eval_js(self, make_script, timeout=60, retries=3):
        """执行 JS。make_script(tag) 返回使用该 tag 回传结果的脚本体。

        结果经 _Bridge 按 tag 分发到本请求专属队列，并发请求互不干扰。
        """
        self._check_alive()
        tag = uuid.uuid4().hex
        result_queue = self._bridge.register(tag)
        last_error = None
        try:
            script = make_script(tag)
            tag_json = json.dumps(tag)
            wrapped = (
                "try{" + script + "}"
                "catch(e){pywebview.api.onFetchResult(" + tag_json +
                ",'__PTERR__:'+(e&&e.message||e));}"
            )
            for attempt in range(retries):
                if attempt:
                    time.sleep(1)
                try:
                    self._hub.evaluate_js(wrapped)
                except Exception as exc:
                    last_error = exc
                    continue
                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        _kind, rtag, payload = result_queue.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if rtag != tag:
                        continue
                    if payload.startswith("__PTERR__:"):
                        last_error = PatreonError(payload[len("__PTERR__:"):])
                        break
                    return payload
                if not isinstance(last_error, PatreonError):
                    last_error = PatreonError("Patreon 页面无响应")
            raise last_error if isinstance(last_error, Exception) else PatreonError("Patreon 请求失败")
        finally:
            self._bridge.unregister(tag)

    def _browser_json(self, path, params=None, timeout=60):
        url = _API_ROOT + path
        if params:
            url += "?" + urlencode(params)
        if not self._ensure_hub_ready():
            raise PatreonError("无法打开 Patreon 页面")

        def make_script(tag):
            return (
                "fetch(%s,{credentials:'include',headers:{'Accept':'application/json'}})"
                ".then(function(r){return r.text();})"
                ".then(function(t){pywebview.api.onFetchResult(%s,t);})"
                ".catch(function(e){pywebview.api.onFetchResult(%s,'__PTERR__:'+(e&&e.message||e));});"
            ) % (json.dumps(url), json.dumps(tag), json.dumps(tag))

        payload = self._eval_js(make_script, timeout=timeout)
        if isinstance(payload, str) and payload.startswith("__PTERR__:"):
            raise PatreonError(payload[len("__PTERR__:"):])
        try:
            return json.loads(payload) if isinstance(payload, str) else payload
        except (TypeError, ValueError) as exc:
            raise PatreonError("Patreon 响应解析失败: %s" % exc)

    def _browser_html(self, url, timeout=60):
        def make_script(tag):
            return (
                "fetch(%s,{credentials:'include'})"
                ".then(function(r){return r.text();})"
                ".then(function(t){pywebview.api.onFetchResult(%s,t);})"
                ".catch(function(e){pywebview.api.onFetchResult(%s,'__PTERR__:'+(e&&e.message||e));});"
            ) % (json.dumps(url), json.dumps(tag), json.dumps(tag))

        payload = self._eval_js(make_script, timeout=timeout)
        if isinstance(payload, str) and payload.startswith("__PTERR__:"):
            raise PatreonError(payload[len("__PTERR__:"):])
        return payload or ""

    def _dom_json(self, script_body, timeout=60):
        def make_script(tag):
            return "(" + script_body + ")(" + json.dumps(tag) + ")"

        payload = self._eval_js(make_script, timeout=timeout)
        if isinstance(payload, str) and payload.startswith("__PTERR__:"):
            raise PatreonError(payload[len("__PTERR__:"):])
        try:
            return json.loads(payload) if isinstance(payload, str) else payload
        except (TypeError, ValueError):
            return []

    # -- 登录 --------------------------------------------------------------

    def is_logged_in(self):
        """校验登录态（httpx 直连，零浏览器进程）。"""
        try:
            payload = self._http_json(
                "/current_user", timeout=30, allow_browser_fallback=False)
        except (PatreonError, PatreonNotLoggedIn):
            return False
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("data"))

    def current_user_id(self):
        payload = self._http_json("/current_user", timeout=30)
        data = payload.get("data")
        if not data:
            raise PatreonNotLoggedIn("未登录 Patreon")
        return data.get("id")

    def _browser_logged_in(self, timeout=20):
        """通过浏览器桥检测登录态（登录窗口与 hub 共享同一 WebView2
        profile，用户在登录窗口完成登录后，hub 侧 fetch 立即可见）。"""
        try:
            payload = self._browser_json("/current_user", timeout=timeout)
        except PatreonError:
            return False
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("data"))

    def ensure_login(self, cancel_event=None, timeout=None, poll_interval=2.0):
        """确保已登录。未登录时临时启动浏览器显示登录窗口，登录成功后
        导出 cookie 并关闭浏览器（内存归还）。

        登录等待期间用浏览器桥检测登录态（窗口本就开着，无额外浏览器
        开销），检测成功后立即导出 cookie 并以 httpx 复核，复核通过才算
        完成；用户关闭登录窗口或超时返回 False。
        """
        if self.is_logged_in():
            return True
        self._ensure_browser()
        login_closed = threading.Event()

        def _on_login_closed():
            login_closed.set()

        try:
            self._login_win.events.closed += _on_login_closed
        except Exception:
            pass
        try:
            self._login_win.show()
        except Exception:
            pass
        deadline = None if timeout is None else time.time() + timeout
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return False
                if login_closed.is_set() or self._closed_flag:
                    return False
                if deadline is not None and time.time() > deadline:
                    return False
                if self._browser_logged_in():
                    for _ in range(3):
                        self._export_cookies()
                        if self.is_logged_in():
                            return True
                        time.sleep(0.5)
                    raise PatreonError("登录成功但 cookie 导出失败，请重试")
                time.sleep(poll_interval)
        finally:
            try:
                self._login_win.hide()
            except Exception:
                pass
            self._close_browser()

    def _export_cookies(self):
        """从浏览器会话导出 cookie 到本地（httpx 模式使用）。"""
        if self._hub is None:
            return
        try:
            raw = self._hub.get_cookies()
            cookies = [cookie_to_dict(item) for item in raw]
            if cookies:
                self._cookie_store.save(cookies)
        except Exception:
            pass

    # -- 创作者 ------------------------------------------------------------

    def list_subscribed_creators(self, cancel_event=None):
        """列出当前账号关注/订阅的创作者。

        临时启动浏览器渲染 /memberships 页面抓取创作者链接并解析
        campaign id，随后关闭浏览器；创作者详情（名称/头像）走 httpx。
        回退：user 接口 memberships.campaign（httpx）。
        """
        self._ensure_browser()
        links = []
        seen_ids = set()
        creators = []
        try:
            if not self._ensure_hub_ready():
                raise PatreonError("无法打开 Patreon 页面")
            try:
                self._hub.load_url(PATREON_MEMBERSHIPS)
                links = self._poll_creator_links(cancel_event)
            except Exception:
                links = []

            if links:
                for url in links:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    campaign_id = None
                    try:
                        page_html = self._browser_html(url, timeout=45)
                        campaign_id = extract_campaign_id(page_html)
                    except Exception:
                        pass
                    if not campaign_id or campaign_id in seen_ids:
                        time.sleep(0.4)
                        continue
                    seen_ids.add(campaign_id)
                    creators.append({"campaign_id": campaign_id, "url": url})
                    time.sleep(0.5)
        finally:
            self._close_browser()

        if not creators:
            try:
                creators = self._creators_from_user_endpoint(cancel_event)
            except Exception:
                creators = []
            if creators:
                return creators
            raise PatreonError("无法读取订阅列表，请确认已登录 Patreon 并点击重新登录")

        for creator in creators:
            if cancel_event is not None and cancel_event.is_set():
                break
            creator["name"] = "Creator %d" % creator["campaign_id"]
            creator["avatar_url"] = None
            try:
                details = self._http_json(
                    "/campaigns/%d" % creator["campaign_id"],
                    {"fields[campaign]": _POSTS_FIELDS["campaign"],
                     "json-api-version": "1.0"}, timeout=30)
                data = details.get("data") or {}
                attrs = data.get("attributes") or {}
                if attrs.get("name"):
                    creator["name"] = attrs["name"]
                if attrs.get("avatar_photo_url"):
                    creator["avatar_url"] = attrs["avatar_photo_url"]
            except Exception:
                pass
        return creators

    def _poll_creator_links(self, cancel_event=None, timeout=45):
        dom_script = (
            "function(tag){"
            "var out=[];var seen={};"
            "document.querySelectorAll('a[href*=\"patreon.com\"]').forEach(function(a){"
            "  var h=a.getAttribute('href');"
            "  if(!h||seen[h])return;"
            "  seen[h]=1;out.push(h);"
            "});"
            "pywebview.api.onFetchResult(tag,JSON.stringify(out));}"
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return []
            try:
                links = [link for link in self._dom_json(dom_script, timeout=30)
                         if is_creator_link(link)]
            except Exception:
                links = []
            if links:
                return links
            time.sleep(2)
        return []

    def _creators_from_user_endpoint(self, cancel_event=None):
        user_id = self.current_user_id()
        payload = self._http_json(
            "/user/%s" % user_id,
            {"include": "memberships.campaign,memberships.campaign.creator",
             "fields[campaign]": _POSTS_FIELDS["campaign"],
             "json-api-version": "1.0"}, timeout=45)
        return parse_campaigns_payload(payload)

    # -- 帖子 --------------------------------------------------------------

    def creator_posts(self, campaign_id, cursor=None, sort="-published_at",
                      timeout=60):
        """拉取一页帖子（默认 30 篇/页，httpx 直连）。

        sort：最新 -published_at；热门 -like_count；评论 -comment_count。
        返回 (posts, next_cursor, total)；next_cursor 为 None 表示已到末页，
        total 为创作者帖子总数（响应 meta.pagination.total，可能为 None）。
        """
        params = {
            "include": "user,campaign",
            "fields[post]": _LIST_POST_FIELDS,
            "fields[user]": _POSTS_FIELDS["user"],
            "fields[campaign]": _POSTS_FIELDS["campaign"],
            "sort": sort,
            "filter[is_draft]": "false",
            "filter[campaign_id]": campaign_id,
            "page[count]": str(PAGE_SIZE),
            "json-api-use-default-includes": "false",
            "json-api-version": "1.0",
        }
        if cursor:
            params["page[cursor]"] = cursor
        payload = self._http_json("/posts", params, timeout=timeout)
        posts, next_cursor = parse_posts_page(payload)
        total = None
        try:
            total_value = ((payload.get("meta") or {})
                           .get("pagination") or {}).get("total")
            if isinstance(total_value, int):
                total = total_value
        except AttributeError:
            pass
        return posts, next_cursor, total

    def post_details(self, post_id, timeout=60):
        """按需获取单篇帖子完整数据（正文/附件/外链/图集，httpx 直连）。"""
        params = {
            "include": _DETAIL_POST_INCLUDES,
            "fields[post]": _POSTS_FIELDS["post"],
            "fields[media]": _POSTS_FIELDS["media"],
            "fields[user]": _POSTS_FIELDS["user"],
            "fields[campaign]": _POSTS_FIELDS["campaign"],
            "fields[access_rule]": _POSTS_FIELDS["access_rule"],
            "json-api-use-default-includes": "false",
            "json-api-version": "1.0",
        }
        payload = self._http_json("/posts/%s" % post_id, params, timeout=timeout)
        data = payload.get("data")
        if not data:
            raise PatreonError("帖子不存在或不可见: %s" % post_id)
        posts, _ = parse_posts_page(payload)
        if not posts:
            raise PatreonError("帖子解析失败: %s" % post_id)
        return posts[0]

    def campaign_collections(self, campaign_id, with_posts=True, timeout=60):
        """拉取创作者合集列表（httpx 直连）。

        with_posts=True 时一次返回全部合集及其帖子（含全部帖子的列表字段），
        响应约数百 KB；False 时仅返回合集元数据与帖子 id 列表（轻量）。
        返回 (collections, posts_map)。
        """
        include = "collections.posts" if with_posts else "collections"
        params = {
            "include": include,
            "fields[collection]": "title,url",
            "fields[post]": _COLLECTION_POST_FIELDS,
            "json-api-use-default-includes": "false",
            "json-api-version": "1.0",
        }
        payload = self._http_json(
            "/campaigns/%s" % campaign_id, params, timeout=timeout)
        return parse_collections_payload(payload)

    # -- 下载 --------------------------------------------------------------

    def download_attachment(self, url, suggested_name, dest_dir, cancel_event=None,
                            progress_callback=None):
        """下载 Patreon 托管附件。httpx + cookie 优先，失败回退 WebView2 捕获。

        返回最终文件绝对路径；取消返回 None。
        """
        name = sanitize_filename(suggested_name)
        dest_path = _unique_path(dest_dir, name)
        if cancel_event is not None and cancel_event.is_set():
            return None
        try:
            return self._download_httpx(
                url, dest_path, cancel_event, progress_callback)
        except Exception:
            pass
        self._ensure_browser()
        try:
            return self._download_webview(url, dest_path, cancel_event, progress_callback)
        except Exception:
            return None
        finally:
            self._close_browser()

    def _download_httpx(self, url, dest_path, cancel_event, progress_callback):
        import httpx

        headers = self._http_headers()
        tmp = dest_path + ".part"
        with httpx.stream(
                "GET", url, headers=headers, follow_redirects=True,
                timeout=60, proxy=ConfigManager.get_proxy() or None) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with open(tmp, "wb") as handle:
                for chunk in response.iter_bytes(65536):
                    if cancel_event is not None and cancel_event.is_set():
                        handle.close()
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                        return None
                    handle.write(chunk)
                    done += len(chunk)
                    if progress_callback is not None:
                        progress_callback(done, total)
            os.replace(tmp, dest_path)
        return dest_path

    def _download_webview(self, url, dest_path, cancel_event, progress_callback):
        """导航隐藏窗口触发下载，经补丁处理器落盘到 download_dir 后移动到位。"""
        base_name = os.path.basename(dest_path)
        state_dir = self._download_dir
        _DL_STATE["dir"] = state_dir
        _DL_STATE["captured"] = []

        try:
            self._dl_win.load_url(url)
        except Exception:
            pass

        deadline = time.time() + 180
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return None
            candidates = [f for f in _DL_STATE["captured"] if f]
            if candidates:
                captured = _pick_captured(state_dir, base_name, candidates)
                if captured:
                    final = _unique_path(os.path.dirname(dest_path),
                                         os.path.basename(dest_path))
                    os.replace(captured, final)
                    return final
            if progress_callback is not None:
                temp = _download_temp_size(state_dir)
                progress_callback(temp, 0)
            time.sleep(1)
        raise PatreonError("下载超时")

    def open_external(self, url, cancel_event=None, on_message=None, timeout=None):
        """在可见 WebView2 窗口打开外链，用户手动操作；捕获下载后返回文件路径。

        返回 (file_path | None)。用户在窗口关闭/取消时返回 None。
        完成后浏览器立即关闭（内存归还）。
        """
        self._ensure_browser()
        state_dir = self._download_dir
        _DL_STATE["dir"] = state_dir
        _DL_STATE["captured"] = []

        try:
            self._ext_win.show()
        except Exception:
            pass
        try:
            self._ext_win.load_url(url)
        except Exception:
            pass
        if on_message is not None:
            on_message("请在打开的浏览器窗口中完成下载")

        deadline = None if timeout is None else time.time() + timeout
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return None
                if deadline is not None and time.time() > deadline:
                    return None
                candidates = [f for f in _DL_STATE["captured"] if f]
                if candidates:
                    captured = _pick_captured(state_dir, None, candidates)
                    if captured:
                        final = _unique_path(state_dir, os.path.basename(captured))
                        os.replace(captured, final)
                        return final
                time.sleep(1)
        finally:
            try:
                self._ext_win.hide()
            except Exception:
                pass
            self._close_browser()


def _unique_path(dest_dir, name):
    base, ext = os.path.splitext(name)
    candidate = os.path.join(dest_dir, name)
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, "%s (%d)%s" % (base, index, ext))
        index += 1
    return candidate


def _pick_captured(state_dir, base_name, candidates):
    for name in candidates:
        if not base_name:
            continue
        if name == base_name:
            path = os.path.join(state_dir, name)
            if os.path.isfile(path):
                return path
    for name in candidates:
        if base_name and name.startswith(base_name):
            path = os.path.join(state_dir, name)
            if os.path.isfile(path):
                return path
    for name in candidates:
        path = os.path.join(state_dir, name)
        if os.path.isfile(path):
            return path
    return None


def _download_temp_size(state_dir):
    """WebView2 下载中写 .crdownload 临时文件，取其大小作为进度。"""
    total = 0
    try:
        for name in os.listdir(state_dir):
            if name.endswith(".crdownload"):
                total += os.path.getsize(os.path.join(state_dir, name))
    except OSError:
        pass
    return total
