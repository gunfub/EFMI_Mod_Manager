from modules.catalog_view import (
    CARD,
    COMPACT,
    DETAILED,
    VIEW_MODE_ORDER,
    VIEW_MODES,
    LocalCatalogState,
    LocalItemViewModel,
    OnlineCatalogState,
    fit_card_text,
    is_sensitive,
    readme_presentation,
    remote_image_cache_key,
)
from modules.gamebanana import Page, RemoteMod


def _remote(item_id, obsolete=False, visibility="show", ratings=False):
    return RemoteMod(
        id=item_id, name="Mod {}".format(item_id), profile_url="",
        version=None, date_updated=None, author=None, category=None,
        images=(), has_files=True, visibility=visibility,
        has_content_ratings=ratings, is_obsolete=obsolete)


def test_local_view_model_uses_note_as_display_name():
    vm = LocalItemViewModel.from_mod(
        {"name": "Folder", "path": "C:/Mods/Folder", "enabled": True},
        note="Friendly", selected=True)

    assert vm.display_name == "Friendly"
    assert vm.secondary_name == "Folder"
    assert vm.selected is True


def test_local_selection_prunes_missing_mods():
    state = LocalCatalogState(selected_names={"A", "B"})
    state.prune_selection({"B", "C"})
    assert state.selected_names == {"B"}


def test_readme_presentation_handles_zero_one_and_many():
    assert readme_presentation([])[0] is None
    assert readme_presentation([("README.md", "one")])[0] == "README.md"
    assert readme_presentation([("README.md", "one"), ("README.txt", "two")])[0] == "README x2"


def test_remote_sensitive_policy_includes_visibility_and_ratings():
    assert is_sensitive(_remote(1, visibility="warn"))
    assert is_sensitive(_remote(2, ratings=True))
    assert not is_sensitive(_remote(3))


def test_online_state_commits_only_successful_current_pages():
    state = OnlineCatalogState()
    generation = state.begin_search("query", "popular")
    page = Page((_remote(1), _remote(1), _remote(2, obsolete=True)), 10, 30, 1, False)

    assert state.accept_page(generation, page)
    assert [item.id for item in state.items] == [1]
    assert state.successful_page == 1
    assert state.next_page == 2
    assert not state.accept_page(generation - 1, Page((_remote(3),), 10, 30, 2, True))
    assert state.successful_page == 1


def test_online_details_requests_are_deduplicated():
    state = OnlineCatalogState()
    assert state.begin_details(7)
    assert not state.begin_details(7)
    state.finish_details(7)
    assert state.begin_details(7)


def test_online_state_begin_search_carries_category():
    state = OnlineCatalogState()
    generation = state.begin_search("query", "popular", ("Mod", 35464))

    assert state.category == ("Mod", 35464)
    assert state.query == "query"
    assert state.sort == "popular"
    page = Page((_remote(1),), 10, 30, 1, True)
    assert state.accept_page(generation, page)
    assert [item.id for item in state.items] == [1]

    state.begin_search("", "recent")
    assert state.category is None
    assert state.items == []


def test_remote_image_cache_key_contains_blur_policy():
    clear = remote_image_cache_key("https://example/image", (150, 84), False)
    blurred = remote_image_cache_key("https://example/image", (150, 84), True)
    assert clear != blurred


def test_view_mode_order_keeps_lists_adjacent_and_card_last():
    assert VIEW_MODE_ORDER == (COMPACT, DETAILED, CARD)
    assert set(VIEW_MODE_ORDER) == set(VIEW_MODES)


class FakeFont:
    def __init__(self, char_width=10):
        self._char_width = char_width

    def measure(self, text):
        return len(text) * self._char_width


def test_fit_card_text_short_text_stays_on_one_line():
    assert "\n" not in fit_card_text("Short", FakeFont(), 50)


def test_fit_card_text_long_text_wraps_two_lines_with_ellipsis():
    fitted = fit_card_text(
        "One Two Three Four", FakeFont(), 50)
    assert fitted.count("\n") == 1
    assert fitted.endswith("...")


def test_fit_card_text_single_long_word_breaks_within_word():
    fitted = fit_card_text("ABCDEFGHIJ", FakeFont(), 50)
    assert fitted.count("\n") == 1
    assert fitted == "ABCDE\nFGHIJ"


def test_fit_card_text_empty_returns_empty():
    assert fit_card_text("", FakeFont(), 50) == ""
