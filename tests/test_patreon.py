# -*- coding: utf-8 -*-
"""Patreon 模块纯函数测试（不触网、不依赖 pywebview）。"""

import os
import json
from types import SimpleNamespace

import pytest
from keyring.backend import KeyringBackend

from modules import config
from modules.patreon import (
    CookieStore,
    PatreonError,
    PatreonNotLoggedIn,
    _webview_proxy_arg,
    cookie_to_dict,
    extract_campaign_id,
    extract_external_links,
    is_creator_link,
    parse_campaigns_payload,
    parse_collections_payload,
    parse_posts_page,
    render_content_blocks,
    render_content_text,
    sanitize_filename,
    sort_posts,
)
from modules.source_store import save_patreon_source


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------

def test_sanitize_replaces_windows_invalid_chars():
    assert sanitize_filename('a<b>:c?*.zip') == 'a_b__c__.zip'
    assert sanitize_filename('a/b\\c') == 'a_b_c'
    assert sanitize_filename('mod | v2 (final)') == 'mod _ v2 (final)'


def test_sanitize_handles_empty_and_dots():
    assert sanitize_filename('') == 'file'
    assert sanitize_filename('...') == 'file'
    assert sanitize_filename('  ') == 'file'


def test_sanitize_truncates_long_names_keeping_extension():
    long_name = 'x' * 200 + '.zip'
    result = sanitize_filename(long_name)
    assert len(result) == 80 + 4
    assert result.endswith('.zip')
    assert result.startswith('x' * 80)


def test_sanitize_limits_extension_length():
    result = sanitize_filename('mod.' + 'a' * 30)
    assert result == 'mod.' + 'a' * 9


# ---------------------------------------------------------------------------
# extract_campaign_id
# ---------------------------------------------------------------------------

def test_extract_campaign_id_from_embedded_api_json():
    html = (
        '<html><script>{"self":"https://www.patreon.com/api/campaigns/12345",'
        '"name":"Test"}</script></html>'
    )
    assert extract_campaign_id(html) == 12345


def test_extract_campaign_id_escaped_variant():
    html = '\\"self\\":\\"https://www.patreon.com/api/campaigns/987\\"'
    assert extract_campaign_id(html) == 987


def test_extract_campaign_id_returns_none_without_match():
    assert extract_campaign_id('no campaign here') is None
    assert extract_campaign_id('https://www.patreon.com/api/posts?x=1') is None
    assert extract_campaign_id('') is None


# ---------------------------------------------------------------------------
# extract_external_links
# ---------------------------------------------------------------------------

def test_extract_external_links_from_link_blocks():
    content = json.dumps([
        {"type": "text", "content": "Download here:"},
        {"type": "link", "text": "MEGA", "url": "https://mega.nz/file/abc"},
        {"type": "link", "url": "https://drive.google.com/drive/folders/xyz"},
    ])
    assert extract_external_links(content) == [
        "https://mega.nz/file/abc",
        "https://drive.google.com/drive/folders/xyz",
    ]


def test_extract_external_links_deduplicates():
    content = json.dumps([
        {"type": "link", "url": "https://mega.nz/a"},
        {"type": "link", "url": "https://mega.nz/a"},
    ])
    assert extract_external_links(content) == ["https://mega.nz/a"]


def test_extract_external_links_tolerates_bad_json():
    assert extract_external_links('not json') == []
    assert extract_external_links(None) == []
    assert extract_external_links('') == []


# ---------------------------------------------------------------------------
# parse_posts_page
# ---------------------------------------------------------------------------

def _media_payload(media_id, name, url):
    return {
        "type": "media",
        "id": media_id,
        "attributes": {"file_name": name, "download_url": url},
    }


def _post_payload(post_id, title, attrs=None, media=None):
    relationships = {}
    if media:
        relationships["attachments_media"] = {
            "data": [{"type": "media", "id": m["id"]} for m in media]}
    post = {
        "type": "post",
        "id": post_id,
        "attributes": {
            "title": title,
            "published_at": "2026-08-01T12:00:00+00:00",
            "is_paid": True,
            "current_user_can_view": True,
            "post_file": None,
            "content_json_string": None,
            "url": "https://www.patreon.com/posts/{}".format(post_id),
        },
        "relationships": relationships,
    }
    if attrs:
        post["attributes"].update(attrs)
    return post


