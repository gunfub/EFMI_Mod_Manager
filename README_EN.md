# EFMI Mod Manager

<div align="center"><img src="./README.assets/酸橙色的纪念.png" height="200" /></div>

**English** | [中文](README.md)

A `customtkinter`-based Mod manager that enables/disables Mods by moving folders. Primarily supports Windows, with Linux and macOS compatibility.

> **Important**: EFMI Mod Manager does not handle Mod loading, parsing, or injection. Mod loading and runtime logic is performed by EFMI during game startup. This program only provides a graphical frontend for quickly enabling or disabling Mods — under the hood, it simply moves Mod folders between the `Mods` (enabled) and `Disabled_Mods` (disabled) directories to control which Mods EFMI should load at startup. This program does not modify any Mod content, nor does it participate in EFMI's runtime behavior.

## Features

- **Mod Management**: Scans `Mods` and `Disabled_Mods` folders, one-click toggle enable/disable
- **Batch Operations**: Select all, invert selection, batch enable, batch disable
- **Group Management**: Create, rename, delete groups; collapse/expand groups
- **Three View Modes**: Compact list / detailed list / 16:9 preview cards on both the local and online pages, each page remembering its own last choice
- **Responsive Card Layout**: Keeps cards at a consistent size, adds columns on wider windows, and aligns groups consistently
- **Custom Notes**: Set custom display names for each Mod
- **Preview Images**: Set preview thumbnails, click to view full-size, and show placeholders when no image is available; two-level memory + disk caching with background loading
- **README Detection**: Recognizes common Chinese, English, Japanese, and Korean README names; multiple READMEs show a `README xN` selection menu
- **Local ZIP Installation**: Inspect archive contents before installing, edit target folder names, choose enabled/disabled targets, and install multiple Mods from one ZIP
- **GameBanana Online Mods**: Browse and search Arknights: Endfield Mods (Mods / Tools / Sounds) with popular/recent sorting, pagination, and official-style level-by-level category filtering; sensitive content is blurred by default with a second confirmation
- **Online Install & Updates**: View details (description, author, version, screenshots), pick a file to download and install; sources are recorded automatically and covers are saved as local previews; "Check updates" backs up before updating and rolls back on failure, plus "Restore backup"
- **Category Translation Hot Updates**: Bundled zh/ja/ko category names; the "Update category translations" button fetches the latest translations manually (untranslated categories fall back to English)
- **AI Translation**: One-click translation of online descriptions and Patreon post content (OpenAI-compatible API; the API key is stored in the system credential manager, never in the config file)
- **Cache Cleanup**: "Settings → 🧹 Clear Cache" measures and cleans caches by category (GameBanana cache, Patreon images, local thumbnails, browser cache, download temp leftovers) without touching login state
- **Classic Menu Bar**: Win32-style menus at the top of the window — "Settings" (Language, Browse Folder, Clear Cache, AI Translation Settings, Network Proxy Settings) and "More Mod Settings" (Restore Backup, Check GameBanana Mod Updates), plus a standalone "ℹ️ About" button (project intro, disclaimer, and open-source credits)
- **Network Proxy Settings**: "Settings → 🛰️ Network Proxy Settings" lets you set a manual http/https proxy for all network requests (GameBanana, Patreon, AI translation) and the Patreon browser; supports "Test connection" and one-click restart to apply; leave it empty to follow the system proxy
- **Dark Custom Dialogs**: all native message boxes are replaced with dark dialogs matching the app theme — no more white system dialogs
- **Patreon Subscribed Mods**: Automatically reads your subscribed creators (WebView2 browser session, no extra browser engine download), browses paid posts (latest/popular sorting, collections, 30 posts per page with Load More), downloads Patreon attachments and installs them as Mods; external links (MEGA / Google Drive, etc.) are downloaded manually in a browser window and captured automatically
- **Multi-language A-Z Quick Jump**: The sidebar letter index supports English and Chinese Pinyin initials (optional `pypinyin` dependency) for fast mixed sorting and navigation
- **Multi-language UI**: Auto-detects system language, supports 中文 / English / 日本語 / 한국어 switching
- **DPI Dynamic Scaling**: Adapts to Windows high-DPI displays (Windows only)
- **Dark Theme**: Modern dark UI based on customtkinter
- **Console Hidden**: Terminal window hidden by default after PyInstaller packaging (Windows only; create a `debug_mode` file in the program directory to show it)

## Screenshots

![](./README.assets/screenshot-1.png)

![](./README.assets/screenshot-2.png)

![](./README.assets/screenshot-3.png)

[More Screenshots](./README.assets/more_screenshot.md)

## Directory Structure Requirements

Point the program to a game directory with the following structure:

