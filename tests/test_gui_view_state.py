from modules import gui
from modules.catalog_view import LocalCatalogState


class FakeVar:
    def __init__(self, value=False):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _app():
    app = gui.ModManagerApp.__new__(gui.ModManagerApp)
    app._local_state = LocalCatalogState()
    app.mods_data = [
        {"name": "Alpha"}, {"name": "Beta"}, {"name": "Gamma"},
    ]
    app._mod_rows = {
        name: [{"mod": {"name": name}, "checkbox_var": FakeVar(False)}]
        for name in ("Alpha", "Beta", "Gamma")
    }
    app._checkbox_vars = {
        name: app._mod_rows[name][0]["checkbox_var"]
        for name in ("Alpha", "Beta", "Gamma")
    }
    app._group_checkbox_vars = {}
    app._group_mods = {}
    return app


def test_view_mode_labels_cover_three_modes():
    app = gui.ModManagerApp.__new__(gui.ModManagerApp)
    labels = app._view_mode_labels()
    assert set(labels.keys()) == {"compact", "card", "detailed"}
    assert len(set(labels.values())) == 3


def test_view_switch_order_is_compact_detailed_card():
    app = gui.ModManagerApp.__new__(gui.ModManagerApp)
    captured = {}

    class FakeSwitch:
        def configure(self, **kwargs):
            captured.update(kwargs)

    class FakeVar:
        def set(self, _value):
            pass

    app._view_switch = FakeSwitch()
    app._view_mode = "compact"
    app._view_mode_var = FakeVar()
    app._update_view_switch_labels()
    labels = app._view_mode_labels()
    assert captured["values"] == [
        labels["compact"], labels["detailed"], labels["card"],
    ]


def test_view_mode_change_maps_exact_label_and_persists(monkeypatch):
    app = gui.ModManagerApp.__new__(gui.ModManagerApp)
    app._view_mode = "compact"
    app._local_state = LocalCatalogState()
    app._card_resize_job = None
    rendered = []
    saved = []
    app._render_mod_list = lambda: rendered.append(1)
    monkeypatch.setattr(gui.ConfigManager, "set_view_mode",
                        lambda *args: saved.append(args))

    labels = app._view_mode_labels()
    app._on_view_mode_change(labels["detailed"])
    assert app._view_mode == "detailed"
    assert saved == [("local", "detailed")]
    assert len(rendered) == 1

    app._on_view_mode_change(labels["detailed"])
    assert len(rendered) == 1
    assert len(saved) == 1


def test_select_deselect_invert_use_state_as_truth():
    app = _app()
    app._select_all()
    assert app._local_state.selected_names == {"Alpha", "Beta", "Gamma"}
    assert all(var.get() for var in app._checkbox_vars.values())

    app._invert_selection()
    assert app._local_state.selected_names == set()
    assert not any(var.get() for var in app._checkbox_vars.values())

    app._checkbox_vars["Beta"].set(True)
    app._on_mod_checkbox_toggle("Beta")
    assert app._local_state.selected_names == {"Beta"}

    app._deselect_all()
    assert app._local_state.selected_names == set()


def test_group_toggle_updates_state_and_all_instances():
    app = _app()
    app._group_mods = {"GroupA": ["Alpha", "Beta"]}
    app._mod_rows["Alpha"].append({
        "mod": {"name": "Alpha"}, "checkbox_var": FakeVar(False)})
    app._group_checkbox_vars = {"GroupA": FakeVar(False)}

    app._group_checkbox_vars["GroupA"].set(True)
    app._on_group_checkbox_toggle("GroupA")
    assert app._local_state.selected_names == {"Alpha", "Beta"}
    assert all(
        var.get() for handle in app._mod_rows["Alpha"] for var in [handle["checkbox_var"]])
    assert app._group_checkbox_vars["GroupA"].get() is True

    app._group_checkbox_vars["GroupA"].set(False)
    app._on_group_checkbox_toggle("GroupA")
    assert app._local_state.selected_names == set()


def test_get_selected_mods_returns_state_mods():
    app = _app()
    app._select_all()
    app._local_state.selected_names.discard("Beta")
    selected = app._get_selected_mods()
    assert [m["name"] for m in selected] == ["Alpha", "Gamma"]
