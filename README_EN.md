# EFMI Mod Manager

**English** | [中文](README.md)

A `customtkinter`-based Mod manager that enables/disables Mods by moving folders. Primarily supports Windows, with Linux and macOS compatibility.

> **Important**: EFMI Mod Manager does not handle Mod loading, parsing, or injection. Mod loading and runtime logic is performed by EFMI during game startup. This program only provides a graphical frontend for quickly enabling or disabling Mods — under the hood, it simply moves Mod folders between the `Mods` (enabled) and `Disabled_Mods` (disabled) directories to control which Mods EFMI should load at startup. This program does not modify any Mod content, nor does it participate in EFMI's runtime behavior.

## Features

- **Mod Management**: Scans `Mods` and `Disabled_Mods` folders, one-click toggle enable/disable
- **Batch Operations**: Select all, invert selection, batch enable, batch disable
- **Group Management**: Create, rename, delete groups; collapse/expand groups
- **Custom Notes**: Set custom display names for each Mod
- **Preview Images**: Set preview thumbnails for each Mod, click to view full-size
- **README Detection**: Automatically detects `README.md` / `README.txt` files in Mod folders, one-click open
- **Multi-language UI**: Auto-detects system language, supports 中文 / English / 日本語 / 한국어 switching
- **DPI Dynamic Scaling**: Adapts to Windows high-DPI displays (Windows only)
- **Dark Theme**: Modern dark UI based on customtkinter
- **Console Hidden**: Terminal window hidden by default after PyInstaller packaging (Windows only; create a `debug_mode` file in the program directory to show it)

## Screenshots

![](./README.assets/screenshot-1.png)

![](./README.assets/screenshot-2.png)

![](./README.assets/screenshot-3.png)

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
- Pillow (optional, for preview images)
- pypinyin (optional, for Chinese Pinyin initial index)

```bash
pip install customtkinter Pillow pypinyin
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
uv pip install customtkinter Pillow pypinyin
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

- **Enable/Disable a single Mod**: Click the switch button on the right side of each Mod row
- **Batch operations**: Check the checkboxes in front of Mods (or use the group checkbox to select all in a group), then click **Batch Enable** or **Batch Disable**

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

### 5. Quick Jump

The right sidebar A-Z index has two levels:

- **Primary Index (global)**: A-Z buttons based on group name initials. Click to jump to the corresponding group header. An ungrouped button is at the bottom.
- **Secondary Mini Index (per group)**: Each group content area has an embedded mini A-Z bar on the right, showing only the initials that actually appear within the group. Click to jump to the corresponding Mod within that group. Multiple mini indexes are simultaneously visible and independent.

With `pypinyin` installed, Chinese names are sorted and indexed by Pinyin initials (e.g., a group named "中文" appears under "Z"). Without it, raw characters are used for sorting.

### 6. Language Switching

Click the language dropdown in the top bar to switch between languages. Available options:

- **Auto**: Automatically detects the system language (zh/en/ja/ko) and uses the appropriate translation
- **中文**: Force Chinese (source language, no translation file needed)
- **English**: Force English
- **日本語**: Force Japanese
- **한국어**: Force Korean

## Configuration

Program configuration is saved in `mod_manager_config.json` (in the same directory as the program):

- `language`: Language setting (`"auto"`, `"zh"`, `"en"`)
- `game_path`: Game directory path
- `mod_notes`: Mod display names
- `mod_images`: Mod preview image paths (relative paths for images inside Mod folders, absolute paths for external images)
- `mod_groups`: Group data
- `group_order`: Group ordering
- `collapsed_groups`: List of collapsed groups

## Code Structure

The project uses a modular architecture, with core code split into the `modules/` package:

```
mod_manager.py              ← Entry point, startup initialization
modules/
├── __init__.py             ← Package declaration
├── config.py               ← Configuration management (JSON read/write, groups, notes, previews)
├── mod_ops.py              ← Mod operations (scan, move, validate, README detection)
├── i18n.py                 ← Internationalization (system language detection, JSON translation loading)
├── console_setup.py        ← Console/warning management (stderr redirect, pkg_resources warning suppression)
└── gui.py                  ← GUI main interface (customtkinter window, event handling, batch operations)

locales/
├── en.json                 ← English translations
├── ja.json                 ← Japanese translations
└── ko.json                 ← Korean translations
```

**Module call chain:**  
`mod_manager.py` → `console_setup.py` + `i18n.py` (startup phase)  
`mod_manager.py` → `gui.py` → `config.py` + `mod_ops.py`

For detailed documentation, see [modules/modules.md](modules/modules.md).

## Tech Stack

- **Language**: Python 3
- **GUI Framework**: [customtkinter](https://github.com/TomSchimansky/CustomTkinter)
- **Image Processing**: Pillow (PIL)
- **Packaging**: PyInstaller

## License

This project is open source and available under the [GPLv3 License](https://github.com/gunfub/EFMI_Mod_Manager/blob/main/LICENSE).
