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
7. [modules/catalog_view.py - View State (Tk-free)](#modulescatalog_viewpy---view-state-tk-free)
8. [modules/gamebanana.py - GameBanana API Client](#modulesgamebananapy---gamebanana-api-client)
9. [modules/gb_category_i18n.py - Category Name Translations](#modulesgb_category_i18npy---category-name-translations)
10. [modules/ai_translate.py - AI Translation (OpenAI-Compatible)](#modulesai_translatepy---ai-translation-openai-compatible)
11. [modules/local_preview_cache.py - Two-Level Local Preview Cache](#moduleslocal_preview_cachepy---two-level-local-preview-cache)
12. [modules/archive_installer.py - Safe ZIP Installation](#modulesarchive_installerpy---safe-zip-installation)
13. [modules/source_store.py - Online Source Records](#modulessource_storepy---online-source-records)
14. [modules/update_checker.py - Update Matching](#modulesupdate_checkerpy---update-matching)
15. [modules/update_manager.py - Transactional Updates and Rollback](#modulesupdate_managerpy---transactional-updates-and-rollback)
16. [modules/cleanup.py - Cache Cleanup](#modulescleanuppy---cache-cleanup)
17. [modules/online_browser.py - GameBanana Online Browser Page](#modulesonline_browserpy---gamebanana-online-browser-page)
18. [modules/patreon.py - Patreon Client](#modulespatreonpy---patreon-client)
19. [modules/patreon_browser.py - Patreon Subscription Browser Page](#modulespatreon_browserpy---patreon-subscription-browser-page)
20. [modules/dialogs.py - Custom Dialogs](#modulesdialogspy---custom-dialogs)
21. [modules/gui.py - Main GUI](#modulesguipy---main-gui)
22. [Call Flow](#call-flow)

---

## Architecture

```text
mod_manager.py                  Entry point and startup orchestration
  |
  |-- modules/console_setup.py  Console/warning setup (imported first)
  |-- modules/i18n.py           Language initialization before the GUI
  `-- modules/gui.py            Main customtkinter window
        |-- modules/config.py            Configuration and README names
        |-- modules/mod_ops.py           Local Mod scanning and movement
        |-- modules/catalog_view.py      View modes / page state (Tk-free)
        |-- modules/local_preview_cache.py  Two-level preview caching
        |-- modules/archive_installer.py    Safe ZIP install pipeline
        |-- modules/source_store.py         Online source records / covers
        |-- modules/update_checker.py       Update matching
        |-- modules/update_manager.py       Transactional updates / backups
        |-- modules/ai_translate.py         AI translation settings and calls
        |-- modules/cleanup.py              Cache cleanup
        |-- modules/gamebanana.py           GameBanana API client
        |-- modules/gb_category_i18n.py     Category name translations
        |-- modules/online_browser.py       GameBanana browser page
        |-- modules/patreon.py              Patreon client (httpx + WebView2)
        |-- modules/patreon_browser.py      Patreon subscription browser page
        `-- modules/dialogs.py              Custom dark dialogs (replaces native messagebox)
```


Core rules:

- `mod_manager.py` is the only startup orchestrator.
- Modules are layered into a pure-logic layer (no Tk) and a UI layer: `config.py`, `mod_ops.py`, `i18n.py`, `catalog_view.py`, `gamebanana.py`, `gb_category_i18n.py`, `ai_translate.py`, `local_preview_cache.py`, `archive_installer.py`, `source_store.py`, `update_checker.py`, `update_manager.py`, `cleanup.py`, and `patreon.py` never import `customtkinter` and are independently unit-testable.
- `console_setup.py` must run before importing `customtkinter`.
- `i18n.py` must be initialized before importing `gui.py` so initial UI text uses the selected language.

---

## modules/__init__.py - Package Declaration

- **File:** `modules/__init__.py`
- **Purpose:** Marks `modules/` as a Python package. It contains no runtime logic.

---

## modules/config.py - Configuration

### Responsibility

Reads and writes `mod_manager_config.json` in the application directory. It also provides the paths for the `data/` directory (caches, downloads, backups, Patreon profile).

### Public Constants and Functions

| Name | Type | Description |
|------|------|-------------|
| `APP_DIR` | `str` | Application directory; the executable directory when frozen |
| `CONFIG_PATH` | `str` | Full path to `mod_manager_config.json` |
| `VIEW_MODES` | `tuple` | `("compact", "card", "detailed")` |
| `VIEW_MODE_DEFAULTS` | `dict` | Per-page defaults: `local=compact`, `online=detailed`, `patreon=detailed` |
| `README_NAMES` | `list[str]` | Ordered list of recognized README filenames |
| `README_LABELS` | `dict[str, str]` | README filename to GUI button label mapping |
| `get_app_dir()` | `str` | Returns the application directory used by `APP_DIR` |
| `get_data_dir()` | `str` | `APP_DIR/data` (caches, downloads, backups, staging) |
| `get_patreon_profile_dir()` | `str` | `data/patreon_profile` (WebView2 user data) |
| `get_patreon_download_dir()` | `str` | `data/downloads/patreon` |
| `get_gb_cache_dir()` | `str` | `data/cache/gamebanana` (API JSON cache) |
| `get_gb_download_dir()` | `str` | `data/downloads/gamebanana` |

### Class: `ConfigManager`

All methods are static and are called as `ConfigManager.method()`.

#### General I/O

| Method | Return | Description |
|--------|--------|-------------|
| `load()` | `dict` | Loads JSON; returns `{}` if the file is absent or invalid |
| `save(config)` | - | Writes UTF-8 JSON with indentation |
| `ensure_app_dir_writable()` | `(bool, str)` | Checks whether the application directory is writable |

#### Stored Settings

| Getter / Setter | Description |
|-----------------|-------------|
| `get_game_path()` / `set_game_path(path)` | Game root containing `Mods/` |
| `get_language()` / `set_language(lang)` | `auto`, `zh`, `en`, `ja`, `ko`, etc. |
| `get_mod_notes()` / `set_mod_note(name, note)` | Custom Mod display names; an empty note removes the entry |
| `get_mod_images()` / `set_mod_image(name, path)` | Relative or absolute preview-image paths |
| `get_mod_groups()` / `set_mod_groups(groups)` | Group-to-Mod mapping |
| `get_group_order()` / `set_group_order(order)` | Persisted group order |
| `get_collapsed_groups()` / `set_collapsed_groups(names)` | Collapsed group names |
| `get_view_mode(source)` / `set_view_mode(source, mode)` | Per-page view mode (`compact`/`card`/`detailed`); legacy `view_mode=list/card` migrates automatically; a one-argument call remains the local setter |
| `get_hide_sensitive_content()` / `set_hide_sensitive_content(hidden)` | Online "Hide sensitive content" switch (default on) |
| `get_patreon_creators()` / `set_patreon_creators(creators)` | Saved Patreon creator list |
| `get_patreon_hidden_creators()` / `set_patreon_hidden_creators(ids)` | Blocked creator `campaign_id` list |
| `get_patreon_hide_unentitled()` / `set_patreon_hide_unentitled(hide)` | Hide posts without entitlement (default off) |
| `get_ai_base_url()` / `set_ai_base_url(url)` | AI translation base URL (OpenAI-compatible) |
| `get_ai_model()` / `set_ai_model(model)` | AI translation model name |
| `get_proxy()` / `set_proxy(url)` | Global network proxy (http/https; empty `""` follows the system proxy) |
| `get_gb_category_i18n_url()` / `set_gb_category_i18n_url(url)` | Overridable category-translation hot-update URL |

#### Cleanup

| Method | Description |
|--------|-------------|
| `cleanup_mod_data(valid_mod_names)` | Removes notes/images/group references for missing Mods and cleans stale group-order entries |

### Configuration Shape

```json
{
  "language": "auto",
  "view_modes": {
    "local": "compact",
    "online": "detailed",
    "patreon": "detailed"
  },
  "game_path": "D:/Games/MyGame",
  "mod_notes": { "mod_abc": "My Custom Name" },
  "mod_images": { "mod_abc": "screenshot.png" },
  "mod_groups": { "UI Mods": ["mod_a"] },
  "group_order": ["UI Mods"],
  "collapsed_groups": ["Gameplay"],
  "hide_sensitive_content": true,
  "ai_base_url": "https://api.openai.com/v1",
  "ai_model": "gpt-4o-mini",
  "proxy": "",
  "gb_category_i18n_url": "https://...",
  "installed_sources": {
    "uuid": {
      "instance_id": "uuid",
      "provider": "gamebanana",
      "submission_id": 12345,
      "file_id": 67890,
      "folder_name": "mod_abc",
      "path": "D:/Games/MyGame/Mods/mod_abc",
      "file_md5": "...",
      "source_url": "https://gamebanana.com/mods/12345",
      "installed_at": 1700000000
    }
  },
  "patreon_creators": [{"campaign_id": 1, "name": "Creator"}],
  "patreon_hidden_creators": [2],
  "patreon_hide_unentitled": false
}
```

### Used By

- `mod_manager.py` for the initial language
- All GUI pages and business modules via `APP_DIR`, data-dir helpers, and settings

---

## modules/mod_ops.py - Mod Operations

### Responsibility

Contains non-UI business logic for validating directories, scanning local Mods, detecting README files, moving Mod folders, and opening files/folders through the operating system.

### Module-Level Functions

| Function | Description |
|----------|-------------|
| `find_readme_files(mod_path)` | Scans one Mod directory and returns detected `(filename, path)` README pairs (used by background scan tasks) |
| `_open_in_os(path)` | Cross-platform opening: Windows `os.startfile`, macOS `open`, Linux `xdg-open` |

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

### README Name Compatibility

`check_readme_files()` and `find_readme_files()` follow the `README_NAMES` order from `config.py`: the base `README` name plus common language suffixes (`ZH`, `CN`, `ZH_CN`, `CHS`, `TW`, `ZH_TW`, `CHT`, `EN`, `JA`, `JP`, `KO`, `KR`), each with `.md` and `.txt`.

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
| `t(key, zh_default)` | Resolves a translated string; supports `str.format(**kwargs)` placeholders |
| `on_language_changed(callback)` | Registers a language-change callback |
| `lang` | User-selected value |
| `effective_lang` | Language currently in use after auto-detection/fallback |
| `available` | Language codes discovered from `locales/*.json` |

### Detection and Fallback

- Windows first uses `GetUserDefaultUILanguage` (primary ID `0x04` → zh, `0x09` → en, `0x11` → ja, `0x12` → ko).
- Other platforms and failures fall back to Python locale detection.
- Chinese is the source language and does not require a JSON file.
- Other languages load `locales/<code>.json`.
- Missing keys return the Chinese default passed to `t()`.

---

## modules/catalog_view.py - View State (Tk-free)

### Responsibility

A pure-Python view-state layer: view-mode constants and validation, local/remote item view models, page-level selection, online pagination state, sensitivity policy, README 0/1/N presentation, and two-line card text fitting. **Never imports `customtkinter`**, so it is directly unit-testable.

### Constants

| Name | Description |
|------|-------------|
| `COMPACT` / `CARD` / `DETAILED` / `VIEW_MODES` | The three display modes |
| `VIEW_MODE_ORDER` | Switcher order (compact, detailed, card) |

### Helper Functions

| Function | Description |
|----------|-------------|
| `normalize_view_mode(mode, default)` | Validates a mode, falling back to the default |
| `is_sensitive(item)` | Sensitivity check (`has_content_ratings` or `visibility` in (`warn`, `hide`)) |
| `readme_presentation(readme_files)` | README rules: none → `(None, files)`; one → open directly; many → `"README xN"` |
| `fit_card_text(text, font, max_width)` | Natural line breaks, at most two lines, ellipsis on overflow |
| `remote_image_cache_key(url, size, blur)` | Online image cache key (URL, target size, blur policy) |

### Data Classes

- `ScrollAnchor`: scroll anchor `(key, offset)` used to restore position after a view switch
- `LocalItemViewModel` / `RemoteItemViewModel`: row/card view models (`from_mod()` / `from_remote()` builders)
- `LocalCatalogState`: view mode, selected-name set, scroll anchor; `prune_selection()` drops stale names
- `OnlineCatalogState`: query, sort, category, and **pagination state** (`successful_page` advances only on success, `request_generation` invalidates stale responses, `item_by_id` deduplicates), plus `details_in_flight` deduplication

### Used By

- `modules/gui.py`, `modules/online_browser.py`, `modules/patreon_browser.py`

---

## modules/gamebanana.py - GameBanana API Client

### Responsibility

Wraps the GameBanana API v11: online browsing, search, category filtering, details, secure downloads, and image loading. Pure logic (httpx), no GUI dependency.

### Constants

| Name | Description |
|------|-------------|
| `BASE_URL` / `GAME_ID` | `https://gamebanana.com` / `21842` (Arknights: Endfield) |
| `ALLOWED_MODELS` | `("Mod", "Tool", "Sound")` model whitelist |
| `DOWNLOAD_HOSTS` / `MEDIA_HOST` | Download/image host whitelists |
| `MAX_REDIRECTS` / `MAX_DOWNLOAD_BYTES` / `MAX_IMAGE_BYTES` | Download safety limits |

### Exceptions

- `GameBananaError`: base class for API/network errors
- `DownloadValidationError`: download validation failure (host, size, MD5, etc.)

### Data Classes

| Name | Description |
|------|-------------|
| `Page` | Paginated result (`items`, `page`, `record_count`, `has_next`) |
| `RemoteImage` / `RemoteAuthor` / `RemoteFile` | Image (thumbnail/original), author, file (id/name/MD5/version/date/labels) |
| `RemoteCategory` | Category: `model`, `category_id`, `name`, `item_count`, `icon_url`, `has_children` |
| `RemoteMod` | Listing item; includes a `model` field (from `_sModelName`) that selects the details endpoint |
| `RemoteDetails(RemoteMod)` | Details: description, current/archived files, sensitivity flags |

### Class: `GameBananaClient`

| Method | Description |
|--------|-------------|
| `browse(page, per_page, sort, query, category, model, force)` | Browse/search listings; `category` accepts a `RemoteCategory` or a `(model, category_id)` tuple, mapped to `_aFilters[Generic_Category]`; non-Mod models route to `/apiv11/{model}/Index`, search to `Util/Search/Results` |
| `categories(model, game_id, force)` | Root categories: `GET /apiv11/{model}/Categories?_idGameRow=...&_sSort=count`; obsolete categories are skipped |
| `subcategories(model, category_id, force)` | Subcategories: `GET /apiv11/{model}Category/{id}/SubCategories`; records lack `_idRow`, so the ID is parsed from the last `_sUrl` segment; list/dict responses are normalized |
| `details(mod_id, model, force)` | Details: `GET /apiv11/{model}/{id}/ProfilePage`; Tool/Sound profiles are compatible with Mod |
| `download(remote_file, destination, cancel_event, progress_callback)` | Secure download: GameBanana file servers only, restricted redirects, streamed progress, size and MD5 verification |
| `fetch_image(url)` | Image loading from `images.gamebanana.com` with size limits |
| `close()` | Closes the underlying httpx client |

### Notes

- The constructor accepts `proxy=None` (http/https proxy address); the module stays config-free, and callers (`online_browser.py`, the `gui.py` update check) pass `ConfigManager.get_proxy()`

- Category endpoints return a single dict instead of an array for one-record results; the client normalizes this
- The filter key is `Generic_Category` (`Mod_Category` returns UNKNOWN_FILTER)

### Used By

- `modules/online_browser.py`, `modules/gui.py` (update checks)

---

## modules/gb_category_i18n.py - Category Name Translations

### Responsibility

Independent translation layer for GameBanana category names: bundled fallback plus cache plus manual GitHub hot updates, separate from the UI i18n system.

### Files and Constants

- Bundled: `locales/category_translations/gb_category_names.json` (ships with the app; path matches the GitHub repository)
- Cache: `data/cache/gamebanana/gb_category_names.json` (last successful update; takes priority over the bundled file)
- Default URL: `https://raw.githubusercontent.com/gunfub/EFMI_Mod_Manager/main/locales/category_translations/gb_category_names.json` (overridable via `ConfigManager.get/set_gb_category_i18n_url`)
- Format: `{"category_id": {"zh": "translation", ...}}`; `en` is optional
- Safety limits: host whitelist (`raw.githubusercontent.com`), 1 MiB streamed cap, JSON structure validation, atomic cache writes

### Class: `GBCategoryI18n`

| Method | Description |
|--------|-------------|
| `load()` | Reads local translations (cache -> bundled -> empty) at startup; never touches the network |
| `refresh(client)` | Manually fetches the latest translations (requests carry the configured global proxy); returns an error string instead of raising |
| `translate(category_id, name, lang)` | Returns the translation or falls back to the English original |

### Used By

- `modules/online_browser.py` (the "Update category translations" button calls `refresh()`; network access happens only on button click)

---

## modules/ai_translate.py - AI Translation (OpenAI-Compatible)

### Responsibility

Pure-logic AI translation layer (httpx, unit-testable): calls OpenAI-compatible `chat/completions` endpoints to translate text and manages API-key persistence.

### Constants

- `_MAX_TEXT_CHARS = 8000` (overlong text is truncated)
- `_TIMEOUT = 30.0` / `_MODEL_TIMEOUT = 15.0`
- `_KEYRING_SERVICE = "EFMI_Mod_Manager.AI"` (system keyring service name)

### Exception

- `AiTranslateError`: translation errors with user-facing messages

### Public Functions

| Function | Description |
|----------|-------------|
| `translate_text(base_url, api_key, model, text, target_lang)` | Translates text into the target language. `POST {base}/chat/completions`, falling back to `{base}/v1/chat/completions` on 404; timeout/network/401/403/parse failures raise `AiTranslateError` |
| `list_models(base_url, api_key)` | Fetches available model IDs: `GET {base}/models`, falling back to `{base}/v1/models` |
| `get_ai_api_key()` / `set_ai_api_key(key)` | API-key persistence: keyring (Windows Credential Manager) first, config-file fallback; an empty value deletes the entry |

### Notes

- Every request automatically uses the configured global proxy (`ConfigManager.get_proxy()`; empty means the system proxy)

### Used By

- `modules/gui.py` (AI translation settings dialog)
- `modules/online_browser.py` (description translate button)
- `modules/patreon_browser.py` (post content translate button)

---

## modules/local_preview_cache.py - Two-Level Local Preview Cache

### Responsibility

Memory + disk two-level cache for local Mod preview thumbnails: rows/cards render first, then previews load on background threads, keeping the UI smooth with many Mods or large images.

### Class: `LocalPreviewCache`

| Method | Description |
|--------|-------------|
| `__init__(cache_dir, memory_limit=128)` | Takes the disk cache directory and the in-memory LRU limit |
| `load(source_path, target_size)` | Returns a fitted RGB thumbnail (memory hit → disk hit → generate with `ImageOps.fit` and write to disk); `None` on failure |
| `cache_key(source_path, target_size)` | SHA-256 of (path, mtime_ns, size, target size, processing version `PROCESSING_VERSION`) |
| `prune(max_age_days=30, max_entries=512, max_bytes=256 MiB)` | Removes stale entries and enforces count/size limits |

### Implementation Notes

- Disk entries are PNGs written atomically (temp file + `os.replace`)
- The memory tier is a thread-safe LRU (`OrderedDict` + lock); hits return `copy()`ed images
- Disk hits refresh `atime`, feeding the recent-use policy of `prune()`

### Used By

- `modules/gui.py`, `modules/online_browser.py`, `modules/patreon_browser.py`

---

## modules/archive_installer.py - Safe ZIP Installation

### Responsibility

Safe ZIP inspection and transactional Mod installation: local ZIPs and online downloads share one candidate-recognition, security-check, and install pipeline.

### Safety Limits

- `MAX_ENTRIES = 50_000`, `MAX_PATH_DEPTH = 32`, `MAX_COMPRESSION_RATIO = 1000`, `DISK_SAFETY_BYTES = 256 MiB` (zip-bomb protection)
- Rejects: absolute/drive/UNC paths, `..` traversal, symlinks, reparse points, encrypted entries, and unsafe Windows filenames (reserved names, illegal characters)

### Exceptions and Data Classes

| Name | Description |
|------|-------------|
| `ArchiveInstallError` | Installation error (user-facing message) |
| `InstallCancelled` | User cancelled the installation |
| `ArchiveCandidate` / `ArchiveInspection` | Mod candidates and the pre-inspection result (candidates, file counts, size, SHA-256 digest) |
| `InstallSelection` / `InstallResult` | Selection (target name, enable state, candidate) and result |

### Public Functions

| Function | Description |
|----------|-------------|
| `validate_mod_name(name)` | Validates and cleans a Mod folder name |
| `unique_target_name(preferred, target_roots)` | Generates a unique target name on conflicts ("keep both" auto-rename) |
| `inspect_zip(archive_path, archive_name)` | Pre-inspects: candidate recognition, safety checks, SHA-256 pinning |
| `install_zip(inspection, selection, ...)` | Transactional install: extract → stage → atomic replacement; cancel and progress support |
| `install_loose_file(...)` | Single-file install (creates a dedicated Mod folder automatically) |
| `cleanup_staging(max_age_seconds)` | Cleans expired install staging at startup |
| `cleanup_target_temporaries(target_roots)` | Cleans hidden target temp directories (`.efmi-update-*` etc.) |
| `format_bytes(size)` | Human-readable size |

### Used By

- `modules/gui.py` (local ZIP install, online/Patreon download install)
- `modules/update_manager.py` (reuses inspection and safety validation)

---

## modules/source_store.py - Online Source Records

### Responsibility

Records source metadata for online-installed Mods (central index plus a portable `.efmi_mod_manager/source.json` manifest inside each Mod) and saves GameBanana covers as local previews.

### Constant

- `COVER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")`

### Public Functions

| Function | Description |
|----------|-------------|
| `save_gamebanana_source(mod_path, details, remote_file)` | Records a GameBanana install (provider=`gamebanana`, submission/file IDs, MD5, URL) in the central index and the Mod manifest |
| `save_patreon_source(mod_path, campaign_id, post, attachment)` | Records a Patreon install (provider=`patreon`, campaign/post/file IDs) |
| `get_installed_sources()` | Returns all `config["installed_sources"]` records |
| `update_gamebanana_source(record, details, remote_file, path)` | Updates a record after an update install (new file ID/MD5) |
| `restore_source_from_manifest(mod_path, instance_id)` | Reassociates the central index from a Mod manifest (after the Mod was moved manually) |
| `save_gamebanana_cover(fetch, cover_url, mod_path, mod_name, overwrite=False)` | Downloads the cover original into `.efmi_mod_manager/cover.<ext>` and registers it as the preview via a relative path (survives enable/disable moves; existing previews are kept; failures are silent) |

### Used By

- `modules/gui.py` (online installs/updates, backup restore, background cover saving)

---

## modules/update_checker.py - Update Matching

### Responsibility

Conservative manual GameBanana update matching: only a uniquely matching newer file is selected; ambiguous branches are never auto-chosen.

### Data Class

- `UpdateCandidate`: `kind` (`up_to_date` / `update_available` / `ambiguous` / `file_removed` / `source_unavailable` / `review`), `installed_file_id`, `remote_file`

### Public Function

| Function | Description |
|----------|-------------|
| `check_file(installed, details)` | Compares an install record with remote details: exact file ID/MD5 match → up to date; a unique newer file with the same normalized label (NFKC) → update available; multiple candidates → `ambiguous`; original archived/removed → `file_removed` |

### Used By

- `modules/gui.py` ("Check GameBanana Mod Updates")

---

## modules/update_manager.py - Transactional Updates and Rollback

### Responsibility

Transactional replacement and rollback for managed Mod directories: prepare the full new version, back up, swap atomically, and restore automatically on failure.

### Public Functions

| Function | Description |
|----------|-------------|
| `update_from_zip(inspection, candidate, target_path, source_record, progress_callback, cancel_event)` | Transactional update: verify the ZIP is unchanged (SHA-256) → extract into `data/staging/update-*` → copy to a temp dir on the target volume → back up the old version to `data/backups/<instance_id>/` → `os.replace` atomic swap → automatic rollback on failure; keeps only the newest backup. Returns the backup path |
| `restore_backup(source_record)` | Safely swaps the newest backup back into the target directory (`.restore-*` temp dir + atomic replace). Returns the target path |

### Used By

- `modules/gui.py` (update confirmation, restore backup)

---

## modules/cleanup.py - Cache Cleanup

### Responsibility

Per-category cache/garbage measurement and cleanup (multi-select dialog) that never touches login state. Each cleanable category consists of directories (contents cleared, directories kept) plus optional filename-suffix patterns.

### Constants

- `_TEMP_SUFFIXES = (".part", ".crdownload", ".tmp")`: download temp leftovers
- `_PATREON_WEBVIEW_CACHE_DIRS`: pure-cache subdirectories of the WebView2 profile (Network/Cookies etc. excluded)

### Public Functions

| Function | Description |
|----------|-------------|
| `cleanup_targets()` | Cleanable categories: `gb_cache` (GameBanana API cache), `patreon_images` (post image cache), `local_previews` (local thumbnails), `patreon_browser` (WebView2 cache), `downloads_temp` (download temp leftovers) |
| `measure_target(target)` / `measure_all(targets)` | Measures occupied bytes (background thread) |
| `clean_target(target)` / `clean_all(targets)` | Cleans and returns `(freed_bytes, failed_count)`; in-use files are skipped without error |
| `format_size(value)` | Human-readable size (B/KB/MB/GB/TB) |

### Used By

- `modules/gui.py` (Settings → 🧹 Clear Cache dialog)

---

## modules/online_browser.py - GameBanana Online Browser Page

### Responsibility

A native customtkinter GameBanana browsing page: three view modes, search, sorting, dynamic category cascades, sensitive-content protection, a details dialog, download/install, and category-translation hot updates.

### Key Features

- **Three view modes**: compact list / detailed list / card grid (specs match the local page: 85×48 / 150×84 / 256-wide 16:9), preferences persisted per page; card columns recompute on window resize
- **Two control rows**: row one left-aligned (search box, Search, Popular/Recent dropdown button, Category cascade, Update category translations, Refresh); row two right-aligned (view mode, hide sensitive content)
- **Category filtering**: a static level-0 section (All/Mods/Tools/Sounds) plus a dynamic cascade of `CTkOptionMenu`s whose depth is API-driven (`MAX_CATEGORY_DEPTH=8` safeguard); a unified lazy node cache with retry, and static leaves for operator/weapon children to avoid empty requests
- **Sensitive content**: when enabled, thumbnails are blurred plus confirmation before details; when disabled, originals are shown (the title marker always stays)
- **Details dialog**: cover, author, category, version, description (AI-translatable), current/archived files, screenshot gallery with full-image view (black background)
- **Install flow**: pick a file → `GameBananaClient.download()` → `archive_installer` pipeline → `source_store` records the source and saves the cover as the preview in the background
- **Image loading**: bounded executor, processed-thumbnail memory LRU, in-flight deduplication; closing the page cancels queued work
- **Category translations**: the "Update category translations" button calls `GBCategoryI18n.refresh()` (network only then)
- **Network proxy**: the `GameBananaClient` is constructed with the configured global proxy (`ConfigManager.get_proxy()`), applying to browse/search/details/downloads and image requests

### Used By

- `modules/gui.py` (shown/hidden by `_switch_page("online")`)

---

## modules/patreon.py - Patreon Client

### Responsibility

Patreon subscription access: httpx direct API calls preferred (lists, details, downloads; zero browser processes) plus on-demand temporary WebView2 (pywebview; Windows WebView2/Edge kernel) sessions for login, refreshing subscriptions, and external-link download capture.

### Design Points

- Regular requests go straight to the Patreon internal API (`/api/posts`, etc.) with exported login cookies, keeping memory usage low
- When httpx hits a 403 (Cloudflare policy changes), requests automatically retry through a WebView2 fetch fallback
- The browser closes as soon as it is done; cookies persist through the system keyring in chunks (service `EFMI_Mod_Manager.Patreon`), falling back to a `cookies.json` file
- **Proxy support**: httpx requests read `ConfigManager.get_proxy()` per request; the WebView2 browser follows it too via the pure helper `_webview_proxy_arg` (http/https without credentials and with a port → `--proxy-server=...`, else `None`) appended to the Edge kernel's `AdditionalBrowserArguments` in `apply_compat_patches`, scoped to this process only

### Public Data and Functions

| Name | Description |
|------|-------------|
| `CookieStore` | Cookie I/O: keyring first (chunked storage, `cookies.count` commit marker), file fallback |
| `sanitize_filename(name, max_length)` | Sanitizes filenames |
| `render_content_blocks` / `render_content_text` | Post content-block rendering (images/text) and plain-text extraction |
| `parse_posts_page` / `parse_collections_payload` / `parse_campaigns_payload` | Patreon API JSON parsing (posts/collections/creators) |
| `sort_posts(posts, sort)` | Latest / Popular (by likes) sorting |
| `extract_external_links(content_json)` | Extracts external links (MEGA, Google Drive, etc.) |
| `PatreonError` / `PatreonNotLoggedIn` | Exceptions |

### Class: `PatreonSession`

| Method | Description |
|--------|-------------|
| `start()` / `close()` | Starts/closes the browser on demand (timeout-protected) |
| `is_logged_in()` / `current_user_id()` | Login detection (httpx first, browser fallback on 403) |
| `ensure_login(cancel_event)` | Opens a visible browser window to complete login and exports cookies |
| `list_subscribed_creators(cancel_event)` | Refreshes subscriptions: reads every followed creator (temporary browser scrape of the memberships page) |
| `creator_posts(campaign_id, cursor, sort)` | Paginated creator posts (30 per page) |
| `post_details(post_id)` | Post details (content/attachments/external links, loaded on demand) |
| `campaign_collections(campaign_id)` | A creator's collections/posts |
| `download_attachment(url, suggested_name, dest_dir, cancel_event, progress_callback)` | Attachment download (httpx first, WebView2 fallback on 403), progress/cancel |
| `open_external(url, cancel_event, on_message)` | Opens a browser window for manual external downloads and captures the completion event (open-and-capture) |

### Used By

- `modules/patreon_browser.py`

---

## modules/patreon_browser.py - Patreon Subscription Browser Page

### Responsibility

A customtkinter Patreon subscription browsing page: creator list, three post view modes, a details dialog, attachment installation, and external-link capture.

### Key Features

- **Left side**: subscribed/followed creator list (filterable; the 🔄 Refresh Subscriptions button starts a temporary browser scrape); selecting a creator dynamically shows their 📁 Collections below, with 🗂 All Posts restoring the full list
- **Right side**: posts in three view modes (compact/detailed/card, consistent with the GameBanana page, preference persisted); 🕐 Latest / 🔥 Popular sorting (popular by likes, matching the two entries on the author's homepage); 30 posts per page with a "Load More" button and a "showing X / Y posts" counter
- **Post details**: cover image, full text with inline images (click to view full-screen), attachment list, and external links; all loaded on demand with an opened-posts cache; the content is AI-translatable
- **Download & install**: "Download and install" → httpx attachment download → the `archive_installer` pipeline (ZIP with candidate selection, single files get their own Mod folder) → `source_store.save_patreon_source()`; unentitled paid posts show a 🔒 Requires Subscription marker
- **External links**: "Open and capture" opens a browser window for manual download and asks to install the captured file; "Copy" copies the link
- Hide-unentitled toggle and creator blocking

### Used By

- `modules/gui.py` (shown/hidden by `_switch_page("patreon")`; install/external callbacks)

---

## modules/dialogs.py - Custom Dialogs

### Responsibility

Dark custom dialogs (built on `CTkToplevel`, same style as the local Mod note/group dialogs) that replace the native `tkinter.messagebox`; every prompt and confirmation in `gui.py` / `online_browser.py` / `patreon_browser.py` goes through this module, eliminating the white native dialogs that clash with the dark theme.

### Public Functions

| Function | Description |
|----------|-------------|
| `showinfo(title, message, parent=None)` | Info prompt (OK button) |
| `showwarning(title, message, parent=None)` | Warning prompt |
| `showerror(title, message, parent=None)` | Error prompt |
| `askyesno(title, message, parent=None)` | Yes/No confirmation returning a bool (Enter = yes, Esc = no) |

### Implementation Details

- Modal: `transient` + `grab_set` + `wait_window`, centered on the parent window, not resizable
- Dark title bar: `_apply_dialog_titlebar_color()` repaints the DWM title bar synchronously **before** `grab_set()` (withdraw → update → DWM → deiconify, no deferred callbacks), preventing the library's deferred repaint from running after grab and deadlocking the Tk event loop
- Text wraps at `wraplength=460`; button labels come from i18n (`dialog.yes` / `dialog.no` / `dialog.ok`)

### Used By

- `modules/gui.py`, `modules/online_browser.py`, `modules/patreon_browser.py`

---

## modules/gui.py - Main GUI

### Responsibility

Implements the complete `customtkinter` interface: local / GameBanana / Patreon pages, a classic menu bar, three view modes, responsive cards, groups, A-Z navigation, notes, previews, README actions, selection, enable/disable operations, ZIP installation, update checks/backup restore, cache cleanup, and AI translation settings.

### Dependencies

- `customtkinter`
- Pillow through `HAS_PIL`
- pypinyin through `HAS_PYPINYIN`
- Internal modules: `config.py`, `mod_ops.py`, `i18n.py`, `catalog_view.py`, `local_preview_cache.py`, `archive_installer.py`, `source_store.py`, `update_checker.py`, `update_manager.py`, `ai_translate.py`, `cleanup.py`, `gamebanana.py`, `online_browser.py`, `patreon_browser.py`, `dialogs.py`

### Class: `ModManagerApp`

#### Layout Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `PREVIEW_SIZE` | `(85, 48)` | Logical 16:9 thumbnail size in compact rows |
| `CARD_WIDTH` | `256` | Fixed logical card width; about 320 px at 125% DPI |
| `CARD_GAP` | `4` | Logical card-grid spacing |

#### Construction and Startup

| Method | Description |
|--------|-------------|
| `__init__()` | Builds the window, loads view preferences, starts card-area monitoring, and schedules deferred initial loading |
| `run()` | Enters `root.mainloop()` |
| `_build_ui()` | Builds the classic Win32-style menu bar (Settings / More Mod Settings, left-aligned, plus a standalone **ℹ️ About** button, divider line beneath), title bar (title, three page buttons, path label, conditional Browse button), local toolbar, scroll area, alphabet bar, status bar, and progress widgets |
| `_switch_page(page)` | Switches between `local` / `online` / `patreon` and shows/hides the matching frame |
| `_load_config_and_refresh(defer=False)` | Loads the path and optionally defers the initial scan |
| `_refresh_when_layout_ready(attempt=0)` | Waits for a reliable scroll-area width before the first card render |
| `_refresh()` | Validates, scans, cleans metadata, renders Mods, updates stats, and rebuilds navigation |

#### Menus and Dialogs

| Method | Description |
|--------|-------------|
| `_show_settings_menu(anchor)` | Settings popup: Language cascade submenu (current language checkmarked), 📁 Browse Folder, 🧹 Clear Cache, 🌐 AI Translation Settings, 🛰️ Network Proxy Settings |
| `_show_mod_settings_menu(anchor)` | More Mod Settings popup: Restore Backup, Check GameBanana Mod Updates |
| `_show_about_dialog()` | "ℹ️ About" dialog (standalone top-bar button): a `CTkScrollableFrame` with three sections — memorial image + caption / about the project (intro, disclaimer, version, clickable project homepage, GPLv3 license) / open-source credits (name·version·license·copyright per component, click to open the repository, footer points at the bundled `licenses/` and `THIRD_PARTY_NOTICES.txt`); degrades gracefully without PIL or a missing image |
| `_show_cleanup_dialog()` | Cache-cleanup dialog: lists cleanable categories with measured sizes (background thread), cleans the selection, skips download temp leftovers while a download is running, and reports freed space |
| `_show_ai_settings_dialog()` | AI translation settings: Base URL, API Key (`get/set_ai_api_key`, keyring-stored), model combo with "Fetch available models" (`list_models` in the background) |
| `_show_proxy_settings_dialog()` | Network proxy settings: address input (validated on save for http/https scheme and required host/port; socks5 rejected), "Test connection" button (background request to Google `generate_204`, result shown inline), and a restart prompt after saving ("Restart now" / "Later") |
| `_test_proxy_connection(dialog, proxy_var, status_label, test_btn)` | Tests proxy connectivity in the background and shows the result inline |
| `_confirm_proxy_restart()` | Restart confirmation after a proxy save (shown after a 150 ms delay so the old dialog is fully destroyed) |
| `_restart_app()` | Restarts the app: re-launches via `subprocess.Popen` and `os._exit(0)`, best-effort Patreon session shutdown first |
| `_browse_folder()` | Folder picker that sets the game path |
| `_update_browse_btn_visibility()` | Shows the top-bar Browse button only until a folder is selected; the Settings menu entry stays available |

#### Local Page: Views and Rendering

| Method | Description |
|--------|-------------|
| `_view_mode_labels()` / `_update_view_switch_labels()` | Localized labels for the three-mode switch (☷ Compact / ☰ Detailed / ▦ Card) |
| `_on_view_mode_change(label)` | Switches the local view mode and saves it (`set_view_mode("local", ...)`) |
| `_get_card_column_count(width)` | Calculates how many fixed-width cards fully fit |
| `_watch_card_area()` | Reads the underlying Canvas width every 150 ms and reacts only when column count changes |
| `_refresh_card_columns()` | Rebuilds cards while preserving selected Mods and group checkbox state |
| `_show_empty_state(message)` | Clears the Mod area and displays a centered message |
| `_render_mod_list()` | Renders active groups plus the ungrouped section in the current view mode |
| `_create_group_section(...)` | Builds a group header and either a row container or full-width card grid |
| `_create_mod_row(...)` | Builds a compact row (checkbox/preview/name/README/switch/more) |
| `_create_mod_detailed_row(...)` | Builds a detailed row (150×84 preview, display/original names, README summary, switch, open-folder/more) |
| `_create_mod_card(...)` | Builds one fixed-width card (16:9 preview, two-line title, compact action area) |
| `_toggle_group_collapse(group, button)` | Persists collapse state |

#### Local Page: Selection, Groups, Notes, and Previews

| Method | Description |
|--------|-------------|
| `_on_group_checkbox_toggle(group)` | Applies a group checkbox to all Mods in that group |
| `_on_mod_checkbox_toggle(name)` | Synchronizes the containing group checkbox |
| `_select_all()` / `_deselect_all()` / `_invert_selection()` | Bulk selection helpers |
| `_sync_all_group_checkboxes()` | Recomputes every group checkbox |
| `_get_selected_mods()` | Returns selected Mod dictionaries |
| `_create_group()` / `_manage_groups()` | Creates, renames, and deletes groups (dialog stays open for consecutive operations) |
| `_show_more_menu(mod)` | Opens note, preview, and grouping actions |
| `_show_readme_menu(button, files)` | Opens a multi-README selection menu under the button |
| `_toggle_mod_group(mod, group, add)` | Adds or removes a Mod from a group |
| `_resolve_preview_path(mod_path, stored_path)` | Resolves relative paths and paths moved between enabled/disabled directories |
| `_set_preview_image(mod)` / `_clear_preview_image(mod)` | Stores or removes a preview path |
| `_show_full_image(path)` | Opens a black-themed image viewer sized to at most 60% of the screen |
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

#### Install / Update / Backup

| Method | Description |
|--------|-------------|
| `_install_zip_from_file()` | Local ZIP install: inspection dialog (candidates, file counts, size, editable target names, enable/disable target, multi-Mod selection) → `install_zip` transactional install |
| `_install_online_file(...)` | Online download install: `GameBananaClient.download()` → install pipeline → source record + background cover save |
| `_install_patreon_file(...)` | Patreon attachment download install (callback from `patreon_browser`) |
| `_open_patreon_external(...)` | Patreon external-link "open and capture" |
| `_check_updates()` | Checks GameBanana Mod updates: compares each install record via `check_file` → candidate confirmation → `update_from_zip` transactional update (auto-backup, rollback on failure) |
| `_restore_managed_backup()` | Restores the newest pre-update backup via `restore_backup` |

#### Other

| Method | Description |
|--------|-------------|
| `_open_mod_folder(mod)` | Opens the Mod folder in the file manager |
| `_update_stats()` | Updates the status-bar statistics |
| `_apply_language()` | Refreshes all static UI texts and labels, then re-renders the Mod list |
| `_on_language_change(display_value)` | Language submenu handler: saves config → updates i18n → `_apply_language()` |

### Threading Model

- All Tk/customtkinter work runs on the UI thread.
- File moves, downloads, extraction, image decoding, hashing, update checks, cache measurement, and cleanup all run on background threads and never block Tk.
- Worker results return through `root.after(0, callback)`.
- Card-size monitoring runs on the UI thread through `root.after(150, ...)` and rebuilds only when the computed column count changes.
- On exit, queued preview/README background work is cancelled; startup and refresh clean stale staging.

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
                          |-- cleanup_target_temporaries()    archive_installer.py
                          |-- ConfigManager.cleanup_mod_data()
                          |-- LocalCatalogState.prune_selection()  catalog_view.py
                          |-- _render_mod_list()
                          |     `-- _create_group_section()
                          |           |-- _create_mod_row()/_create_mod_detailed_row()
                          |           `-- _create_mod_card()
                          |-- _update_stats()
                          `-- _rebuild_alphabet_bar()
```

User actions:

```text
Page switch       -> _switch_page() -> OnlineBrowserFrame / PatreonBrowserFrame
View switch       -> ConfigManager.set_view_mode(source, mode) -> render
Single toggle     -> _toggle_mod_threaded() -> ModManager.toggle_mod()
Batch toggle      -> _batch_toggle() -> ModManager.toggle_mods_batch()
Group management  -> ConfigManager.set_mod_groups()
Note/preview      -> ConfigManager.set_mod_note()/set_mod_image()
Multiple README   -> _show_readme_menu() -> ModManager.open_file()
Window resize     -> _watch_card_area() -> _refresh_card_columns()
Install ZIP       -> inspect_zip() -> install_zip()
Online install    -> GameBananaClient.download() -> install pipeline
                    -> source_store.save_gamebanana_source() + save_gamebanana_cover()
Patreon install   -> PatreonSession.download_attachment() -> install pipeline
                    -> source_store.save_patreon_source()
Check updates     -> update_checker.check_file() -> update_manager.update_from_zip()
Restore backup    -> update_manager.restore_backup()
Clear cache       -> cleanup.measure_all()/clean_all()
AI translate      -> ai_translate.translate_text()/list_models()
Proxy settings    -> _show_proxy_settings_dialog()
About             -> _show_about_dialog()
```

### Dependency Summary

```text
console_setup.py     no internal dependencies
mod_manager.py   ->  console_setup.py, i18n.py, config.py, gui.py
gui.py           ->  config.py, mod_ops.py, i18n.py, catalog_view.py,
                     local_preview_cache.py, archive_installer.py,
                     source_store.py, update_checker.py, update_manager.py,
                     ai_translate.py, cleanup.py, gamebanana.py,
                     online_browser.py, patreon_browser.py
online_browser.py ->  gamebanana.py, gb_category_i18n.py, catalog_view.py,
                      ai_translate.py, config.py, i18n.py
patreon_browser.py -> patreon.py, catalog_view.py, ai_translate.py,
                      local_preview_cache.py, config.py, i18n.py
dialogs.py       ->  i18n.py (button labels)
patreon.py       ->  config.py (paths), i18n.py (errors)
archive_installer.py -> config.py (APP_DIR)
update_manager.py ->  archive_installer.py, config.py
source_store.py  ->  config.py
ai_translate.py  ->  config.py (keyring fallback)
cleanup.py       ->  config.py (data dir)
gamebanana.py    ->  httpx only
i18n.py          ->  locales/*.json
```

Pure-logic layer (no Tk): `config.py`, `mod_ops.py`, `i18n.py`, `catalog_view.py`, `gamebanana.py`, `gb_category_i18n.py`, `ai_translate.py`, `local_preview_cache.py`, `archive_installer.py`, `source_store.py`, `update_checker.py`, `update_manager.py`, `cleanup.py`, `patreon.py`. UI layer: `gui.py`, `online_browser.py`, `patreon_browser.py`, `dialogs.py`.