def test_parse_posts_page_with_attachments():
    media = [_media_payload("m1", "mod-v1.0.zip", "https://cdn.patreon.com/1.zip")]
    payload = {
        "data": [_post_payload("p1", "My Mod v1.0", media=media)],
        "included": media,
        "links": {},
    }
    posts, cursor = parse_posts_page(payload)
    assert cursor is None
    assert len(posts) == 1
    post = posts[0]
    assert post["post_id"] == "p1"
    assert post["title"] == "My Mod v1.0"
    assert post["is_paid"] is True
    assert post["can_view"] is True
    assert post["post_url"] == "https://www.patreon.com/posts/p1"
    assert post["attachments"] == [{
        "file_id": "m1", "name": "mod-v1.0.zip",
        "url": "https://cdn.patreon.com/1.zip"}]
    assert post["post_file"] is None


def test_parse_posts_page_post_file_and_cursor():
    payload = {
        "data": [_post_payload("p2", "File Post", attrs={
            "post_file": {"name": "main.pak", "url": "https://cdn.patreon.com/main.pak"},
        })],
        "included": [],
        "links": {"next": "https://www.patreon.com/api/posts?page[cursor]=abc123"},
    }
    posts, cursor = parse_posts_page(payload)
    assert cursor == "abc123"
    assert posts[0]["post_file"] == {
        "name": "main.pak", "url": "https://cdn.patreon.com/main.pak"}


def test_parse_posts_page_skips_non_post_entries():
    payload = {
        "data": [{"type": "user", "id": "u1", "attributes": {}}],
        "included": [],
        "links": {},
    }
    posts, cursor = parse_posts_page(payload)
    assert posts == [] and cursor is None


def test_parse_posts_page_missing_media_reference():
    payload = {
        "data": [_post_payload("p3", "Broken", media=[
            {"type": "media", "id": "missing"}])],
        "included": [],
        "links": {},
    }
    posts, _ = parse_posts_page(payload)
    assert posts[0]["attachments"] == []


def test_parse_posts_page_embed_and_content_links():
    payload = {
        "data": [_post_payload("p4", "With links", attrs={
            "embed": {"url": "https://youtu.be/abc"},
            "content_json_string": json.dumps([
                {"type": "link", "url": "https://mega.nz/x"}]),
        })],
        "included": [],
        "links": {},
    }
    posts, _ = parse_posts_page(payload)
    post = posts[0]
    assert post["embed_url"] == "https://youtu.be/abc"
    assert post["external_links"] == ["https://mega.nz/x"]


def _image_media(media_id, url):
    return {
        "type": "media", "id": media_id,
        "attributes": {"image_urls": {
            "url": url + "?s=url", "original": url + "?s=orig",
            "default": url + "?s=default"}},
    }


def test_parse_posts_page_cover_and_images():
    media = [_image_media("i1", "https://cdn.patreon.com/cover.png")]
    post = _post_payload("p5", "With Cover", attrs={
        "image": {"url": "https://cdn.patreon.com/cover.png?w=620",
                  "thumb_url": "https://cdn.patreon.com/cover.png?w=100"},
    })
    post["relationships"]["images"] = {"data": [{"type": "media", "id": "i1"}]}
    payload = {"data": [post], "included": media, "links": {}}
    parsed, _ = parse_posts_page(payload)
    assert parsed[0]["cover_url"] == "https://cdn.patreon.com/cover.png?w=620"
    assert parsed[0]["cover_thumb_url"] == "https://cdn.patreon.com/cover.png?w=100"
    # 图集取 original 原图（default 为方形裁剪版）
    assert parsed[0]["images"] == ["https://cdn.patreon.com/cover.png?s=orig"]


def test_parse_posts_page_missing_image_attr():
    payload = {"data": [_post_payload("p6", "No Cover")], "included": [], "links": {}}
    parsed, _ = parse_posts_page(payload)
    assert parsed[0]["cover_url"] is None
    assert parsed[0]["cover_thumb_url"] is None
    assert parsed[0]["images"] == []


def test_parse_posts_page_sparse_list_response():
    """列表瘦身后的响应：无正文/附件/外链，解析不报错且字段为空。"""
    post = _post_payload("p7", "Sparse", attrs={
        "image": {"url": "https://cdn.patreon.com/a.png",
                  "thumb_url": "https://cdn.patreon.com/a_t.png"},
    })
    del post["attributes"]["content_json_string"]
    payload = {"data": [post], "included": [], "links": {}}
    parsed, _ = parse_posts_page(payload)
    item = parsed[0]
    assert item["content_json"] is None
    assert item["attachments"] == []
    assert item["post_file"] is None
    assert item["external_links"] == []
    assert item["images"] == []
    assert item["cover_thumb_url"] == "https://cdn.patreon.com/a_t.png"


