from modules.gamebanana import RemoteCategory, RemoteMod
from modules.online_browser import (
    CARD_GAP,
    CARD_WIDTH,
    COMPACT_PREVIEW,
    DETAILED_PREVIEW,
    LEAF_CHILD_CATEGORY_IDS,
    OnlineBrowserFrame,
    blur_thumbnail,
    card_preview_size,
    category_menu_label,
    category_section_label,
    online_card_columns,
)


def _remote(item_id, visibility="show", ratings=False):
    return RemoteMod(
        id=item_id, name="Mod {}".format(item_id), profile_url="",
        version=None, date_updated=None, author=None, category=None,
        images=(), has_files=True, visibility=visibility,
        has_content_ratings=ratings, is_obsolete=False)


def test_blur_thumbnail_only_when_hidden_and_sensitive():
    assert blur_thumbnail(True, _remote(1, visibility="warn")) is True
    assert blur_thumbnail(True, _remote(2, ratings=True)) is True
    assert blur_thumbnail(True, _remote(3)) is False
    assert blur_thumbnail(False, _remote(4, visibility="warn")) is False


def test_online_card_columns_formula():
    assert online_card_columns(200) == 1
    assert online_card_columns(256) == 1
    assert online_card_columns(540) == 2
    assert online_card_columns(1000) >= 3
    assert online_card_columns(500, dpi_scale=2.0) <= online_card_columns(500)


def test_online_preview_sizes_are_16_9():
    for size in (COMPACT_PREVIEW, DETAILED_PREVIEW):
        ratio = size[0] / float(size[1])
        assert abs(ratio - 16.0 / 9.0) / (16.0 / 9.0) < 0.005, size


def test_online_card_preview_size_matches_local_formula():
    for card_width in (210, 240, 300, 400):
        image_size, display_size, preview_height = card_preview_size(
            card_width, dpi_scale=1.0)
        ratio = image_size[0] / float(image_size[1])
        assert abs(ratio - 16.0 / 9.0) / (16.0 / 9.0) < 0.006, image_size
        assert display_size[0] == image_size[0]
        assert preview_height == max(94, round(image_size[0] * 9 / 16))


def test_online_card_spec_matches_local():
    from modules.gui import ModManagerApp
    assert CARD_WIDTH == ModManagerApp.CARD_WIDTH
    assert CARD_GAP == ModManagerApp.CARD_GAP


def _label_fn(key, default):
    return {"online.section_tools": "Tools"}.get(key, default)


def test_category_menu_label_translates_category_name():
    label = category_menu_label(
        35464, "Skins",
        lambda cid, raw: "皮肤" if cid == 35464 else raw)
    assert label == "皮肤"


def test_category_menu_label_is_plain_translation_without_section_prefix():
    label = category_menu_label(
        42770, "Operators",
        lambda cid, raw: "干员")
    assert label == "干员"


def test_category_menu_label_falls_back_to_english_original():
    label = category_menu_label(
        9999, "Blender Plugins",
        lambda cid, raw: raw)
    assert label == "Blender Plugins"


def test_category_section_label_uses_ui_translation():
    assert category_section_label("Mod", _label_fn) == "Mods"
    assert category_section_label("Tool", _label_fn) == "Tools"
    assert category_section_label("Sound", _label_fn) == "声音"
    assert category_section_label("UnknownModel", _label_fn) == "UnknownModel"


def _bare_frame():
    frame = object.__new__(OnlineBrowserFrame)
    frame._category_nodes = {}
    return frame


def _cat(category_id, name="Cat"):
    return RemoteCategory(model="Mod", category_id=category_id, name=name)


def test_leaf_child_categories_cover_operators_and_weapons():
    assert LEAF_CHILD_CATEGORY_IDS == {42770, 42772}


def test_children_of_operators_are_static_leaves():
    frame = _bare_frame()
    child = frame._as_child_node(
        _cat(42719, "Endministrator (F)"), 42770)

    assert child["static_children"] is True
    assert child["children_loaded"] is True
    assert child["has_children"] is False


def test_children_of_weapons_are_static_leaves():
    frame = _bare_frame()
    child = frame._as_child_node(_cat(42773, "Sword"), 42772)

    assert child["static_children"] is True
    assert child["children_loaded"] is True
    assert child["has_children"] is False


def test_other_children_remain_dynamic():
    frame = _bare_frame()
    child = frame._as_child_node(_cat(42770, "Operators"), 35464)

    assert child["static_children"] is False
    assert child["children_loaded"] is False


def test_leaf_marking_is_idempotent_when_node_exists():
    frame = _bare_frame()
    first = frame._as_child_node(_cat(42719, "Amiya"), 42770)
    second = frame._as_child_node(_cat(42719, "Amiya"), 42770)

    assert first is second
    assert second["static_children"] is True


def test_fetch_full_image_uses_passed_bounds_not_winfo():
    from io import BytesIO

    from PIL import Image as PILImage

    buf = BytesIO()
    PILImage.new("RGB", (2000, 1500), (120, 80, 40)).save(buf, "JPEG")

    class StubRoot:
        def winfo_screenwidth(self):
            raise AssertionError("winfo_screenwidth must not run in the worker")

        def winfo_screenheight(self):
            raise AssertionError("winfo_screenheight must not run in the worker")

    class StubClient:
        def fetch_image(self, url):
            return buf.getvalue()

    frame = object.__new__(OnlineBrowserFrame)
    frame.client = StubClient()
    frame.root = StubRoot()

    image = frame._fetch_full_image(
        "https://images.gamebanana.com/img/ss/x.jpg", 500, 400)
    assert image.mode == "RGB"
    assert image.size[0] <= 500
    assert image.size[1] <= 400
    assert image.size[0] / float(image.size[1]) > 1.2
