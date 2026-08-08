# -*- coding: utf-8 -*-
"""AI 翻译模块测试（monkeypatch httpx，不触网）。"""

import pytest

from modules import config
from modules.ai_translate import (
    AiTranslateError,
    get_ai_api_key,
    list_models,
    normalize_base_url,
    set_ai_api_key,
    target_lang_name,
    translate_text,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _monkeypatch_httpx(monkeypatch, handler):
    import httpx

    def fake_get(url, headers=None, timeout=None, proxy=None):
        return handler(url, headers=headers)

    def fake_post(url, headers=None, json=None, timeout=None, proxy=None):
        return handler(url, headers=headers, payload=json)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)


def test_normalize_base_url():
    assert normalize_base_url("  https://api.openai.com/v1/  ") == "https://api.openai.com/v1"
    assert normalize_base_url("https://api.deepseek.com") == "https://api.deepseek.com"
    assert normalize_base_url("") == ""


def test_target_lang_name():
    assert target_lang_name("zh") == "简体中文"
    assert target_lang_name("en") == "English"
    assert target_lang_name("ja") == "日本語"
    assert target_lang_name("ko") == "한국어"
    assert target_lang_name("fr") == "English"


def test_translate_text_request_shape(monkeypatch):
    captured = {}

    def handler(url, headers=None, payload=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return _FakeResponse(200, {
            "choices": [{"message": {"content": " 你好，世界 "}}]})

    _monkeypatch_httpx(monkeypatch, handler)
    result = translate_text("https://api.openai.com/v1", "sk-test", "gpt-4o-mini",
                            "Hello world", "zh")
    assert result == "你好，世界"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["payload"]["model"] == "gpt-4o-mini"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert "简体中文" in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["messages"][-1]["content"] == "Hello world"


def test_translate_text_falls_back_to_v1_on_404(monkeypatch):
    urls = []

    def handler(url, headers=None, payload=None):
        urls.append(url)
        if url.endswith("/v1/chat/completions"):
            return _FakeResponse(200, {
                "choices": [{"message": {"content": "译文"}}]})
        return _FakeResponse(404, {})

    _monkeypatch_httpx(monkeypatch, handler)
    result = translate_text("https://api.deepseek.com", "sk-x", "deepseek-chat",
                            "text", "en")
    assert result == "译文"
    assert urls == [
        "https://api.deepseek.com/chat/completions",
        "https://api.deepseek.com/v1/chat/completions",
    ]


def test_translate_text_errors(monkeypatch):
    def handler(url, headers=None, payload=None):
        return _FakeResponse(401, {})

    _monkeypatch_httpx(monkeypatch, handler)
    with pytest.raises(AiTranslateError, match="API key"):
        translate_text("https://x.com/v1", "bad", "m", "t", "zh")


def test_translate_text_missing_config():
    with pytest.raises(AiTranslateError, match="base url"):
        translate_text("", "key", "m", "t", "zh")
    with pytest.raises(AiTranslateError, match="API key"):
        translate_text("https://x.com/v1", "", "m", "t", "zh")
    with pytest.raises(AiTranslateError, match="模型"):
        translate_text("https://x.com/v1", "key", "", "t", "zh")
    with pytest.raises(AiTranslateError, match="没有可翻译"):
        translate_text("https://x.com/v1", "key", "m", "  ", "zh")


def test_translate_text_empty_response(monkeypatch):
    def handler(url, headers=None, payload=None):
        return _FakeResponse(200, {"choices": [{"message": {"content": "  "}}]})

    _monkeypatch_httpx(monkeypatch, handler)
    with pytest.raises(AiTranslateError, match="未返回译文"):
        translate_text("https://x.com/v1", "k", "m", "t", "zh")


def test_translate_text_timeout_maps_to_friendly(monkeypatch):
    import httpx

    def boom(*_a, **_k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(AiTranslateError, match="超时"):
        translate_text("https://x.com/v1", "k", "m", "t", "zh")


def test_list_models(monkeypatch):
    def handler(url, headers=None, payload=None):
        return _FakeResponse(200, {"data": [
            {"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "gpt-4.1"}]})

    _monkeypatch_httpx(monkeypatch, handler)
    assert list_models("https://api.openai.com/v1", "sk") == [
        "gpt-4.1", "gpt-4o", "gpt-4o-mini"]


def test_list_models_falls_back_to_v1(monkeypatch):
    urls = []

    def handler(url, headers=None, payload=None):
        urls.append(url)
        if url.endswith("/v1/models"):
            return _FakeResponse(200, {"data": [{"id": "llama3"}]})
        return _FakeResponse(404, {})

    _monkeypatch_httpx(monkeypatch, handler)
    assert list_models("https://localhost:11434", "k") == ["llama3"]
    assert urls == ["https://localhost:11434/models",
                    "https://localhost:11434/v1/models"]


def test_list_models_requires_config():
    with pytest.raises(AiTranslateError, match="base url"):
        list_models("", "k")
    with pytest.raises(AiTranslateError, match="API key"):
        list_models("https://x.com", "")


# ---------------------------------------------------------------------------
# API key 存取：keyring 优先，回退配置文件
# ---------------------------------------------------------------------------

class _FakeKeyring:
    def __init__(self):
        self._data = {}

    def set_password(self, service, username, password):
        self._data[(service, username)] = password

    def get_password(self, service, username):
        return self._data.get((service, username))

    def delete_password(self, service, username):
        self._data.pop((service, username), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr("modules.ai_translate._keyring", lambda: fake)
    return fake


def test_api_key_roundtrip_via_keyring(tmp_path, monkeypatch, fake_keyring):
    config_path = tmp_path / "cfg.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    set_ai_api_key("sk-secret")
    assert fake_keyring._data == {("EFMI_Mod_Manager.AI", "api_key"): "sk-secret"}
    assert get_ai_api_key() == "sk-secret"
    assert "ai_api_key" not in config.ConfigManager.load()  # 不落明文

    set_ai_api_key("")
    assert fake_keyring._data == {}
    assert get_ai_api_key() == ""


def test_api_key_falls_back_to_config(tmp_path, monkeypatch):
    config_path = tmp_path / "cfg.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr("modules.ai_translate._keyring", lambda: None)

    set_ai_api_key("sk-fallback")
    assert get_ai_api_key() == "sk-fallback"
    assert config.ConfigManager.load().get("ai_api_key") == "sk-fallback"

    set_ai_api_key("")
    assert get_ai_api_key() == ""
    assert "ai_api_key" not in config.ConfigManager.load()


def test_ai_config_roundtrip(tmp_path, monkeypatch):
    config_path = tmp_path / "cfg.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))

    assert config.ConfigManager.get_ai_base_url() == ""
    assert config.ConfigManager.get_ai_model() == ""
    config.ConfigManager.set_ai_base_url(" https://api.deepseek.com ")
    config.ConfigManager.set_ai_model("deepseek-chat")
    assert config.ConfigManager.get_ai_base_url() == "https://api.deepseek.com"
    assert config.ConfigManager.get_ai_model() == "deepseek-chat"