```
Game Directory/
├── Mods/                  # Enabled Mods (must exist)
│   ├── ModA/
│   └── ModB/
└── Disabled_Mods/         # Disabled Mods (auto-created on first run)
    └── ModC/
```

Enabling/disabling a Mod is essentially moving its folder between `Mods` and `Disabled_Mods`.

## Installation & Running

### Method 1: pip (Traditional)

#### Dependencies

- Python 3.8+
- customtkinter
- httpx (HTTP client for online browsing / Patreon / AI translation)
- Pillow (optional, for preview images)
- pypinyin (optional, for Chinese Pinyin initial index)
- pywebview (optional, for Patreon login/external downloads; uses the system WebView2 on Windows)
- keyring (optional, stores API keys / Patreon cookies in the system credential manager; falls back to files)

```bash
pip install customtkinter httpx Pillow pypinyin pywebview keyring
```

#### Run Directly

```bash
python mod_manager.py
```

#### Package as exe

```bash
pip install pyinstaller
pyinstaller --name "EFMI_Mod_Manager" mod_manager.py
```

- `--windowed` hides the terminal window
- For debugging, create an empty file named `debug_mode` in the exe directory to show the console

### Method 2: uv (Recommended, Faster & Lighter)

[uv](https://github.com/astral-sh/uv) is a Rust-based fast Python package manager that reads `pyproject.toml` directly.

#### Install uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

#### Install Dependencies

```bash
# Auto-sync dependencies from pyproject.toml (recommended)
uv sync

# Or install manually
uv pip install customtkinter httpx Pillow pypinyin pywebview keyring
```

#### Run Directly

```bash
# Run in the uv-managed virtual environment
uv run python mod_manager.py
```

#### Package as exe

```bash
# Install dev dependencies (includes pyinstaller)
uv sync --group dev

# Package using pyinstaller in the uv environment
uv run pyinstaller --name "EFMI_Mod_Manager" mod_manager.py
```

- `--windowed` hides the terminal window
- For debugging, create an empty file named `debug_mode` in the exe directory to show the console

## Usage

### 1. Select Game Directory

Click **📁 Browse** in the top bar to select the game root directory containing the `Mods` folder. The program will auto-detect and create the `Disabled_Mods` folder if needed.

### 2. Manage Mods

- **Switch views**: Use the **☷ Compact / ☰ Detailed / ▦ Card** control on the right side of the toolbar; the local and online pages each remember their own choice
- **Enable/Disable a single Mod**: Click the switch in a Mod row or card
- **Batch operations**: Check the checkboxes in front of Mods (or use the group checkbox to select all in a group), then click **Batch Enable** or **Batch Disable**
- **Card layout**: Cards keep a consistent size and gain columns as the window gets wider; each group is centered while cards remain left-aligned inside its grid
- **Install ZIP**: Click **Install ZIP** and pick an archive; confirm the candidate Mods, target folder names, and enabled/disabled target before installing (archives are safety-inspected for dangerous paths, zip bombs, and invalid filenames)
- **Menu bar**: The classic menu at the very top — "Settings" (Language / Browse Folder / 🧹 Clear Cache / 🌐 AI Translation Settings / 🛰️ Network Proxy Settings) and "More Mod Settings" (Restore Backup / Check GameBanana Mod Updates), with a standalone "ℹ️ About" button on the right; the 📁 Browse Folder button hides once a folder is picked

### 3. Group Management

- **Create a new group**: Click **➕ New Group** in the toolbar
- **Manage groups**: Click **✏️ Manage Groups** in the toolbar to create, rename, or delete groups. Dialog stays open for consecutive operations.
- **Add Mod to a group**: Click the **⋯** button on the right of a Mod row → **📁 Add to / Remove from Group**
- **Collapse group**: Click the arrow button on the left side of the group header bar

### 4. More Actions

Click the **⋯** button on the right of a Mod row:

| Action | Description |
|------|------|
| 📝 Edit Note | Set a custom display name for the Mod (replaces the folder name) |
| 🖼️ Set Preview | Select an image as the Mod thumbnail |
| 📁 Group Actions | Add or remove a Mod from groups |
| 🗑️ Clear Note/Preview | Remove existing notes or preview images |

README files appear in each Mod's action area. All three view modes share one aggregation rule: no button when absent, direct open for a single README, and a **📄 README xN** button with a selection menu when multiple files exist. Supported names include `.md` / `.txt` variants with common language suffixes such as `ZH`, `CN`, `CHS`, `TW`, `EN`, `JA`, `JP`, `KO`, and `KR`.

### 5. GameBanana Online Mods

Switch to the **GameBanana** page at the top to browse and search online Mods for Arknights: Endfield:

- **Category filtering**: Official-style level-by-level categories (Mods / Tools / Sounds); search, sorting, and "Load More" respect the selected category, and new categories appear without updating the app (the "Update category translations" button fetches the latest category names manually; untranslated categories fall back to English)
- **Sorting and pagination**: 🕐 Popular / Recent sorting, with a "Load More" button at the bottom
- **Three view modes**: ☷ Compact list / ☰ Detailed list / ▦ Card grid (choice saved automatically)
- **Sensitive content**: The "Hide sensitive content" switch is on by default — sensitive thumbnails are blurred with a second confirmation before viewing; turn it off to show originals directly (the sensitive title marker always stays)
- **Details and install**: Click an item to open details (cover, description, author, version, screenshots, current/archived files), pick a specific file to download and install; the source is recorded automatically and the GameBanana cover is saved as the local preview (existing previews are kept)
- **AI translation**: Click **🌐 Translate** in the details dialog to translate the description into the UI language (requires Base URL, API Key, and a model configured under "Settings → AI Translation Settings")
- **Updates and backup**: "More Mod Settings → Check GameBanana Mod Updates" checks installed online Mods for new versions (backs up before updating and rolls back on failure); "Restore backup" returns to the previous version

### 6. Clear Cache, AI Translation Settings, and Network Proxy

- **🧹 Clear Cache** (Settings menu): check the categories to clean and see their occupied space — GameBanana cache, Patreon image cache, local thumbnails, Patreon browser cache, and download temp leftovers; clearing the browser cache does not affect login state
- **🌐 AI Translation Settings** (Settings menu): configure an OpenAI-compatible Base URL, API Key, and model ("Fetch available models" lists them automatically); the API key is stored in the system credential manager, never in the config file
- **🛰️ Network Proxy Settings** (Settings menu): set a manual http/https proxy address (with an optional "Test connection" check) that applies to all network requests and the Patreon browser; after saving you are prompted to restart — restart with one click or later; leave it empty to follow the system proxy

### 7. Quick Jump

The right sidebar A-Z index has two levels:

- **Primary Index (global)**: A-Z buttons based on group name initials. Click to jump to the corresponding group header. An ungrouped button is at the bottom.
- **Secondary Mini Index (per group)**: Each group content area has an embedded mini A-Z bar on the right, showing only the initials that actually appear within the group. Click to jump to the corresponding Mod within that group. Multiple mini indexes are simultaneously visible and independent.

With `pypinyin` installed, Chinese names are sorted and indexed by Pinyin initials (e.g., a group named "中文" appears under "Z"). Without it, raw characters are used for sorting.

### 8. Patreon Subscribed Mods

Switch to the **Patreon** page at the top to browse posts (paid + public) from creators you follow or subscribe to:

- **Login**: Click **Login to Patreon** on first use; the app temporarily opens a browser window (built on the Windows WebView2/Edge kernel) to complete login and save the session. **Daily browsing (post lists, details, attachment downloads) goes straight to the API via httpx with no browser process and minimal memory usage**; the browser only starts briefly for login, refreshing subscriptions, and external downloads, then closes itself
- **Subscription list**: Click **🔄 Refresh Subscriptions** to read every creator you follow (temporarily starts the browser, then closes it); the input box at the top filters by name
- **Collections**: After selecting a creator, their **📁 Collections** appear dynamically below the list (each creator's collections differ, loaded per creator); click a collection to browse its posts, **🗂 All Posts** restores the full list (collection posts load at once, no pagination)
- **Post views**: The right-side post list supports the same **☷ Compact / ☰ Detailed / ▦ Card** styles as the GameBanana page (choice saved automatically) with **🕐 Latest / 🔥 Popular** sorting (popular by likes, matching the two entries on the author's homepage); **30 posts per page, a "Load More" button at the bottom, and a "showing X / Y posts" counter at the top**; the list loads only titles, dates, paywall markers, and small covers (content/attachments load on demand for fast browsing)
- **Post details**: Click a post (or the **📄 Details** button) to open the details dialog with the cover image, **the full post text and inline images (click images for full-screen view)**, attachment lists, and external download links — all loaded on demand (already-opened posts use the cache)
- **Download attachments**: **Download and install** on the details page downloads the Patreon-hosted attachment and runs the standard install flow (ZIPs offer candidate selection, single files get their own Mod folder automatically); unentitled paid posts show a **🔒 Requires Subscription** marker
- **External links**: Some authors host files on MEGA / Google Drive, etc. **Open and capture** opens a browser window — finish the download manually there, and the file is captured and prompts to install; **Copy** copies the link

> Note: The Patreon feature is only for downloading content you are subscribed to; please respect each creator's license terms. External sites (MEGA, Google Drive, etc.) require you to log in once in the browser window.

### 9. Language Switching

Click **Settings → Language** in the top menu bar to switch between languages. Available options:

- **Auto**: Automatically detects the system language (zh/en/ja/ko) and uses the appropriate translation
- **中文**: Force Chinese (source language, no translation file needed)
- **English**: Force English
- **日本語**: Force Japanese
- **한국어**: Force Korean

## Configuration

Program configuration is saved in `mod_manager_config.json` (in the same directory as the program):

- `language`: Language setting (`"auto"`, `"zh"`, `"en"`, `"ja"`, `"ko"`)
- `view_modes`: Per-page display mode (`local` / `online` / `patreon`, values `"compact"` / `"card"` / `"detailed"`; legacy `view_mode=list/card` migrates automatically)
- `game_path`: Game directory path
- `mod_notes`: Mod display names
- `mod_images`: Mod preview image paths (relative paths for images inside Mod folders, absolute paths for external images)
- `mod_groups`: Group data
- `group_order`: Group ordering
- `collapsed_groups`: List of collapsed groups
- `hide_sensitive_content`: Online "Hide sensitive content" switch (default `true`)
- `installed_sources`: Source records for online-installed Mods (GameBanana / Patreon IDs, MD5, paths, etc.)
- `patreon_creators` / `patreon_hidden_creators` / `patreon_hide_unentitled`: Patreon creator list and display settings
- `ai_base_url` / `ai_model`: AI translation endpoint and model (the API key is stored in the system credential manager, not in this file; it falls back to an `ai_api_key` field when keyring is unavailable)
- `proxy`: Global network proxy address (http/https; empty follows the system proxy)
- `gb_category_i18n_url`: Optional override for the category-translation hot-update URL

Other data lives under `data/`: `cache/` (API caches and thumbnails), `downloads/` (download staging), `staging/` (install staging), `backups/` (update backups), `patreon_profile/` (WebView2 user data).

## Code Structure

The project uses a modular architecture, with core code split into the `modules/` package:

```
mod_manager.py              ← Entry point, startup initialization
modules/
├── __init__.py             ← Package declaration
├── config.py               ← Configuration management (JSON read/write, groups, notes, previews, data/ dirs)
├── mod_ops.py              ← Local Mod operations (scan, move, validate, README detection)
├── i18n.py                 ← Internationalization (system language detection, JSON translation loading)
├── console_setup.py        ← Console/warning management (stderr redirect, pkg_resources warning suppression)
├── catalog_view.py         ← View state (three view modes, page selection/pagination state, README 0/1/N rules)
├── local_preview_cache.py  ← Two-level local preview caching (memory LRU + disk thumbnails)
├── gamebanana.py           ← GameBanana API client (browse/categories/details/secure downloads)
├── gb_category_i18n.py     ← Category name translations (bundled + cache + GitHub manual hot updates)
├── ai_translate.py         ← AI translation (OpenAI-compatible API, keyring-stored key)
├── archive_installer.py    ← Safe ZIP / single-file installation (inspection, transactional install)
├── source_store.py         ← Online source records (installed_sources + .efmi_mod_manager/source.json + cover saving)
├── update_checker.py       ← Conservative GameBanana update matching
├── update_manager.py       ← Transactional updates / backup restore (atomic swap, automatic rollback)
├── cleanup.py              ← Cache cleanup (per-category measurement and cleaning, login state untouched)
├── gui.py                  ← Main GUI (local page + menu bar, event handling, batch operations)
├── online_browser.py       ← GameBanana online browsing page (category cascades, three views, detail install)
├── patreon.py              ← Patreon client (httpx direct API + WebView2 login/scrape/download capture)
├── patreon_browser.py      ← Patreon subscription browsing page (creator list, posts, download/external)
└── dialogs.py              ← Custom dark dialogs (replacing the native messagebox)

locales/
├── en.json                 ← English translations
├── ja.json                 ← Japanese translations
├── ko.json                 ← Korean translations
└── category_translations/  ← GameBanana category name translations (gb_category_names.json)
```

**Module call chain:**  
`mod_manager.py` → `console_setup.py` + `i18n.py` (startup phase)  
`mod_manager.py` → `gui.py` → `config.py` + `mod_ops.py`

For detailed documentation, see [English Modules Documentation](modules/modules_EN.md) / [中文模块文档](modules/modules.md).

## Tech Stack

- **Language**: Python 3
- **GUI Framework**: [customtkinter](https://github.com/TomSchimansky/CustomTkinter)
- **Image Processing**: Pillow (PIL)
- **HTTP**: httpx
- **Credential Storage**: keyring (Windows Credential Manager)
- **Patreon Browser Session**: [pywebview](https://github.com/r0x0r/pywebview) (Windows 10/11 uses the system WebView2, no extra browser engine download; Linux needs system WebKitGTK)
- **Packaging**: PyInstaller

## License

This project is open source and available under the [GPLv3 License](https://github.com/gunfub/EFMI_Mod_Manager/blob/main/LICENSE).
