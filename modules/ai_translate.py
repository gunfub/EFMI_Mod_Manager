# -*- coding: utf-8 -*-
"""AI 翻译（OpenAI 兼容接口）：纯逻辑，httpx 实现，可单测。

- translate_text：POST {base}/chat/completions，404 时回退 {base}/v1/
- list_models：GET {base}/models，404 时回退 {base}/v1/models
- API key 存系统钥匙串（服务名带 EFMI_Mod_Manager 前缀），不可用时
  回退配置文件字段（与 CookieStore 同策略）
"""

from modules.config import ConfigManager

_KEYRING_SERVICE = "EFMI_Mod_Manager.AI"
_KEYRING_USER = "api_key"
_MAX_TEXT_CHARS = 8000
_TIMEOUT = 30.0
_MODEL_TIMEOUT = 15.0

_TARGET_LANG_NAMES = {
    "zh": "简体中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}


class AiTranslateError(Exception):
    """AI 翻译功能错误（消息已面向用户）。"""


def normalize_base_url(base):
    """清洗 base url：去首尾空白与末尾斜杠。"""
    base = (base or "").strip().rstrip("/")
    return base


def target_lang_name(lang):
    """语言代码 → 目标语言名（供 system 提示词使用）。"""
    return _TARGET_LANG_NAMES.get(lang, "English")


def _endpoint_candidates(base, path):
    """同一 base 下可能的端点：{base}{path} 与 {base}/v1{path}。"""
    return [base + path, base + "/v1" + path]


def _request_json(url, api_key, payload=None, timeout=_TIMEOUT):
    import httpx

    proxy = ConfigManager.get_proxy() or None
    headers = {"Authorization": "Bearer " + (api_key or "")}
    try:
        if payload is None:
            response = httpx.get(url, headers=headers, timeout=timeout, proxy=proxy)
        else:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=timeout, proxy=proxy)
    except httpx.TimeoutException:
        raise AiTranslateError("请求超时，请检查网络或服务地址")
    except httpx.RequestError:
        raise AiTranslateError("网络请求失败，请检查 base url 与网络连接")
    return response


def translate_text(base_url, api_key, model, text, target_lang):
    """将 text 翻译为目标语言，返回译文（失败抛 AiTranslateError）。"""
    base = normalize_base_url(base_url)
    if not base:
        raise AiTranslateError("未配置 AI 服务地址（base url）")
    if not api_key:
        raise AiTranslateError("未配置 API key")
    if not model:
        raise AiTranslateError("未配置模型名称")
    text = (text or "").strip()
    if not text:
        raise AiTranslateError("没有可翻译的内容")
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS]

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专业翻译。请将用户提供的文本翻译为{}，"
                    "只输出译文，不要解释、不要附加任何内容。"
                ).format(target_lang_name(target_lang)),
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
    }
    last_error = None
    for url in _endpoint_candidates(base, "/chat/completions"):
        response = _request_json(url, api_key, payload=payload)
        if response.status_code == 404:
            last_error = "404 Not Found"
            continue
        if response.status_code == 401 or response.status_code == 403:
            raise AiTranslateError("API key 无效或无权限（HTTP {}）".format(
                response.status_code))
        if response.status_code != 200:
            raise AiTranslateError("接口返回错误：HTTP {}".format(
                response.status_code))
        try:
            data = response.json()
        except ValueError:
            raise AiTranslateError("接口返回内容无法解析")
        content = (
            (data.get("choices") or [{}])[0]
            .get("message", {}).get("content")
        )
        if not content or not content.strip():
            raise AiTranslateError("接口未返回译文内容")
        return content.strip()
    raise AiTranslateError("接口地址不正确（HTTP 404），请检查 base url")


def list_models(base_url, api_key):
    """获取可用模型 id 列表（失败抛 AiTranslateError）。"""
    base = normalize_base_url(base_url)
    if not base:
        raise AiTranslateError("未配置 AI 服务地址（base url）")
    if not api_key:
        raise AiTranslateError("未配置 API key")
    last_error = None
    for url in _endpoint_candidates(base, "/models"):
        response = _request_json(url, api_key, timeout=_MODEL_TIMEOUT)
        if response.status_code == 404:
            last_error = "404 Not Found"
            continue
        if response.status_code != 200:
            raise AiTranslateError("获取模型列表失败：HTTP {}".format(
                response.status_code))
        try:
            data = response.json()
        except ValueError:
            raise AiTranslateError("模型列表响应无法解析")
        ids = [item.get("id") for item in data.get("data") or []
               if isinstance(item, dict) and item.get("id")]
        if not ids:
            raise AiTranslateError("模型列表为空")
        return sorted(ids)
    raise AiTranslateError("接口地址不正确（HTTP 404），请检查 base url")


# ---------------------------------------------------------------------------
# API key 持久化：keyring 优先，回退配置文件
# ---------------------------------------------------------------------------

def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def get_ai_api_key():
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if value:
                return value
        except Exception:
            pass
    return ConfigManager.load().get("ai_api_key", "")


def set_ai_api_key(api_key):
    api_key = (api_key or "").strip()
    kr = _keyring()
    if kr is not None:
        try:
            if api_key:
                kr.set_password(_KEYRING_SERVICE, _KEYRING_USER, api_key)
            else:
                kr.delete_password(_KEYRING_SERVICE, _KEYRING_USER)
            return  # keyring 成功即不落明文
        except Exception:
            pass
    config = ConfigManager.load()
    if api_key:
        config["ai_api_key"] = api_key
    else:
        config.pop("ai_api_key", None)
    ConfigManager.save(config)