def test_parse_posts_page_single_object_data():
    """单帖端点 data 为单对象（非数组）时兼容解析。"""
    post = _post_payload("p8", "Single", attrs={
        "post_file": {"name": "mod.pak", "url": "https://cdn.patreon.com/mod.pak"},
    })
    payload = {"data": post, "included": [], "links": {}}
    parsed, _ = parse_posts_page(payload)
    assert len(parsed) == 1
    assert parsed[0]["post_file"] == {
        "name": "mod.pak", "url": "https://cdn.patreon.com/mod.pak"}


# ---------------------------------------------------------------------------
# render_content_text
# ---------------------------------------------------------------------------

def test_render_content_text_blocks():
    content = json.dumps([
        {"type": "heading", "content": "Install Guide"},
        {"type": "text", "content": "Step 1: unzip"},
        {"type": "link", "text": "MEGA", "url": "https://mega.nz/x"},
        {"type": "image", "url": "https://cdn/x.png"},
    ])
    text = render_content_text(content)
    assert "Install Guide" in text
    assert "Step 1: unzip" in text
    assert "MEGA: https://mega.nz/x" in text
    assert "cdn/x.png" not in text


def test_render_content_text_tolerates_bad_json():
    assert render_content_text("not json") == ""
    assert render_content_text(None) == ""
    assert render_content_text("") == ""
    assert render_content_text("[]") == ""


# ---------------------------------------------------------------------------
# render_content_blocks（ProseMirror doc 结构）
# ---------------------------------------------------------------------------

def _pm_doc(blocks):
    return json.dumps({"type": "doc", "content": blocks})


def test_render_content_blocks_mixed_text_and_images():
    content = _pm_doc([
        {"type": "paragraph", "content": [
            {"type": "text", "text": "First paragraph"}]},
        {"type": "image", "attrs": {
            "src": "https://cdn.patreon.com/img1.png", "media_id": "m1"}},
        {"type": "heading", "attrs": {"level": 3}, "content": [
            {"type": "text", "text": "Heading"}]},
        {"type": "paragraph", "content": []},
        {"type": "image", "attrs": {"src": "https://cdn.patreon.com/img2.png"}},
    ])
    blocks = render_content_blocks(content)
    assert blocks == [
        {"type": "text", "text": "First paragraph"},
        {"type": "image", "url": "https://cdn.patreon.com/img1.png"},
        {"type": "text", "text": "Heading"},
        {"type": "image", "url": "https://cdn.patreon.com/img2.png"},
    ]


def test_render_content_blocks_tolerates_bad_input():
    assert render_content_blocks(None) == []
    assert render_content_blocks("not json") == []
    assert render_content_blocks("[]") == []
    assert render_content_blocks(json.dumps({"type": "other"})) == []


def test_render_content_text_supports_pm_doc():
    content = _pm_doc([
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Line one"}]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Line two"}]},
    ])
    assert render_content_text(content) == "Line one\nLine two"


def test_extract_external_links_from_pm_marks():
    content = _pm_doc([
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Download "},
            {"type": "text", "text": "here",
             "marks": [{"type": "link", "attrs": {"href": "https://mega.nz/x"}}]},
        ]},
    ])
    assert extract_external_links(content) == ["https://mega.nz/x"]


# ---------------------------------------------------------------------------
# parse_campaigns_payload
# ---------------------------------------------------------------------------

def _user_payload(membership_ids, campaigns):
    """构造 /api/user 响应（includes=memberships.campaign）的标准形状。"""
    included = []
    for membership_id in membership_ids:
        included.append({
            "type": "membership",
            "id": membership_id,
            "relationships": {
                "campaign": {"data": {"type": "campaign",
                                      "id": membership_id[len("mem-"):]}},
            },
        })
    included.extend(campaigns)
    return {
        "data": [{
            "type": "user", "id": "u1",
            "relationships": {
                "memberships": {
                    "data": [{"type": "membership", "id": mid} for mid in membership_ids]},
            },
        }],
        "included": included,
    }


