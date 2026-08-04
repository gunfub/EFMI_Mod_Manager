# EFMI Mod Manager - Modules Documentation

> This document describes the responsibilities, public interfaces, call relationships, and implementation details of every Python module under `modules/`.

[中文](modules.md) | **English**

---

## Contents

1. [Architecture](#architecture)
2. [modules/__init__.py - Package Declaration](#modulesinitpy---package-declaration)
3. [modules/config.py - Configuration](#modulesconfigpy---configuration)
4. [modules/mod_ops.py - Mod Operations](#modulesmod_opspy---mod-operations)
5. [modules/console_setup.py - Console and Startup](#modulesconsole_setuppy---console-and-startup)
6. [modules/i18n.py - Internationalization](#modulesi18npy---internationalization)
7. [modules/gui.py - Main GUI](#modulesguipy---main-gui)
8. [Call Flow](#call-flow)

---

## Architecture

```text
mod_manager.py                  Entry point and startup orchestration
  |
  |-- modules/console_setup.py  Console/warning setup (imported first)
  |-- modules/i18n.py           Language initialization before the GUI
  `-- modules/gui.py            Main customtkinter window
        |-- modules/config.py   Persistent configuration and README names
        `-- modules/mod_ops.py  Mod scanning, movement, and file opening
```

Core rules:

- `mod_manager.py` is the only startup orchestrator.
- Internal modules do not have circular dependencies.
- `console_setup.py` must run before importing `customtkinter`.
- `i18n.py` must be initialized before importing `gui.py` so initial UI text uses the selected language.

---

## modules/__init__.py - Package Declaration

- **File:** `modules/__init__.py`
- **Purpose:** Marks `modules/` as a Python package. It contains no runtime logic.

---

## modules/config.py - Configuration

### Responsibility

Reads and writes `mod_manager_config.json` in the application directory. It stores the game path, language, view mode, notes, preview paths, groups, ordering, and collapsed-group state.

### Public Constants

| Name | Type | Description |
|------|------|-------------|
| `APP_DIR` | `str` | Application directory; the executable directory when frozen |
| `CONFIG_PATH` | `str` | Full path to `mod_manager_config.json` |
| `README_NAMES` | `list[str]` | Ordered list of recognized README filenames |
| `README_LABELS` | `dict[str, str]` | README filename to GUI button label mapping |

`README_NAMES` supports `.md` and `.txt`, the base `README` name, and common language suffixes:

- Chinese: `ZH`, `CN`, `ZH_CN`, `CHS`, `TW`, `ZH_TW`, `CHT`
- English: `EN`
- Japanese: `JA`, `JP`
- Korean: `KO`, `KR`

### Public Function

| Function | Description |
|----------|-------------|
| `get_app_dir()` | Returns the application directory used by `APP_DIR` |

### Class: `ConfigManager`

All methods are static and are called as `ConfigManager.method()`.

#### General I/O

| Method | Return | Description |
|--------|--------|-------------|
| `load()` | `dict` | Loads JSON; returns `{}` if the file is absent or invalid |
| `save(config)` | - | Writes UTF-8 JSON with indentation |

#### Stored Settings

| Getter / Setter | Description |
|-----------------|-------------|
| `get_game_path()` / `set_game_path(path)` | Game root containing `Mods/` |
| `get_mod_notes()` / `set_mod_note(name, note)` | Custom Mod display names; an empty note removes the entry |
| `get_mod_images()` / `set_mod_image(name, path)` | Relative or absolute preview-image paths |
| `get_mod_groups()` / `set_mod_groups(groups)` | Group-to-Mod mapping |
| `get_group_order()` / `set_group_order(order)` | Persisted group order |
| `get_collapsed_groups()` / `set_collapsed_groups(names)` | Collapsed group names |
| `get_language()` / `set_language(lang)` | `auto`, `zh`, `en`, `ja`, `ko`, etc. |
| `get_view_mode()` / `set_view_mode(mode)` | `list` or `card`; invalid values fall back to `list` |

#### Cleanup

| Method | Description |
|--------|-------------|
| `cleanup_mod_data(valid_mod_names)` | Removes notes/images/group references for missing Mods and cleans stale group-order entries |

### Configuration Shape

```json
{
  "language": "auto",
  "view_mode": "card",
  "game_path": "D:/Games/MyGame",
  "mod_notes": {
    "mod_abc": "My Custom Name"
  },
  "mod_images": {
    "mod_abc": "screenshot.png",
    "mod_xyz": "D:/Pictures/preview.png"
  },
  "mod_groups": {
    "UI Mods": ["mod_a", "mod_b"],
    "Gameplay": ["mod_c"]
  },
  "group_order": ["UI Mods", "Gameplay"],
  "collapsed_groups": ["Gameplay"]
}
```

### Used By

- `mod_manager.py` for the initial language
- `modules/gui.py` for all UI settings and metadata
- `modules/mod_ops.py` for `README_NAMES`

---

## modules/mod_ops.py - Mod Operations

### Responsibility

Contains non-UI business logic for validating directories, scanning Mods, detecting README files, moving Mod folders, and opening files/folders through the operating system.

### Class: `ModManager`

Constructed with the game root directory.

| Attribute | Description |
|-----------|-------------|
| `game_path` | Selected game root |
| `mods_dir` | `game_path/Mods` |
| `disabled_dir` | `game_path/Disabled_Mods` |

### Methods

| Method | Return | Description |
|--------|--------|-------------|
| `validate()` | `(bool, str, bool)` | Validates the game path and creates `Disabled_Mods` when needed |
| `scan_mods()` | `list[dict]` | Returns Mod dictionaries containing `name`, `enabled`, and `path` |
| `check_readme_files(name, enabled)` | `list[(name, path)]` | Detects all recognized README names in configured order |
| `open_file(path)` | - | Opens a file through the OS default application |
| `open_mod_folder(name, enabled)` | - | Opens the Mod directory through the OS file manager |
| `toggle_mod(name, currently_enabled, progress_callback=None)` | - | Moves one Mod between enabled and disabled directories |
| `toggle_mods_batch(mods, enable, progress_callback=None, file_progress_callback=None)` | `list[(name, ok, error)]` | Moves several Mods and reports individual results |
| `_move_with_progress(src, dst, callback=None)` | - | Internal rename-first, copy-and-delete fallback implementation |

### Move Strategy

1. Try `os.rename()` for a fast same-volume move.
2. If that fails, copy files with `shutil.copy2()` and remove the source with `shutil.rmtree()`.
3. Report progress through `progress_callback(current, total, bytes_done, status)`.

### Cross-Platform Opening

The module-level `_open_in_os()` dispatches to:

- Windows: `os.startfile`
- macOS: `open`
- Linux and other supported Unix systems: `xdg-open`

---

## modules/console_setup.py - Console and Startup

### Responsibility

Runs before third-party GUI imports to:

1. Redirect early `stderr` output to the null device.
2. Suppress `pkg_resources` deprecation warnings.
3. Show or hide the console according to the `debug_mode` file.

### Public Functions

| Function | Description |
|----------|-------------|
| `redirect_stderr_to_null()` | Redirects `sys.stderr` before third-party imports |
| `suppress_pkg_resources_warning()` | Adds message-based warning filters compatible with PyInstaller import hooks |
| `restore_stderr()` | Restores the original stream for debugging |
| `setup_console_visibility(app_dir)` | Applies `debug_mode` behavior; non-Windows systems only restore stderr |

### Required Startup Order

```python
redirect_stderr_to_null()
suppress_pkg_resources_warning()
setup_console_visibility(APP_DIR)
init_i18n()
from modules.gui import ModManagerApp
```

---

## modules/i18n.py - Internationalization

### Responsibility

Detects the system language, loads JSON translations, supports runtime switching, and falls back to Chinese source strings when a translation key is missing.

### Public Functions

| Function | Description |
|----------|-------------|
| `init_i18n()` | Initializes and returns the global `I18n` instance |
| `get_i18n()` | Returns the global instance, creating it if necessary |
| `t(key, zh_default)` | Looks up a dotted translation key with a Chinese fallback |

### Class: `I18n`

| Method / Property | Description |
|-------------------|-------------|
| `set_language(lang)` | Selects `auto`, `zh`, `en`, `ja`, `ko`, etc. |
| `t(key, zh_default)` | Resolves a translated string |
| `on_language_changed(callback)` | Registers a language-change callback |
| `lang` | User-selected value |
| `effective_lang` | Language currently in use after auto-detection/fallback |
| `available` | Language codes discovered from `locales/*.json` |

### Detection and Fallback

- Windows first uses `GetUserDefaultUILanguage`.
- Other platforms and failures fall back to Python locale detection.
- Chinese is the source language and does not require a JSON file.
- Other languages load `locales/<code>.json`.
- Missing keys return the Chinese default passed to `t()`.

---

## modules/gamebanana.py - GameBanana API Client

### Responsibility

Wraps the GameBanana API v11: online browsing, search, category filtering, details, and secure downloads.

### Main Interface

| Method | Description |
|--------|-------------|
| `browse(page, per_page, sort, query, category, model, force)` | Browse/search listings; `category` accepts a `RemoteCategory` or a `(model, category_id)` tuple, mapped to `_aFilters[Generic_Category]` and the request path (`/apiv11/{model}/Index` or `Util/Search/Results`) |
| `categories(model, game_id, force)` | Root categories: `GET /apiv11/{model}/Categories?_idGameRow=...&_sSort=count`; obsolete categories are skipped |
| `subcategories(model, category_id, force)` | Subcategories: `GET /apiv11/{model}Category/{id}/SubCategories`; records lack `_idRow`, so the ID is parsed from the last `_sUrl` segment |
| `details(mod_id, model, force)` | Details: `GET /apiv11/{model}/{id}/ProfilePage`; Tool/Sound profiles are compatible with Mod |

### Data Classes

- `RemoteCategory`: `model`, `category_id`, `name`, `item_count`, `icon_url`, `has_children`
- `RemoteMod`: includes a `model` field (from `_sModelName`) that selects the details endpoint

### Notes

- Category endpoints return a single dict instead of an array for one-record results; the client normalizes this
- The filter key is `Generic_Category` (`Mod_Category` returns UNKNOWN_FILTER)

---

## modules/gb_category_i18n.py - Category Name Translations (Manual Hot Updates)

### Responsibility

Independent translation layer for GameBanana category names: bundled fallback plus manual GitHub hot updates, separate from the UI i18n system.

### Files and Constants

- Bundled: `locales/category_translations/gb_category_names.json` (ships with the app; path matches the GitHub repository)
- Cache: `data/cache/gb_category_names.json` (last successful update; takes priority over the bundled file)
- Default URL: `https://raw.githubusercontent.com/gunfub/EFMI_Mod_Manager/main/locales/category_translations/gb_category_names.json` (overridable via `ConfigManager.get/set_gb_category_i18n_url`)
- Format: `{"category_id": {"zh": "translation", ...}}`; `en` is optional

### Class: `GBCategoryI18n`

| Method | Description |
|--------|-------------|
| `load()` | Reads local translations (cache -> bundled -> empty) at startup; never touches the network |
| `refresh(client)` | Manually fetches the latest translations; host whitelist, 1 MiB size cap, JSON structure validation, atomic cache write; returns an error string instead of raising |
| `translate(category_id, name, lang)` | Returns the translation or falls back to the English original |

### Called By

- `modules/online_browser.py` (the "Update category translations" button calls `refresh()`; network access happens only on button click)

---

## modules/gui.py - Main GUI

### Responsibility

Implements the complete `customtkinter` interface: toolbar, list/card views, groups, A-Z navigation, notes, previews, README actions, selection, enable/disable operations, progress, and dialogs.

### Dependencies

- `customtkinter`
- Pillow through `HAS_PIL`
- pypinyin through `HAS_PYPINYIN`
- `ConfigManager`, `README_LABELS`, `ModManager`, and i18n helpers

### Class: `ModManagerApp`

#### Layout Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `PREVIEW_SIZE` | `(85, 48)` | Logical 16:9 thumbnail size in list view |
| `CARD_WIDTH` | `256` | Fixed logical card width; about 320 px at 125% DPI |
| `CARD_GAP` | `4` | Logical card-grid spacing |

#### Construction and Startup

| Method | Description |
|--------|-------------|
| `__init__()` | Builds the window, loads view preference, starts card-area monitoring, and schedules deferred initial loading |
| `run()` | Enters `root.mainloop()` |
| `_load_config_and_refresh(defer=False)` | Loads the path and optionally defers the initial scan |
| `_refresh_when_layout_ready(attempt=0)` | Waits for a reliable scroll-area width before the first card render |
| `_refresh()` | Validates, scans, cleans metadata, renders Mods, updates stats, and rebuilds navigation |
| `_update_browse_btn_visibility()` | Shows the top-bar Browse button only until a folder is selected; hides it afterwards (the Settings menu entry stays available) |
| `_show_settings_menu(anchor=None)` | Top-bar Settings popup: Language submenu (current language checkmarked) and Browse Folder |
| `_show_mod_settings_menu(anchor=None)` | Top-bar More Mod Settings popup: Restore Backup and Check GameBanana Mod Updates |

The deferred startup avoids calculating card columns while Tk still reports the temporary startup width.

#### UI and Navigation

| Method | Description |
|--------|-------------|
| `_build_ui()` | Builds a classic Win32-style menu bar pinned to the very top of the window (Settings / More Mod Settings, left-aligned, with a divider line beneath), the title bar (title, page buttons, path label, conditional Browse button), the toolbar (select/actions/groups + Install ZIP/Refresh/view mode), scroll area, alphabet bar, status bar, and progress widgets |
| `_build_alphabet_bar(parent)` | Builds the global group index container |
| `_rebuild_alphabet_bar()` | Creates group-initial buttons and the ungrouped shortcut |
| `_build_group_mini_alpha_bar(content, group, mods, notes)` | Builds the per-group Mod initial index |
| `_scroll_to_group(letter)` / `_scroll_to_mini_letter(...)` | Scroll navigation helpers |
| `_get_sort_key(display)` / `_get_index_letter(display)` | Mixed English/Chinese sorting and indexing helpers |

#### View Modes and Responsive Cards

| Method | Description |
|--------|-------------|
| `_view_mode_labels()` | Returns localized List/Card labels |
| `_on_view_mode_change(label)` | Saves the new mode and rebuilds the Mod area |
| `_get_card_column_count(width=None)` | Calculates how many fixed-width cards fully fit |
| `_watch_card_area()` | Reads the underlying Canvas width every 150 ms and reacts only when column count changes |
| `_refresh_card_columns()` | Rebuilds cards while preserving selected Mods and group checkbox state |
| `_fit_card_text(text, font, max_width)` | Wraps text naturally into at most two lines and adds an ellipsis on overflow |

Card-layout rules:

- Cards have a fixed width and do not stretch on large windows or shrink when a column is added.
- A new column is added only when another complete card slot fits.
- Every group reserves the full dynamic column grid, including empty columns.
- The full grid is centered, while cards remain left-aligned from column zero.
- Consequently, groups with one Mod and groups with many Mods share the same grid width and left edge.

#### Rendering

| Method | Description |
|--------|-------------|
| `_render_mod_list()` | Clears old widgets and renders active groups plus the ungrouped section |
| `_create_group_section(...)` | Builds a group header and either a row container or full-width card grid |
| `_create_mod_row(parent, mod, note, image_path)` | Builds one detailed list row |
| `_create_mod_card(parent, mod, note, image_path, index, columns, width)` | Builds one fixed-width card |
| `_show_empty_state(message)` | Clears the Mod area and displays a centered message |

List view:

- Uses compact detailed rows.
- Valid previews are clickable.
- Missing, invalid, unloadable, or Pillow-unavailable previews use a same-position placeholder so names align.

Card view:

- Uses a 16:9 center-cropped preview on top.
- Missing previews use a 16:9 placeholder.
- The note and original folder name each use one natural line or at most two lines.
- Font measurement is adjusted for DPI and verified against the constrained title area so trailing characters are not clipped.

#### README Behavior

- List view displays every detected README as a separate button.
- Card view opens a single README directly.
- Multiple files use one `📄 README xN` button.
- `_show_readme_menu(button, files)` opens a dark popup under the button and opens the selected path.

#### Groups and Selection

| Method | Description |
|--------|-------------|
| `_on_group_checkbox_toggle(group)` | Applies a group checkbox to all Mods in that group |
| `_on_mod_checkbox_toggle(name)` | Synchronizes the containing group checkbox |
| `_select_all()` / `_deselect_all()` / `_invert_selection()` | Bulk selection helpers |
| `_sync_all_group_checkboxes()` | Recomputes every group checkbox |
| `_get_selected_mods()` | Returns selected Mod dictionaries |
| `_create_group()` / `_manage_groups()` | Creates, renames, and deletes groups |
| `_toggle_group_collapse(group, button)` | Persists collapse state |
| `_toggle_mod_group(mod, group, add)` | Adds or removes a Mod from a group |

#### Notes, Previews, and Menus

| Method | Description |
|--------|-------------|
| `_show_more_menu(mod)` | Opens note, preview, and grouping actions |
| `_show_readme_menu(button, files)` | Opens a multi-README selection menu |
| `_resolve_preview_path(mod_path, stored_path)` | Resolves relative paths and paths moved between enabled/disabled directories |
| `_set_preview_image(mod)` / `_clear_preview_image(mod)` | Stores or removes a preview path |
| `_show_full_image(path)` | Opens a themed image viewer sized to at most 60% of the screen |
| `_edit_note(mod)` / `_clear_note(mod)` | Edits or removes the display name |

#### Enable/Disable Operations

| Method | Description |
|--------|-------------|
| `_on_switch_toggled(name, state)` | Starts a confirmed single-Mod operation |
| `_toggle_mod_threaded(mod)` | Runs one move in a worker thread |
| `_batch_toggle(enable)` | Runs selected Mod moves in a worker thread |
| `_on_toggle_complete(...)` / `_on_batch_complete(...)` | Restores UI state and reports results |
| `_update_progress(percent, status)` | Updates progress widgets |
| `_set_ui_enabled(enabled)` | Disables or enables controls during operations |

### Threading Model

- All Tk/customtkinter work runs on the UI thread.
- File moves run in daemon worker threads.
- Worker results return through `root.after(0, callback)`.
- Card-size monitoring runs on the UI thread through `root.after(150, ...)` and rebuilds only when the computed column count changes.

---

## Call Flow

```text
mod_manager.py
  |-- redirect_stderr_to_null()             console_setup.py
  |-- suppress_pkg_resources_warning()      console_setup.py
  |-- setup_console_visibility(APP_DIR)     console_setup.py
  |-- init_i18n() + set_language()          i18n.py + config.py
  `-- ModManagerApp                         gui.py
        |-- _build_ui()
        |-- _watch_card_area()
        `-- _load_config_and_refresh(defer=True)
              `-- _refresh_when_layout_ready()
                    `-- _refresh()
                          |-- ModManager.validate()/scan_mods()
                          |-- ConfigManager.cleanup_mod_data()
                          |-- _render_mod_list()
                          |     `-- _create_group_section()
                          |           |-- _create_mod_row()
                          |           `-- _create_mod_card()
                          |-- _update_stats()
                          `-- _rebuild_alphabet_bar()
```

User actions:

```text
View switch       -> ConfigManager.set_view_mode() -> _render_mod_list()
Single toggle     -> _toggle_mod_threaded() -> ModManager.toggle_mod()
Batch toggle      -> _batch_toggle() -> ModManager.toggle_mods_batch()
Group management  -> ConfigManager.set_mod_groups()
Note/preview      -> ConfigManager.set_mod_note()/set_mod_image()
Multiple README   -> _show_readme_menu() -> ModManager.open_file()
Window resize     -> _watch_card_area() -> _refresh_card_columns()
```

### Dependency Summary

```text
console_setup.py     no internal dependencies
mod_manager.py   ->  console_setup.py, i18n.py, config.py, gui.py
gui.py           ->  config.py, mod_ops.py, i18n.py
mod_ops.py       ->  config.py (README_NAMES), i18n.py
i18n.py          ->  locales/*.json
```
