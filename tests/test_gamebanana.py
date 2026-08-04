import hashlib
import json

import pytest

from modules.gamebanana import (
    DownloadValidationError,
    GameBananaClient,
    GameBananaError,
    RemoteCategory,
    _category_filter,
    _mod,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None, body=b""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def json(self):
        return self._payload

    def iter_bytes(self, _chunk_size):
        yield self._body


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, follow_redirects=None):
        self.calls.append((url, params, follow_redirects))
        return self.responses.pop(0)

    def stream(self, method, url, follow_redirects=None, **kwargs):
        self.calls.append((url, None, follow_redirects))
        return self.responses.pop(0)

    def close(self):
        pass


def test_browse_maps_query_and_response_metadata():
    payload = {
        "_aMetadata": {"_nRecordCount": 2, "_nPerpage": 15, "_bIsComplete": True},
        "_aRecords": [{
            "_idRow": 7, "_sName": "Demo", "_sProfileUrl": "https://gamebanana.com/mods/7",
            "_sVersion": "", "_bHasFiles": True, "_bIsObsolete": False,
            "_aPreviewMedia": {"_aImages": [{
                "_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
                "_sFile": "full.jpg", "_sFile220": "thumb.jpg",
                "_wFile220": 220, "_hFile220": 120,
            }]},
        }],
    }
    fake = FakeClient([FakeResponse(payload)])
    page = GameBananaClient(fake).browse(page=2, query="  demo  ")

    assert page.per_page == 15
    assert page.items[0].version is None
    assert page.items[0].images[0].thumbnail_url.endswith("/thumb.jpg")
    assert fake.calls[0][1]["_sSearchString"] == "demo"
    assert fake.calls[0][1]["_nPage"] == 2


def test_details_maps_active_and_archived_files():
    payload = {
        "_idRow": 8, "_sName": "Demo", "_sProfileUrl": "https://gamebanana.com/mods/8",
        "_sDescription": "<p>Hello<br>world</p>", "_aFiles": [{
            "_idRow": 80, "_sFile": "demo.zip", "_nFilesize": 3,
            "_tsDateAdded": 10, "_sDownloadUrl": "https://gamebanana.com/dl/80",
            "_sMd5Checksum": "900150983cd24fb0d6963f7d28e17f72",
        }], "_aArchivedFiles": [{
            "_idRow": 81, "_sFile": "old.zip", "_nFilesize": 3,
            "_tsDateAdded": 5, "_sDownloadUrl": "https://gamebanana.com/dl/81",
        }],
    }
    client = GameBananaClient(FakeClient([FakeResponse(payload)]))
    details = client.details(8)

    assert details.description == "Hello\nworld"
    assert details.files[0].md5 == "900150983cd24fb0d6963f7d28e17f72"
    assert details.archived_files[0].archived is True


def test_download_accepts_gamebanana_cdn_redirect_and_validates_md5(tmp_path):
    body = b"abc"
    fake = FakeClient([
        FakeResponse(status_code=302, headers={"location": "https://files.gamebanana.com/mods/demo.zip"}),
        FakeResponse(status_code=302, headers={"location": "https://filecache38.gamebanana.com/mods/demo.zip"}),
        FakeResponse(status_code=200, body=body),
    ])
    client = GameBananaClient(fake)
    remote = type("File", (), {
        "id": 9, "download_url": "https://gamebanana.com/dl/9", "size": len(body),
        "md5": hashlib.md5(body).hexdigest(),
    })()
    destination = tmp_path / "demo.zip"

    result = client.download(remote, str(destination))

    assert result == str(destination)
    assert destination.read_bytes() == body
    assert len(fake.calls) == 3


def test_download_reports_streaming_progress(tmp_path):
    body = b"0123456789"
    fake = FakeClient([FakeResponse(status_code=200, body=body)])
    client = GameBananaClient(fake)
    remote = type("File", (), {
        "id": 12, "download_url": "https://gamebanana.com/dl/12", "size": len(body),
        "md5": None,
    })()
    progress = []

    result = client.download(
        remote, str(tmp_path / "demo.zip"),
        progress_callback=lambda done, total: progress.append((done, total)))

    assert result == str(tmp_path / "demo.zip")
    assert progress == [(len(body), len(body))]
    assert fake.calls[0][0] == "https://gamebanana.com/dl/12"


def test_download_rejects_untrusted_redirect_and_cleans_partial(tmp_path):
    fake = FakeClient([FakeResponse(status_code=302, headers={"location": "https://evil.example/demo.zip"})])
    client = GameBananaClient(fake)
    remote = type("File", (), {
        "id": 10, "download_url": "https://gamebanana.com/dl/10", "size": 3,
        "md5": None,
    })()
    destination = tmp_path / "demo.zip"

    with pytest.raises(DownloadValidationError):
        client.download(remote, str(destination))
    assert not destination.exists()
    assert not (tmp_path / "demo.zip.partial").exists()