def test_parse_campaigns_payload_extracts_creators():
    campaign = {
        "type": "campaign", "id": "c1",
        "attributes": {"name": "Creator One", "url": "https://www.patreon.com/one",
                       "avatar_photo_url": "https://img.patreon.com/one.jpg"},
    }
    payload = _user_payload(["mem-c1"], [campaign])
    creators = parse_campaigns_payload(payload)
    assert creators == [{
        "campaign_id": "c1", "name": "Creator One",
        "url": "https://www.patreon.com/one",
        "avatar_url": "https://img.patreon.com/one.jpg"}]


def test_parse_campaigns_payload_deduplicates():
    campaign = {"type": "campaign", "id": "c2",
                "attributes": {"name": "Dupe", "url": "", "avatar_photo_url": None}}
    payload = _user_payload(["mem-c2", "mem-c2b"], [campaign])
    assert len(parse_campaigns_payload(payload)) == 1


# ---------------------------------------------------------------------------
# is_creator_link
# ---------------------------------------------------------------------------

def test_is_creator_link():
    assert is_creator_link("https://www.patreon.com/mycreator")
    assert is_creator_link("https://www.patreon.com/mycreator/posts")
    assert is_creator_link("https://www.patreon.com/user/posts?u=123")
    assert is_creator_link("https://www.patreon.com/c/creatorname")
    assert is_creator_link("https://www.patreon.com/m/creatorname")
    assert not is_creator_link("https://www.patreon.com/login")
    assert not is_creator_link("https://www.patreon.com/settings")
    assert not is_creator_link("https://www.patreon.com/explore")
    assert not is_creator_link("https://www.patreon.com/create")
    assert not is_creator_link("https://www.patreon.com/memberships")
    assert not is_creator_link("https://www.patreon.com/home")
    assert not is_creator_link("https://google.com/")
    assert not is_creator_link("")
    assert not is_creator_link("https://www.patreon.com/posts")


# ---------------------------------------------------------------------------
# cookie_to_dict
# ---------------------------------------------------------------------------

def test_cookie_to_dict():
    from http.cookies import SimpleCookie
    cookie = SimpleCookie()
    cookie["session_id"] = "abc"
    cookie["session_id"]["domain"] = ".patreon.com"
    cookie["session_id"]["path"] = "/"
    cookie["session_id"]["secure"] = True
    cookie["session_id"]["httponly"] = True
    result = cookie_to_dict(cookie)
    assert result["name"] == "session_id"
    assert result["value"] == "abc"
    assert result["domain"] == ".patreon.com"
    assert result["path"] == "/"
    assert result["secure"] is True
    assert result["httponly"] is True


def test_cookie_to_dict_empty():
    from http.cookies import SimpleCookie
    assert cookie_to_dict(SimpleCookie()) == {}


# ---------------------------------------------------------------------------
# CookieStore（keyring 使用内存假后端，隔离真实凭据管理器）
# ---------------------------------------------------------------------------

class _FakeKeyring(KeyringBackend):
    """内存版钥匙串后端（隔离真实凭据管理器）。"""

    priority = 1
    INSTANCE = None  # 供测试检查存储内容

    def __init__(self):
        self._data = {}
        type(self).INSTANCE = self

    def set_password(self, service, username, password):
        self._data[(service, username)] = password

    def get_password(self, service, username):
        return self._data.get((service, username))

    def delete_password(self, service, username):
        self._data.pop((service, username), None)


@pytest.fixture(autouse=True)
def _fake_keyring():
    import keyring
    keyring.set_keyring(_FakeKeyring())
    yield
    keyring.set_keyring(_FakeKeyring())


def test_cookie_store_roundtrip(tmp_path):
    store = CookieStore(str(tmp_path))
    assert store.load() == []
    cookies = [
        {"name": "session_id", "value": "abc", "domain": ".patreon.com",
         "path": "/", "secure": True, "httponly": True},
        {"name": "other", "value": "x", "domain": ".example.com",
         "path": "/", "secure": False, "httponly": False},
    ]
    store.save(cookies)
    assert store.load() == cookies
    header = store.header()
    assert "session_id=abc" in header
    assert "other=x" not in header  # 非 patreon 域不进入请求头


