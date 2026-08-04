from modules.config import README_NAMES
from modules.mod_ops import ModManager, find_readme_files


def test_scan_mods_preserves_enabled_then_disabled_sorting(tmp_path):
    mods = tmp_path / "Mods"
    disabled = tmp_path / "Disabled_Mods"
    mods.mkdir()
    disabled.mkdir()
    for name in ("Zulu", "Alpha"):
        (mods / name).mkdir()
    for name in ("Delta", "Beta"):
        (disabled / name).mkdir()
    (mods / "not-a-mod.txt").write_text("ignored", encoding="utf-8")

    result = ModManager(str(tmp_path)).scan_mods()

    assert [(item["name"], item["enabled"]) for item in result] == [
        ("Alpha", True),
        ("Zulu", True),
        ("Beta", False),
        ("Delta", False),
    ]


def test_find_readmes_uses_configured_order_and_ignores_directories(tmp_path):
    (tmp_path / "README_KO.txt").write_text("ko", encoding="utf-8")
    (tmp_path / "README.md").write_text("main", encoding="utf-8")
    (tmp_path / "README_EN.md").write_text("en", encoding="utf-8")
    (tmp_path / "README_CN.md").mkdir()
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    result = find_readme_files(str(tmp_path))

    names = [name for name, _path in result]
    assert names == [
        name for name in README_NAMES
        if name in {"README.md", "README_EN.md", "README_KO.txt"}
    ]


def test_find_readmes_returns_empty_for_missing_directory(tmp_path):
    assert find_readme_files(str(tmp_path / "missing")) == []


def test_check_readme_files_uses_current_mod_location(tmp_path):
    mod_path = tmp_path / "Disabled_Mods" / "Example"
    (tmp_path / "Mods").mkdir()
    mod_path.mkdir(parents=True)
    readme = mod_path / "README.txt"
    readme.write_text("text", encoding="utf-8")

    result = ModManager(str(tmp_path)).check_readme_files("Example", False)

    assert result == [("README.txt", str(readme))]