def test_download_rejects_md5_mismatch(tmp_path):
    fake = FakeClient([FakeResponse(status_code=200, body=b"abc")])
    client = GameBananaClient(fake)
    remote = type("File", (), {
        "id": 11, "download_url": "https://gamebanana.com/dl/11", "size": 3,
        "md5": "00000000000000000000000000000000",
    })()

    with pytest.raises(DownloadValidationError, match="MD5"):
        client.download(remote, str(tmp_path / "demo.zip"))


def test_json_cache_avoids_second_network_request(tmp_path):
    payload = {"_aMetadata": {"_nRecordCount": 0, "_nPerpage": 30,
                              "_bIsComplete": True}, "_aRecords": []}
    fake = FakeClient([FakeResponse(payload)])
    client = GameBananaClient(fake, cache_dir=str(tmp_path))

    client.browse()
    client.browse()

    assert len(fake.calls) == 1


def test_force_refresh_bypasses_json_cache(tmp_path):
    first = {"_aMetadata": {"_nRecordCount": 0, "_nPerpage": 30,
                            "_bIsComplete": True}, "_aRecords": []}
    second = {"_aMetadata": {"_nRecordCount": 1, "_nPerpage": 30,
                             "_bIsComplete": True}, "_aRecords": []}
    fake = FakeClient([FakeResponse(first), FakeResponse(second)])
    client = GameBananaClient(fake, cache_dir=str(tmp_path))

    client.browse()
    page = client.browse(force=True)

    assert page.record_count == 1
    assert len(fake.calls) == 2


def test_image_cache_avoids_second_network_request(tmp_path):
    body = b"image bytes"
    fake = FakeClient([FakeResponse(status_code=200, body=body)])
    fake.responses[0].content = body
    client = GameBananaClient(fake, cache_dir=str(tmp_path))
    url = "https://images.gamebanana.com/img/test.jpg"

    assert client.fetch_image(url) == body
    assert client.fetch_image(url) == body
    assert len(fake.calls) == 1


def _browse_payload():
    return {
        "_aMetadata": {"_nRecordCount": 1, "_nPerpage": 30, "_bIsComplete": True},
        "_aRecords": [{
            "_idRow": 7, "_sName": "Demo", "_sProfileUrl": "https://gamebanana.com/mods/7",
            "_sModelName": "Tool", "_sVersion": "", "_bHasFiles": True,
            "_aRootCategory": None,
            "_aCategory": {"_sName": "Other/Misc"},
            "_aPreviewMedia": {"_aImages": []},
        }],
    }


def test_browse_category_filter_added_to_index_params():
    fake = FakeClient([FakeResponse(_browse_payload())])
    client = GameBananaClient(fake)
    category = RemoteCategory(
        model="Mod", category_id=35464, name="Skins", has_children=True)

    client.browse(category=category)

    params = fake.calls[0][1]
    assert params["_aFilters[Generic_Category]"] == 35464
    assert params["_aFilters[Generic_Game]"] == 21842


def test_browse_category_filter_added_to_search_params():
    fake = FakeClient([FakeResponse(_browse_payload())])
    client = GameBananaClient(fake)

    client.browse(query="ui", category=("Mod", 42706))

    params = fake.calls[0][1]
    assert params["_sSearchString"] == "ui"
    assert params["_aFilters[Generic_Category]"] == 42706


def test_browse_model_switches_index_path_and_maps_model():
    fake = FakeClient([FakeResponse(_browse_payload())])
    client = GameBananaClient(fake)

    page = client.browse(model="Tool", category=("Tool", 1990))

    assert fake.calls[0][0].endswith("/apiv11/Tool/Index")
    assert page.items[0].model == "Tool"
    assert page.items[0].category == "Other/Misc"


def test_browse_without_category_omits_filter():
    fake = FakeClient([FakeResponse(_browse_payload())])
    client = GameBananaClient(fake)

    client.browse()

    params = fake.calls[0][1]
    assert "_aFilters[Generic_Category]" not in params


def test_details_uses_model_specific_path():
    payload = {"_idRow": 8, "_sName": "Demo", "_sProfileUrl": "https://gamebanana.com/tools/8",
               "_sDescription": "", "_aFiles": []}
    fake = FakeClient([FakeResponse(payload)])
    client = GameBananaClient(fake)

    client.details(8, model="Tool")

    assert fake.calls[0][0].endswith("/apiv11/Tool/8/ProfilePage")