def test_cookie_store_corrupt_file(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text("{not json", encoding="utf-8")
    store = CookieStore(str(tmp_path))
    assert store.load() == []


def test_cookie_store_clear(tmp_path):
    store = CookieStore(str(tmp_path))
    store.save([{"name": "session_id", "value": "abc", "domain": ".patreon.com"}])
    store.clear()
    assert store.load() == []
    assert store.header() == ""


def test_cookie_store_saves_to_keyring_not_file(tmp_path):
    store = CookieStore(str(tmp_path))
    cookies = [{"name": "session_id", "value": "abc", "domain": ".patreon.com"}]
    store.save(cookies)
    assert not (tmp_path / "cookies.json").exists()  # 明文文件不落盘
    store2 = CookieStore(str(tmp_path))
    assert store2.load() == cookies  # 从钥匙串读回


def test_cookie_store_migrates_legacy_file(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps(
        [{"name": "session_id", "value": "old", "domain": ".patreon.com"}],
        ensure_ascii=False), encoding="utf-8")
    store = CookieStore(str(tmp_path))
    assert store.load() == [
        {"name": "session_id", "value": "old", "domain": ".patreon.com"}]
    assert not path.exists()  # 迁移后删除明文文件
    assert store.load() == [  # 二次加载从钥匙串
        {"name": "session_id", "value": "old", "domain": ".patreon.com"}]


def test_cookie_store_falls_back_to_file_when_keyring_broken(tmp_path, monkeypatch):
    import modules.patreon as patreon_mod

    def broken_keyring(*_a):
        class _Broken:
            @staticmethod
            def get_password(*_a):
                raise RuntimeError("backend unavailable")

            @staticmethod
            def set_password(*_a):
                raise RuntimeError("backend unavailable")

            @staticmethod
            def delete_password(*_a):
                raise RuntimeError("backend unavailable")

        return _Broken()

    monkeypatch.setattr(patreon_mod.CookieStore, "_keyring", broken_keyring)
    store = CookieStore(str(tmp_path))
    cookies = [{"name": "session_id", "value": "abc", "domain": ".patreon.com"}]
    store.save(cookies)
    assert store.load() == cookies  # 从文件读回
    assert (tmp_path / "cookies.json").exists()


def test_cookie_store_large_payload_splits_into_chunks(tmp_path):
    """大 cookie 集分块存入多条钥匙串凭据并完整读回（凭据管理器单条容量有限）。"""
    store = CookieStore(str(tmp_path))
    cookies = [{"name": "k%d" % i, "value": "v" * 100, "domain": ".patreon.com"}
               for i in range(200)]  # JSON 约 30KB，远超单条凭据上限
    store.save(cookies)
    assert not (tmp_path / "cookies.json").exists()
    chunks = [v for (k, v) in _FakeKeyring.INSTANCE._data.items()
              if k[1].startswith("cookies.")]
    assert len(chunks) > 1  # 确实分块了
    assert store.load() == cookies


def test_cookie_store_over_cap_falls_back_to_file(tmp_path):
    """超过分块防御上限（64 块 ≈ 51KB）时回退明文文件。"""
    store = CookieStore(str(tmp_path))
    cookies = [{"name": "k%d" % i, "value": "v" * 100, "domain": ".patreon.com"}
               for i in range(700)]  # JSON 约 100KB
    store.save(cookies)
    assert (tmp_path / "cookies.json").exists()
    assert store.load() == cookies


# ---------------------------------------------------------------------------
# _webview_proxy_arg
# ---------------------------------------------------------------------------

def test_webview_proxy_arg_returns_none_when_unsupported():
    assert _webview_proxy_arg("") is None
    assert _webview_proxy_arg(None) is None
    assert _webview_proxy_arg("   ") is None
    assert _webview_proxy_arg("socks5://127.0.0.1:7890") is None
    assert _webview_proxy_arg("http://user:pass@127.0.0.1:7897") is None
    assert _webview_proxy_arg("abc") is None
    assert _webview_proxy_arg("http://proxy.example.com") is None
    assert _webview_proxy_arg("http://127.0.0.1:abc") is None
    assert _webview_proxy_arg("http://127.0.0.1:99999") is None


def test_webview_proxy_arg_builds_switch():
    assert _webview_proxy_arg("http://127.0.0.1:7897") == \
        "--proxy-server=http://127.0.0.1:7897"
    assert _webview_proxy_arg("https://proxy.example.com:8080") == \
        "--proxy-server=https://proxy.example.com:8080"
    assert _webview_proxy_arg("127.0.0.1:7897") == \
        "--proxy-server=http://127.0.0.1:7897"
    assert _webview_proxy_arg("http://[::1]:7897") == \
        "--proxy-server=http://[::1]:7897"


# ---------------------------------------------------------------------------
# PatreonSession httpx 层（不触网，monkeypatch httpx）
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, payload=None, text="{}"):
        self.status_code = status_code
        self._payload = payload
        self._text = text

    def json(self):
        if self._payload is not None:
            return self._payload
        import json as _json
        return _json.loads(self._text)


