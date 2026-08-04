import json

import pytest

from modules.gb_category_i18n import GBCategoryI18n


class FakeResponse:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code

    def iter_bytes(self, _chunk_size=None):
        yield self.content


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, method, url, follow_redirects=None):
        self.calls.append((url, follow_redirects))
        response = self.responses.pop(0)

        class _Context:
            def __init__(self, resp):
                self._resp = resp

            def __enter__(self):
                return self._resp

            def __exit__(self, *_exc):
                return False

        return _Context(response)

    def close(self):
        pass


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _fresh(tmp_path, bundled=None, cached=None, url="https://raw.githubusercontent.com/owner/repo/main/locales/category_translations/gb_category_names.json"):
    bundled_path = tmp_path / "bundled.json"
    cache_path = tmp_path / "cache.json"
    if bundled is not None:
        _write(bundled_path, bundled)
    if cached is not None:
        _write(cache_path, cached)
    return GBCategoryI18n(
        bundled_path=str(bundled_path), cache_path=str(cache_path), url=url)


def test_translate_returns_translation_for_known_id(tmp_path):
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}})
    assert i18n.translate(35464, "Skins", "zh") == "皮肤"
    assert i18n.translate("35464", "Skins", "zh") == "皮肤"


def test_translate_falls_back_to_english_for_unknown_id(tmp_path):
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}})
    assert i18n.translate(9999, "Operators", "zh") == "Operators"


def test_translate_falls_back_to_english_for_missing_lang_key(tmp_path):
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}})
    assert i18n.translate(35464, "Skins", "ja") == "Skins"


def test_load_prefers_cache_over_bundled(tmp_path):
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}},
                  cached={"42770": {"zh": "干员"}})
    assert i18n.translate(42770, "Operators", "zh") == "干员"
    assert i18n.translate(35464, "Skins", "zh") == "Skins"


def test_load_ignores_bad_bundled_file(tmp_path):
    bad = tmp_path / "bundled.json"
    bad.write_text("{not json", encoding="utf-8")
    i18n = GBCategoryI18n(bundled_path=str(bad), cache_path=str(tmp_path / "cache.json"))
    assert i18n.translate(1, "Anything", "zh") == "Anything"


def test_refresh_success_writes_cache_and_switches_data(tmp_path):
    payload = {"42770": {"zh": "干员"}}
    client = FakeClient([
        FakeResponse(content=json.dumps(payload).encode("utf-8"))])
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}})

    assert i18n.refresh(client=client) is None
    assert i18n.translate(42770, "Operators", "zh") == "干员"
    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert cache == payload
    assert client.calls[0][0].startswith("https://raw.githubusercontent.com/")


def test_refresh_keeps_old_data_on_bad_json(tmp_path):
    client = FakeClient([FakeResponse(content=b"{broken")])
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}})

    error = i18n.refresh(client=client)

    assert error is not None
    assert i18n.translate(35464, "Skins", "zh") == "皮肤"
    assert not (tmp_path / "cache.json").exists()


def test_refresh_keeps_old_data_on_wrong_structure(tmp_path):
    client = FakeClient([FakeResponse(content=json.dumps({"35464": "皮肤"}).encode("utf-8"))])
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}})

    error = i18n.refresh(client=client)

    assert error is not None
    assert i18n.translate(35464, "Skins", "zh") == "皮肤"


def test_refresh_rejects_oversized_file(tmp_path):
    client = FakeClient([FakeResponse(content=b"x" * (1024 * 1024 + 1))])
    i18n = _fresh(tmp_path)

    assert i18n.refresh(client=client) is not None


def test_refresh_rejects_untrusted_host(tmp_path):
    i18n = _fresh(tmp_path, url="https://evil.example/gb_category_names.json")
    error = i18n.refresh(client=FakeClient([]))
    assert "不受信任" in error


def test_refresh_handles_http_error_status(tmp_path):
    client = FakeClient([FakeResponse(status_code=404)])
    i18n = _fresh(tmp_path, bundled={"35464": {"zh": "皮肤"}})

    error = i18n.refresh(client=client)

    assert "404" in error
    assert i18n.translate(35464, "Skins", "zh") == "皮肤"