def test_categories_maps_fields_and_skips_obsolete():
    payload = [
        {"_idRow": 35464, "_sName": "Skins", "_nItemCount": 581,
         "_nCategoryCount": 5, "_sIconUrl": "https://images.gamebanana.com/ico.png",
         "_bIsObsolete": False},
        {"_idRow": 42706, "_sName": "UI", "_nItemCount": 22,
         "_nCategoryCount": 0, "_bIsObsolete": False},
        {"_idRow": 999, "_sName": "Old", "_nItemCount": 1,
         "_nCategoryCount": 0, "_bIsObsolete": True},
    ]
    fake = FakeClient([FakeResponse(payload)])
    client = GameBananaClient(fake)

    categories = client.categories("Mod")

    assert fake.calls[0][1] == {"_idGameRow": 21842, "_sSort": "count"}
    assert len(categories) == 2
    skins = categories[0]
    assert skins.model == "Mod"
    assert skins.category_id == 35464
    assert skins.name == "Skins"
    assert skins.item_count == 581
    assert skins.has_children is True
    assert skins.icon_url == "https://images.gamebanana.com/ico.png"
    assert categories[1].has_children is False


def test_categories_normalizes_single_object_payload():
    payload = {"_idRow": 6252, "_sName": "Other/Misc", "_nItemCount": 0,
               "_nCategoryCount": 0, "_bIsObsolete": False}
    fake = FakeClient([FakeResponse(payload)])
    client = GameBananaClient(fake)

    categories = client.categories("Sound")

    assert len(categories) == 1
    assert categories[0].category_id == 6252


def test_subcategories_parse_id_from_url():
    payload = [{
        "_sName": "Operators", "_sIconUrl": "",
        "_sUrl": "https://gamebanana.com/mods/cats/42770",
        "_nItemCount": 552,
    }]
    fake = FakeClient([FakeResponse(payload)])
    client = GameBananaClient(fake)

    categories = client.subcategories("Mod", 35464)

    assert fake.calls[0][0].endswith("/apiv11/ModCategory/35464/SubCategories")
    assert len(categories) == 1
    assert categories[0].category_id == 42770
    assert categories[0].name == "Operators"
    assert categories[0].item_count == 552
    assert categories[0].has_children is False


def test_subcategories_handles_empty_payload():
    fake = FakeClient([FakeResponse([])])
    client = GameBananaClient(fake)

    assert client.subcategories("Mod", 35464) == ()


def test_category_filter_normalizes_none_tuple_and_remote():
    assert _category_filter(None) == ("Mod", None)
    assert _category_filter(("Tool", 1990)) == ("Tool", 1990)
    assert _category_filter((None, None)) == ("Mod", None)
    remote = RemoteCategory(model="Sound", category_id=6252, name="Other/Misc")
    assert _category_filter(remote) == ("Sound", 6252)


def test_browse_search_rejects_non_mod_categories():
    fake = FakeClient([])
    client = GameBananaClient(fake)

    with pytest.raises(GameBananaError, match="不支持搜索"):
        client.browse(query="test", category=("Tool", 1990))
    assert fake.calls == []


def test_mod_normalizes_untrusted_model_names():
    payload = {"_idRow": 1, "_sName": "X", "_sProfileUrl": "",
               "_sModelName": "../evil", "_aPreviewMedia": {"_aImages": []}}
    item = _mod(payload)
    assert item.model == "Mod"

    clean = {"_idRow": 1, "_sName": "X", "_sProfileUrl": "",
             "_aPreviewMedia": {"_aImages": []}}
    item = _mod(clean, model="Sound")
    assert item.model == "Sound"


def test_details_normalizes_untrusted_model_path():
    payload = {"_idRow": 8, "_sName": "Demo", "_sProfileUrl": "",
               "_sDescription": "", "_aFiles": []}
    fake = FakeClient([FakeResponse(payload)])
    client = GameBananaClient(fake)

    client.details(8, model="../evil")

    assert fake.calls[0][0].endswith("/apiv11/Mod/8/ProfilePage")


def test_categories_normalizes_untrusted_model_path():
    fake = FakeClient([FakeResponse([])])
    client = GameBananaClient(fake)

    client.categories("../evil")

    assert fake.calls[0][0].endswith("/apiv11/Mod/Categories")


def test_subcategories_normalizes_untrusted_model_path():
    fake = FakeClient([FakeResponse([])])
    client = GameBananaClient(fake)

    client.subcategories("../evil", 35464)

    assert fake.calls[0][0].endswith("/apiv11/ModCategory/35464/SubCategories")