def test_http_json_401_raises_not_logged_in(tmp_path, monkeypatch):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()

    def fake_get(url, headers=None, timeout=None, follow_redirects=True, proxy=None):
        return _FakeResponse(401)

    monkeypatch.setattr("httpx.get", fake_get)
    with pytest.raises(PatreonNotLoggedIn):
        session._http_json("/current_user")


def test_http_json_ok_returns_payload(tmp_path, monkeypatch):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()
    session._cookie_store.save([
        {"name": "session_id", "value": "abc", "domain": ".patreon.com"}])

    def fake_get(url, headers=None, timeout=None, follow_redirects=True, proxy=None):
        assert "session_id=abc" in (headers or {}).get("Cookie", "")
        return _FakeResponse(200, {"data": {"id": "u1", "type": "user"}})

    monkeypatch.setattr("httpx.get", fake_get)
    payload = session._http_json("/current_user")
    assert payload["data"]["id"] == "u1"


def test_is_logged_in_uses_httpx(tmp_path, monkeypatch):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()

    monkeypatch.setattr(
        "httpx.get",
        lambda *a, **k: _FakeResponse(401))
    assert session.is_logged_in() is False

    monkeypatch.setattr(
        "httpx.get",
        lambda *a, **k: _FakeResponse(200, {"data": {"id": "u1"}}))
    assert session.is_logged_in() is True


def test_close_browser_idempotent(tmp_path):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()
    session.close()
    session.close()  # 二次关闭不抛异常
    assert session._thread is None


# ---------------------------------------------------------------------------
# _browser_logged_in / ensure_login（登录等待循环）
# ---------------------------------------------------------------------------

class _FakeClosedEvent:
    def __init__(self):
        self._handlers = []

    def __iadd__(self, handler):
        self._handlers.append(handler)
        return self

    def fire(self):
        for handler in list(self._handlers):
            handler()


class _FakeLoginWin:
    def __init__(self):
        self.events = SimpleNamespace(closed=_FakeClosedEvent())

    def show(self):
        pass

    def hide(self):
        pass


def _session_with_fake_browser(tmp_path):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()
    session._thread = object()
    session._closed_flag = False
    session._login_win = _FakeLoginWin()
    session._ensure_browser = lambda: None
    session._close_browser = lambda *a, **k: None
    return session


def test_browser_logged_in_true_when_data_present(tmp_path, monkeypatch):
    session = _session_with_fake_browser(tmp_path)
    monkeypatch.setattr(
        session, "_browser_json",
        lambda *a, **k: {"data": {"id": "u1", "type": "user"}})
    assert session._browser_logged_in() is True


def test_browser_logged_in_false_when_error_payload(tmp_path, monkeypatch):
    session = _session_with_fake_browser(tmp_path)
    monkeypatch.setattr(
        session, "_browser_json",
        lambda *a, **k: {"errors": [{"code_name": "LoginRequired"}]})
    assert session._browser_logged_in() is False


def test_browser_logged_in_false_on_bridge_error(tmp_path, monkeypatch):
    session = _session_with_fake_browser(tmp_path)

    def boom(*a, **k):
        raise PatreonError("Patreon 页面无响应")

    monkeypatch.setattr(session, "_browser_json", boom)
    assert session._browser_logged_in() is False


def test_ensure_login_exports_cookies_then_httpx_verifies(tmp_path, monkeypatch):
    session = _session_with_fake_browser(tmp_path)
    state = {"httpx_logged": False}

    monkeypatch.setattr(session, "is_logged_in", lambda: state["httpx_logged"])
    monkeypatch.setattr(session, "_browser_logged_in", lambda *a, **k: True)

    def fake_export():
        state["httpx_logged"] = True

    monkeypatch.setattr(session, "_export_cookies", fake_export)

    assert session.ensure_login(timeout=5, poll_interval=0.05) is True
    assert state["httpx_logged"] is True


def test_ensure_login_timeout_returns_false(tmp_path, monkeypatch):
    session = _session_with_fake_browser(tmp_path)

    monkeypatch.setattr(session, "is_logged_in", lambda: False)
    monkeypatch.setattr(session, "_browser_logged_in", lambda *a, **k: False)

    assert session.ensure_login(timeout=0.3, poll_interval=0.05) is False


def test_ensure_login_aborts_when_window_closed(tmp_path, monkeypatch):
    session = _session_with_fake_browser(tmp_path)

    monkeypatch.setattr(session, "is_logged_in", lambda: False)

    def fake_check(*a, **k):
        session._login_win.events.closed.fire()
        return False

    monkeypatch.setattr(session, "_browser_logged_in", fake_check)

    assert session.ensure_login(timeout=5, poll_interval=0.05) is False


def test_ensure_login_already_logged_in_skips_browser(tmp_path, monkeypatch):
    session = _session_with_fake_browser(tmp_path)
    monkeypatch.setattr(session, "is_logged_in", lambda: True)
    monkeypatch.setattr(session, "_ensure_browser", lambda: (_ for _ in ()).throw(AssertionError("不应启动浏览器")))

    assert session.ensure_login(timeout=5, poll_interval=0.05) is True


def _posts_payload(entries, next_cursor=None, total=233):
    payload = {
        "data": [],
        "included": [],
        "meta": {"pagination": {"total": total}},
    }
    if next_cursor:
        payload["links"] = {
            "next": "https://www.patreon.com/api/posts?page%5Bcursor%5D=" + next_cursor}
    for index in range(entries):
        payload["data"].append({
            "type": "post", "id": "p%d" % index,
            "attributes": {"title": "Post %d" % index}})
    return payload


def test_creator_posts_single_page_with_cursor(tmp_path, monkeypatch):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()
    seen_urls = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=True, proxy=None):
        seen_urls.append(url)
        if "page%5Bcursor%5D=c2" in url:
            return _FakeResponse(200, _posts_payload(5, None, 233))
        return _FakeResponse(200, _posts_payload(30, "c2", 233))

    monkeypatch.setattr("httpx.get", fake_get)

    posts, cursor, total = session.creator_posts(14830458)
    assert len(posts) == 30
    assert cursor == "c2"
    assert total == 233
    assert "page%5Bcount%5D=30" in seen_urls[0]

    posts2, cursor2, total2 = session.creator_posts(14830458, cursor="c2")
    assert len(posts2) == 5
    assert cursor2 is None
    assert total2 == 233
    assert "page%5Bcursor%5D=c2" in seen_urls[1]


def test_creator_posts_total_missing(tmp_path, monkeypatch):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()

    payload = _posts_payload(2, None, 233)
    payload["meta"] = {}
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: _FakeResponse(200, payload))

    posts, cursor, total = session.creator_posts(14830458)
    assert len(posts) == 2
    assert cursor is None
    assert total is None


def test_creator_posts_sort_parameter(tmp_path, monkeypatch):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()
    seen_urls = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=True, proxy=None):
        seen_urls.append(url)
        return _FakeResponse(200, _posts_payload(3, None, 100))

    monkeypatch.setattr("httpx.get", fake_get)

    session.creator_posts(14830458)
    assert "sort=-published_at" in seen_urls[0]

    session.creator_posts(14830458, sort="-like_count")
    assert "sort=-like_count" in seen_urls[1]


# ---------------------------------------------------------------------------
# sort_posts（合集本地排序）
# ---------------------------------------------------------------------------

def _sortable_post(post_id, published_at, like_count):
    return {"post_id": post_id, "published_at": published_at,
            "like_count": like_count}


def test_sort_posts_latest_by_published_desc():
    posts = [
        _sortable_post("a", "2026-08-01T10:00:00+00:00", 1),
        _sortable_post("b", "2026-08-05T10:00:00+00:00", 1),
        _sortable_post("c", "2026-08-03T10:00:00+00:00", 1),
    ]
    result = sort_posts(posts, "-published_at")
    assert [p["post_id"] for p in result] == ["b", "c", "a"]


def test_sort_posts_popular_by_like_desc():
    posts = [
        _sortable_post("a", "2026-08-01", 5),
        _sortable_post("b", "2026-08-05", 100),
        _sortable_post("c", "2026-08-03", 30),
    ]
    result = sort_posts(posts, "-like_count")
    assert [p["post_id"] for p in result] == ["b", "c", "a"]


def test_sort_posts_tolerates_missing_fields():
    posts = [
        {"post_id": "a", "published_at": None, "like_count": None},
        {"post_id": "b", "published_at": "2026-08-01", "like_count": 10},
        {"post_id": "c"},
    ]
    result = sort_posts(posts, "-published_at")
    assert len(result) == 3
    assert result[0]["post_id"] == "b"
    result2 = sort_posts(posts, "-like_count")
    assert result2[0]["post_id"] == "b"


def test_parse_collections_payload_keeps_like_count():
    payload = _collection_payload(
        [("col1", "Mods", ["p1"])],
        [("p1", "Mod A", True)],
    )
    # 给帖子补充 like_count 属性
    for entry in payload["included"]:
        if entry.get("type") == "post":
            entry["attributes"]["like_count"] = 42
    _collections, posts_map = parse_collections_payload(payload)
    assert posts_map["p1"]["like_count"] == 42

def _collection_payload(collections, posts):
    included = []
    for post in posts:
        included.append({
            "type": "post", "id": post[0],
            "attributes": {"title": post[1],
                           "current_user_can_view": post[2],
                           "is_paid": False, "image": None,
                           "url": "https://www.patreon.com/posts/%s" % post[0]},
            "relationships": {},
        })
    for coll in collections:
        included.append({
            "type": "collection", "id": coll[0],
            "attributes": {"title": coll[1], "url": ""},
            "relationships": {
                "posts": {"data": [
                    {"type": "post", "id": pid} for pid in coll[2]]}},
        })
    return {
        "data": {"id": "c1", "type": "campaign", "attributes": {},
                 "relationships": {}},
        "included": included,
    }


def test_parse_collections_payload():
    payload = _collection_payload(
        [("col1", "Mods", ["p1", "p2"]), ("col2", "Polls", ["p3"])],
        [("p1", "Mod A", True), ("p2", "Mod B", False), ("p3", "Poll", True)],
    )
    collections, posts_map = parse_collections_payload(payload)
    assert [c["id"] for c in collections] == ["col1", "col2"]
    assert collections[0]["title"] == "Mods"
    assert collections[0]["post_ids"] == ["p1", "p2"]
    assert posts_map["p1"]["title"] == "Mod A"
    assert posts_map["p1"]["can_view"] is True
    assert posts_map["p2"]["can_view"] is False
    # 合集接口不含正文/附件（列表字段）
    assert posts_map["p1"]["attachments"] == []
    assert posts_map["p1"]["content_json"] is None


def test_parse_collections_payload_keeps_all_refs():
    """轻量模式（不带 .posts）无帖子条目时，保留原始 id 供合集计数。"""
    payload = _collection_payload(
        [("col1", "Mods", ["p1", "missing"])],
        [("p1", "Mod A", True)],
    )
    collections, posts_map = parse_collections_payload(payload)
    assert collections[0]["post_ids"] == ["p1", "missing"]
    assert "missing" not in posts_map


def test_campaign_collections_uses_include(tmp_path, monkeypatch):
    from modules.patreon import PatreonSession

    session = PatreonSession(str(tmp_path / "profile"), str(tmp_path / "dl"))
    session.start()
    seen_urls = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=True, proxy=None):
        seen_urls.append(url)
        return _FakeResponse(200, _collection_payload([], []))

    monkeypatch.setattr("httpx.get", fake_get)

    session.campaign_collections(14830458, with_posts=True)
    assert "include=collections.posts" in seen_urls[0]

    session.campaign_collections(14830458, with_posts=False)
    assert "include=collections" in seen_urls[1]
    assert "collections.posts" not in seen_urls[1]


# ---------------------------------------------------------------------------
# save_patreon_source
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    config_path = tmp_path / "mod_manager_config.json"
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))
    return config_path


def test_save_patreon_source_records_provider(tmp_path, isolated_config):
    mod_path = tmp_path / "Mods" / "MyPatreonMod"
    mod_path.mkdir(parents=True)
    post = {"post_id": "p1", "title": "My Mod",
            "post_url": "https://www.patreon.com/posts/p1"}
    attachment = {"file_id": "m1", "name": "mod.zip", "url": "https://cdn/x.zip"}

    record = save_patreon_source(str(mod_path), "c1", post, attachment)

    assert record["provider"] == "patreon"
    assert record["campaign_id"] == "c1"
    assert record["post_id"] == "p1"
    assert record["file_id"] == "m1"
    assert record["file_name"] == "mod.zip"
    assert record["folder_name"] == "MyPatreonMod"
    stored = config.ConfigManager.load()["installed_sources"][record["instance_id"]]
    assert stored == record
    manifest = json.loads(
        (mod_path / ".efmi_mod_manager" / "source.json").read_text(encoding="utf-8"))
    assert manifest["provider"] == "patreon"
