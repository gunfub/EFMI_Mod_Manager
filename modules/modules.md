# EFMI Mod Manager — Modules 文档

> 本文档详细描述 `modules/` 文件夹中每个 Python 模块的职责、公共接口、调用关系与实现细节。

**中文** | [English](modules_EN.md)

---

## 目录

1. [整体架构](#整体架构)
2. [modules/__init__.py — 包声明](#modules__init__py--包声明)
3. [modules/config.py — 配置管理](#modulesconfigpy--配置管理)
4. [modules/mod_ops.py — Mod 操作](#modulesmod_opspy--mod-操作)
5. [modules/console_setup.py — 控制台与启动设置](#modulesconsole_setuppy--控制台与启动设置)
6. [modules/i18n.py — 多语言](#modulesi18npy--多语言)
7. [modules/catalog_view.py — 视图状态（无 Tk 依赖）](#modulescatalog_viewpy--视图状态无-tk-依赖)
8. [modules/gamebanana.py — GameBanana API 客户端](#modulesgamebananapy--gamebanana-api-客户端)
9. [modules/gb_category_i18n.py — 分类名翻译（手动热更新）](#modulesgb_category_i18npy--分类名翻译手动热更新)
10. [modules/ai_translate.py — AI 翻译（OpenAI 兼容）](#modulesai_translatepy--ai-翻译openai-兼容)
11. [modules/local_preview_cache.py — 本地预览图两级缓存](#moduleslocal_preview_cachepy--本地预览图两级缓存)
12. [modules/archive_installer.py — ZIP 安全安装](#modulesarchive_installerpy--zip-安全安装)
13. [modules/source_store.py — 在线来源记录](#modulessource_storepy--在线来源记录)
14. [modules/update_checker.py — 更新匹配](#modulesupdate_checkerpy--更新匹配)
15. [modules/update_manager.py — 事务更新与回滚](#modulesupdate_managerpy--事务更新与回滚)
16. [modules/cleanup.py — 缓存清理](#modulescleanuppy--缓存清理)
17. [modules/online_browser.py — GameBanana 在线浏览页](#modulesonline_browserpy--gamebanana-在线浏览页)
18. [modules/patreon.py — Patreon 客户端](#modulespatreonpy--patreon-客户端)
19. [modules/patreon_browser.py — Patreon 订阅浏览页](#modulespatreon_browserpy--patreon-订阅浏览页)
20. [modules/dialogs.py — 自定义对话框](#modulesdialogspy--自定义对话框)
21. [modules/gui.py — GUI 主界面](#modulesguipy--gui-主界面)
22. [调用流程图](#调用流程图)

---

## 整体架构

```
mod_manager.py          ← 入口文件，启动初始化 + 导入 GUI
  │
  ├── modules/console_setup.py   ← 控制台/警告管理（最早导入）
  ├── modules/i18n.py            ← 多语言（GUI 加载前初始化）
  └── modules/gui.py             ← 主窗口 UI（导入 customtkinter）
        ├── modules/config.py            ← 配置读写（含语言设置）
        ├── modules/mod_ops.py           ← 本地 Mod 扫描/移动
        ├── modules/catalog_view.py      ← 视图模式/页面状态（无 Tk）
        ├── modules/local_preview_cache.py ← 本地预览图两级缓存
        ├── modules/archive_installer.py ← ZIP 安全安装管线
        ├── modules/source_store.py      ← 在线来源记录/封面保存
        ├── modules/update_checker.py    ← 更新匹配
        ├── modules/update_manager.py    ← 事务更新/备份恢复
        ├── modules/ai_translate.py      ← AI 翻译设置与调用
        ├── modules/cleanup.py           ← 缓存清理
        ├── modules/gamebanana.py        ← GameBanana API 客户端
        ├── modules/gb_category_i18n.py  ← 分类名翻译
        ├── modules/online_browser.py    ← GameBanana 在线浏览页
        ├── modules/patreon.py           ← Patreon 客户端（httpx + WebView2）
        ├── modules/patreon_browser.py   ← Patreon 订阅浏览页
        └── modules/dialogs.py           ← 自定义对话框（深色，替代原生 messagebox）
```

**核心原则：**
- 入口文件 `mod_manager.py` 是所有 import 的调度的唯一入口。
- 模块按「无 Tk 依赖的纯逻辑层」与「UI 层」分层：`config.py` / `mod_ops.py` / `i18n.py` / `catalog_view.py` / `gamebanana.py` / `gb_category_i18n.py` / `ai_translate.py` / `local_preview_cache.py` / `archive_installer.py` / `source_store.py` / `update_checker.py` / `update_manager.py` / `cleanup.py` / `patreon.py` 均可独立单元测试，不导入 `customtkinter`。
- `console_setup.py` 必须在 `import customtkinter` **之前**调用。
- `i18n.py` 必须在 `import gui` **之前**初始化，确保 GUI 构建时语言已就绪。

---

## modules/__init__.py — 包声明

- **文件**：`modules/__init__.py`
- **内容**：`# EFMI Mod Manager - modules package`
- **作用**：将 `modules/` 目录标记为 Python 包，允许 `from modules.xxx import yyy` 语法。无实际逻辑。

---

## modules/config.py — 配置管理

### 职责

管理程序的持久化配置，读写 `mod_manager_config.json`（JSON 格式，与可执行文件同目录）。同时提供 `data/` 目录下的缓存、下载、备份、Patreon 配置目录路径。

### 公共常量与函数

| 名称 | 类型 | 说明 |
|------|------|------|
| `APP_DIR` | `str` | 程序所在目录（PyInstaller 下为 exe 同目录，否则为仓库根目录） |
| `CONFIG_PATH` | `str` | 配置文件的完整路径 `APP_DIR/mod_manager_config.json` |
| `VIEW_MODES` | `tuple` | `("compact", "card", "detailed")` 三种显示模式 |
| `VIEW_MODE_DEFAULTS` | `dict` | 各页面默认视图：`local=compact`、`online=detailed`、`patreon=detailed` |
| `README_NAMES` | `list[str]` | 支持的 README 文件名列表 |
| `README_LABELS` | `dict[str, str]` | README 文件名 → GUI 按钮标签 的映射 |
| `get_app_dir()` | `str` | 返回程序所在目录（同 `APP_DIR`） |
| `get_data_dir()` | `str` | `APP_DIR/data`（缓存/下载/备份/暂存根目录） |
| `get_patreon_profile_dir()` | `str` | `data/patreon_profile`（WebView2 用户数据目录） |
| `get_patreon_download_dir()` | `str` | `data/downloads/patreon` |
| `get_gb_cache_dir()` | `str` | `data/cache/gamebanana`（API JSON 缓存） |
| `get_gb_download_dir()` | `str` | `data/downloads/gamebanana` |

### 类：`ConfigManager`

全静态方法类，无需实例化。所有方法直接通过 `ConfigManager.xxx()` 调用。

#### 通用读写

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `load()` | — | `dict` | 读取配置 JSON，不存在或损坏返回 `{}` |
| `save(config)` | `config: dict` | — | 将 dict 写入 JSON 文件（UTF-8, indent=2） |
| `ensure_app_dir_writable()` | — | `(bool, str)` | 检查程序目录是否可写（不可写时相关功能降级） |

#### 游戏路径 / 语言 / 备注 / 预览图 / 分组

| 方法 | 说明 |
|------|------|
| `get_game_path()` / `set_game_path(path)` | 游戏根目录 |
| `get_language()` / `set_language(lang)` | 语言（`"auto"` / `"zh"` / `"en"` 等），默认 `"auto"` |
| `get_mod_notes()` / `set_mod_note(name, note)` | Mod 备注（note 为空则删除） |
| `get_mod_images()` / `set_mod_image(name, path)` | Mod 预览图（相对路径/绝对路径） |
| `get_mod_groups()` / `set_mod_groups(groups)` | 分组数据整体替换 |
| `get_group_order()` / `set_group_order(order)` | 分组排序 |
| `get_collapsed_groups()` / `set_collapsed_groups(lst)` | 折叠分组列表 |

#### 视图模式（按页面独立）

| 方法 | 说明 |
|------|------|
| `get_view_mode(source="local")` | 读取指定页面（`local`/`online`/`patreon`）的视图模式；无效值回退默认；旧 `view_mode=list/card` 自动迁移为 `compact/card` |
| `set_view_mode(source, mode)` | 保存指定页面视图模式；单参数调用兼容旧的本地设置器 |

#### 在线与 Patreon 设置

| 方法 | 说明 |
|------|------|
| `get_hide_sensitive_content()` / `set_hide_sensitive_content(hidden)` | 「隐藏敏感内容」开关（默认开启） |
| `get_patreon_creators()` / `set_patreon_creators(creators)` | 已保存的 Patreon 创作者列表 |
| `get_patreon_hidden_creators()` / `set_patreon_hidden_creators(ids)` | 已屏蔽的创作者 campaign_id 列表 |
| `get_patreon_hide_unentitled()` / `set_patreon_hide_unentitled(hide)` | 是否隐藏无权限查看的帖子（默认关闭） |
| `get_ai_base_url()` / `set_ai_base_url(url)` | AI 翻译服务 base url（OpenAI 兼容） |
| `get_ai_model()` / `set_ai_model(model)` | AI 翻译模型名称 |
| `get_proxy()` / `set_proxy(url)` | 全局网络代理地址（http/https，留空 `""` 跟随系统代理） |
| `get_gb_category_i18n_url()` / `set_gb_category_i18n_url(url)` | 分类翻译热更新 URL（可覆盖默认 GitHub 地址） |

#### 数据清理

| 方法 | 说明 |
|------|------|
| `cleanup_mod_data(valid_mod_names)` | 清理失效的 Mod 数据——移除已不存在的 Mod 对应的备注、预览图、分组引用；同步清理 `group_order` 中不存在的分组名 |

### 配置文件结构 (`mod_manager_config.json`)

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

### 被调用于

- `mod_manager.py`（启动时读取语言配置）
- `modules/gui.py`、`modules/mod_ops.py`、`modules/online_browser.py`、`modules/patreon_browser.py`、`modules/patreon.py`、`modules/gamebanana.py`、`modules/source_store.py`、`modules/archive_installer.py`、`modules/update_manager.py`、`modules/ai_translate.py`、`modules/cleanup.py`、`modules/gb_category_i18n.py`

---

## modules/mod_ops.py — Mod 操作

### 职责

本地 Mod 文件夹的扫描、验证、移动（启用/禁用）、README 检测。**不涉及任何 UI 代码**，纯业务逻辑。

### 模块级函数

| 函数 | 说明 |
|------|------|
| `find_readme_files(mod_path)` | 直接扫描一个 Mod 目录，返回检测到的 README 文件 `(文件名, 路径)` 列表（后台扫描任务使用） |
| `_open_in_os(path)` | 跨平台打开文件/文件夹：Windows `os.startfile`、macOS `open`、Linux `xdg-open` |

### 类：`ModManager`

需要传入游戏目录路径实例化。

#### 构造与属性

| 签名 | 说明 |
|------|------|
| `__init__(game_path)` | `game_path` 为游戏根目录（包含 `Mods/` 和 `Disabled_Mods/`） |

| 属性 | 类型 | 说明 |
|------|------|------|
| `game_path` | `str` | 游戏根目录 |
| `mods_dir` | `str` | `game_path/Mods` |
| `disabled_dir` | `str` | `game_path/Disabled_Mods` |

#### 方法

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `validate()` | `(bool, str, bool)` | 校验路径有效性。返回 `(是否有效, 错误信息, 是否自动创建了 Disabled_Mods)` |
| `scan_mods()` | `list[dict]` | 扫描 Mods/Disabled_Mods 目录，返回 `[{"name", "enabled", "path"}, ...]` |
| `check_readme_files(mod_name, enabled)` | `list[(fname, fpath)]` | 检查指定 Mod 目录下的 README 文件（按 `README_NAMES` 顺序） |
| `open_file(filepath)` | — | 用系统默认程序打开文件（`_open_in_os()` 跨平台分发） |
| `toggle_mod(mod_name, currently_enabled, progress_callback=None)` | — | 移动单个 Mod 文件夹（Mods ↔ Disabled_Mods）。失败抛异常。callback 签名 `(current, total, bytes_done, status)` |
| `toggle_mods_batch(mod_list, enable, progress_callback=None, file_progress_callback=None)` | `list[(name, ok, err)]` | 批量移动。跳过已处于目标状态的 Mod |
| `open_mod_folder(mod_name, enabled)` | — | 用文件管理器打开 Mod 文件夹 |
| `_move_with_progress(src, dst, progress_callback=None)` | — | **内部方法**。先尝试 `os.rename`（同盘快速移动），失败则逐文件 `shutil.copy2` + `shutil.rmtree` |

### 移动策略

1. **同盘**：`os.rename(src, dst)` 原子操作，速度最快
2. **跨盘**：`shutil.copy2()` 逐文件复制 + `shutil.rmtree()` 删除源目录，保留文件元数据

### README 文件名兼容

`check_readme_files()` / `find_readme_files()` 按 `config.py` 中 `README_NAMES` 的顺序检测文件。支持基础名称 `README.md` / `README.txt`，以及中、英、日、韩常见语言后缀（`ZH`、`CN`、`ZH_CN`、`CHS`、`TW`、`ZH_TW`、`CHT`、`EN`、`JA`、`JP`、`KO`、`KR`）。

### 被调用于

- `modules/gui.py`（`from modules.mod_ops import ModManager, find_readme_files`）

---

## modules/console_setup.py — 控制台与启动设置

### 职责

在 `import customtkinter` **之前**完成三件事：
1. 重定向 stderr 到 devnull（阻止 PyInstaller 启动时的警告输出）
2. 抑制 `pkg_resources` 弃用警告
3. 根据 `debug_mode` 文件控制终端窗口的显示/隐藏

### 公共函数

| 函数 | 参数 | 说明 |
|------|------|------|
| `redirect_stderr_to_null()` | — | 将 `sys.stderr` 重定向到 `os.devnull`，保存原始 stderr。**必须在 import 任何第三方库之前调用** |
| `suppress_pkg_resources_warning()` | — | 使用 message-based 过滤抑制 `pkg_resources` 弃用警告（兼容 PyInstaller 的 `pyimod02_importers.py` 发出的警告） |
| `restore_stderr()` | — | 恢复原始 stderr（调试模式时调用） |
| `setup_console_visibility(app_dir)` | `app_dir: str` | 检查 `app_dir/debug_mode` 文件：存在→恢复 stderr + 分配/显示控制台；不存在→保持重定向 + 隐藏/释放控制台。**非 Windows 平台仅恢复 stderr** |

### 实现细节

- **为什么 message-based 过滤**：PyInstaller 打包后 `customtkinter` 加载 `pkg_resources` 的警告从 `pyimod02_importers.py` 发出，`module=` 参数匹配不到，改用 `message=.*pkg_resources is deprecated.*` 正则匹配。
- **为什么 stderr 重定向**：即使 `--noconsole` 构建，PyInstaller 仍可能短暂显示控制台窗口，重定向可彻底阻断。

### 调用时机（重要！）

```python
redirect_stderr_to_null()          ← 必须在 import 任何第三方库之前
suppress_pkg_resources_warning()   ← 必须在 import customtkinter 之前
setup_console_visibility(_APP_DIR) ← 必须在 import customtkinter 之前
init_i18n() + set_language()       ← GUI 加载前
from modules.gui import ModManagerApp  ← 这里才 import customtkinter
```

### 被调用于

- `mod_manager.py`（唯一调用者，启动阶段专用）

---

## modules/i18n.py — 多语言

### 职责

提供多语言支持：系统语言自动检测、JSON 翻译文件加载、运行时语言切换。中文为源代码语言（不依赖翻译文件），其他语言通过 `locales/xx.json` 翻译。

### 公共函数

| 函数 | 说明 |
|------|------|
| `init_i18n()` | 初始化全局 i18n 单例，返回 `I18n` 实例 |
| `get_i18n()` | 获取全局 i18n 单例（未初始化时自动创建） |
| `t(key, zh_default)` | 快捷翻译函数，等效于 `get_i18n().t(key, zh_default)` |

### 类：`I18n`

单例模式，管理多语言状态。

| 方法/属性 | 说明 |
|------|------|
| `__init__()` | 扫描 `locales/` 目录自动发现 `.json` 翻译文件，检测系统语言并加载 |
| `set_language(lang)` | 设置语言：`"auto"` / `"zh"` / `"en"` 等。返回 `True` 表示语言实际变化 |
| `t(key, zh_default)` | 获取翻译文本。`key` 为点号分隔 JSON 路径，`zh_default` 为中文回退值；支持 `str.format(**kwargs)` 占位符 |
| `on_language_changed(callback)` | 注册语言变更回调（`callback()` 无参数） |
| `lang` (property) | 用户设置的语言代码 |
| `effective_lang` (property) | 实际生效的语言代码（自动检测模式下为系统语言或降级值） |
| `available` (property) | 所有可用的语言代码列表 |

### 系统语言检测

内部函数 `_detect_system_language()`：
1. Windows 下通过 `GetUserDefaultUILanguage` API 获取 UI 语言 ID
2. 主语言 ID `0x04` → `"zh"`；`0x09` → `"en"`；`0x11` → `"ja"`；`0x12` → `"ko"`
3. 非 Windows 或 API 调用失败时，降级到 Python `locale.getdefaultlocale()` 再做一次检测
4. 都失败则返回 `None`

### 语言降级策略

```
用户设置 "auto":
  → 系统检测到 zh → effective = "zh"（跳过 JSON，直接返回中文）
  → 系统检测到 en → 有 en.json → effective = "en"（查 JSON）
  → 系统检测失败   → effective = "en"

用户设置 "zh":
  → effective = "zh"（跳过 JSON）

用户设置 "en":
  → effective = "en"（查 en.json）
  → en.json 加载失败 → 全部降级回中文
```

### 翻译文件格式 (`locales/xx.json`)

```json
{
  "top": { "subtitle": "|  Mod Manager" },
  "dialog": { "toggle_confirm": "Are you sure you want to {action} mod \"{name}\"?" }
}
```

- 键名用点路径组织，与 `t(key, zh_default)` 的 `key` 参数对应
- JSON 中缺失的键自动降级回 `zh_default`

### 被调用于

- `mod_manager.py`、`modules/gui.py`、`modules/mod_ops.py`、`modules/online_browser.py`、`modules/patreon_browser.py`

---

## modules/catalog_view.py — 视图状态（无 Tk 依赖）

### 职责

纯 Python 的「视图状态」层：显示模式常量与校验、本地/远程条目视图模型、页面级选择状态、在线分页状态、敏感内容判定、README 0/1/N 展示规则、卡片文字两行截断工具。**不导入 customtkinter**，可直接单元测试。

### 常量

| 名称 | 说明 |
|------|------|
| `COMPACT` / `CARD` / `DETAILED` / `VIEW_MODES` | 三种显示模式 |
| `VIEW_MODE_ORDER` | 切换器显示顺序（紧凑列表 → 详情列表 → 卡片） |

### 工具函数

| 函数 | 说明 |
|------|------|
| `normalize_view_mode(mode, default)` | 校验视图模式，无效回退默认值 |
| `is_sensitive(item)` | 敏感内容判定（`has_content_ratings` 或 `visibility` 为 `warn`/`hide`） |
| `readme_presentation(readme_files)` | README 展示规则：0 个 → `(None, files)`；1 个 → 直接打开；多个 → `"README xN"` |
| `fit_card_text(text, font, max_width)` | 按自然断点换行、最多两行、溢出加省略号 |
| `remote_image_cache_key(url, size, blur)` | 在线图片缓存键（URL + 目标尺寸 + 模糊策略） |

### 数据类

- `ScrollAnchor`：滚动位置锚点 `(key, offset)`，切换视图后恢复滚动
- `LocalItemViewModel`：本地 Mod 行视图模型（`from_mod()` 从扫描字典构建）
- `RemoteItemViewModel`：在线条目视图模型（`from_remote()` 从 `RemoteMod` 构建）
- `LocalCatalogState`：本地页状态——视图模式、已勾选名称集合、滚动锚点；`prune_selection()` 清理失效勾选
- `OnlineCatalogState`：在线页状态——视图模式、查询、排序、分类、**分页状态**（`successful_page` 仅成功时递增、`request_generation` 代次失效旧响应、`item_by_id` 去重）、`details_in_flight` 详情请求去重

### 被调用于

- `modules/gui.py`、`modules/online_browser.py`、`modules/patreon_browser.py`

---

## modules/gamebanana.py — GameBanana API 客户端

### 职责

封装 GameBanana API v11：在线浏览、搜索、分类筛选、详情、安全下载与图片加载。纯逻辑模块（httpx），不依赖 GUI。

### 常量

| 名称 | 说明 |
|------|------|
| `BASE_URL` / `GAME_ID` | `https://gamebanana.com` / `21842`（Arknights: Endfield） |
| `ALLOWED_MODELS` | `("Mod", "Tool", "Sound")` 模型白名单 |
| `DOWNLOAD_HOSTS` / `MEDIA_HOST` | 下载/图片 host 白名单 |
| `MAX_REDIRECTS` / `MAX_DOWNLOAD_BYTES` / `MAX_IMAGE_BYTES` | 下载安全限制 |

### 异常

- `GameBananaError`：API/网络错误基类
- `DownloadValidationError`：下载校验失败（host、大小、MD5 等）

### 数据类

| 名称 | 说明 |
|------|------|
| `Page` | 分页结果（`items` / `page` / `record_count` / `has_next`） |
| `RemoteImage` / `RemoteAuthor` / `RemoteFile` | 图片（缩略图/原图）、作者、文件（id/名称/MD5/版本/日期/标签） |
| `RemoteCategory` | 分类：`model`、`category_id`、`name`、`item_count`、`icon_url`、`has_children` |
| `RemoteMod` | 条目：含 `model` 字段（来自 `_sModelName`），详情请求据此选择端点 |
| `RemoteDetails(RemoteMod)` | 详情：正文、文件列表、归档文件、敏感标记 |

### 类：`GameBananaClient`

| 方法 | 说明 |
|------|------|
| `browse(page, per_page, sort, query, category, model, force)` | 浏览/搜索列表；`category` 接受 `RemoteCategory` 或 `(model, category_id)`，写入 `_aFilters[Generic_Category]`；非 Mod 模型路由 `/apiv11/{model}/Index`，搜索路由 `Util/Search/Results` |
| `categories(model, game_id, force)` | 根分类：`GET /apiv11/{Model}/Categories?_idGameRow=...&_sSort=count`；跳过 obsolete |
| `subcategories(model, category_id, force)` | 子分类：`GET /apiv11/{Model}Category/{id}/SubCategories`；记录无 `_idRow`，ID 从 `_sUrl` 末段解析；list/dict 响应归一化 |
| `details(mod_id, model, force)` | 详情：`GET /apiv11/{Model}/{id}/ProfilePage`；Tool/Sound 与 Mod 结构兼容 |
| `download(remote_file, destination, cancel_event, progress_callback)` | 安全下载：仅接受 GameBanana 文件服务器，重定向受限、校验声明大小与 MD5，流式进度 |
| `fetch_image(url)` | 图片加载：仅允许 `images.gamebanana.com`，限大小 |
| `close()` | 关闭底层 httpx 客户端 |

### 注意

- 构造时接受 `proxy=None` 参数（http/https 代理地址）；模块保持纯净不读取配置，由调用方（`online_browser.py`、`gui.py` 更新检查）传入 `ConfigManager.get_proxy()`

- 分类接口单条记录时返回 dict 而非数组，内部统一归一化
- 过滤参数名是 `Generic_Category`（`Mod_Category` 会报 UNKNOWN_FILTER）

### 被调用于

- `modules/online_browser.py`、`modules/gui.py`（检查更新）

---

## modules/gb_category_i18n.py — 分类名翻译（手动热更新）

### 职责

GameBanana 分类名的独立翻译层：内置文件兜底 + 缓存 + GitHub 手动热更新，与界面 i18n 分离。

### 文件与常量

- 内置：`locales/category_translations/gb_category_names.json`（随包分发，与 GitHub 仓库路径一致）
- 缓存：`data/cache/gamebanana/gb_category_names.json`（上次成功更新的副本，优先级高于内置）
- 默认 URL：`https://raw.githubusercontent.com/gunfub/EFMI_Mod_Manager/main/locales/category_translations/gb_category_names.json`（可用 `ConfigManager.get/set_gb_category_i18n_url` 覆盖）
- 格式：`{"分类ID": {"zh": "译文", ...}}`；en 可省略
- 安全限制：host 白名单（`raw.githubusercontent.com`）、1 MiB 流式上限、JSON 结构校验、原子写缓存

### 类：`GBCategoryI18n`

| 方法 | 说明 |
|------|------|
| `load()` | 读取本地翻译（缓存 → 内置 → 空），初始化时调用，不联网 |
| `refresh(client)` | 手动拉取 GitHub 最新翻译（请求携带配置的全局代理）；失败返回错误信息不抛异常 |
| `translate(category_id, name, lang)` | 命中返回译文，否则回退英文原名 |

### 被调用于

- `modules/online_browser.py`（「更新分类翻译」按钮触发 `refresh()`；仅在按钮点击时联网）

---

## modules/ai_translate.py — AI 翻译（OpenAI 兼容）

### 职责

AI 翻译纯逻辑层（httpx 实现，可单测）：调用 OpenAI 兼容的 `chat/completions` 接口翻译文本，并管理 API key 持久化。

### 常量

- `_MAX_TEXT_CHARS = 8000`（超长文本截断）
- `_TIMEOUT = 30.0` / `_MODEL_TIMEOUT = 15.0`
- `_KEYRING_SERVICE = "EFMI_Mod_Manager.AI"`（系统钥匙串服务名）

### 异常

- `AiTranslateError`：翻译功能错误（消息已面向用户，直接显示）

### 公共函数

| 函数 | 说明 |
|------|------|
| `translate_text(base_url, api_key, model, text, target_lang)` | 翻译文本为目标语言。`POST {base}/chat/completions`，404 时自动回退 `{base}/v1/chat/completions`；错误（超时/网络/401/403/解析失败）抛 `AiTranslateError` |
| `list_models(base_url, api_key)` | 获取可用模型 id 列表：`GET {base}/models`，404 回退 `{base}/v1/models` |
| `get_ai_api_key()` / `set_ai_api_key(key)` | API key 持久化：keyring（Windows 凭据管理器）优先，不可用时回退配置文件字段；空值删除 |

### 注意

- 每次请求自动注入配置的全局代理（`ConfigManager.get_proxy()`，空则跟随系统代理）

### 被调用于

- `modules/gui.py`（AI 翻译设置对话框）
- `modules/online_browser.py`（详情页描述翻译按钮）
- `modules/patreon_browser.py`（帖子正文翻译按钮）

---

## modules/local_preview_cache.py — 本地预览图两级缓存

### 职责

本地 Mod 预览缩略图的内存 + 磁盘两级缓存：卡片/列表先渲染界面，再在后台线程加载预览图，大量 Mod 或高清图片下更流畅。

### 类：`LocalPreviewCache`

| 方法 | 说明 |
|------|------|
| `__init__(cache_dir, memory_limit=128)` | 指定磁盘缓存目录与内存 LRU 上限 |
| `load(source_path, target_size)` | 返回适配目标尺寸的 RGB 缩略图：内存命中 → 磁盘命中 → 源图 `ImageOps.fit` 生成并写盘；失败返回 `None` |
| `cache_key(source_path, target_size)` | 缓存键：SHA-256（路径 + mtime_ns + 大小 + 目标尺寸 + 处理版本 `PROCESSING_VERSION`） |
| `prune(max_age_days=30, max_entries=512, max_bytes=256MiB)` | 清理过期条目并限制数量与总大小 |

### 实现细节

- 磁盘缓存为 PNG，原子替换写入（临时文件 + `os.replace`）
- 内存缓存为线程安全的 LRU（`OrderedDict` + `Lock`），命中时 `copy()` 返回副本
- 磁盘命中时刷新 `atime`，配合 `prune()` 的最近使用策略

### 被调用于

- `modules/gui.py`、`modules/online_browser.py`、`modules/patreon_browser.py`

---

## modules/archive_installer.py — ZIP 安全安装

### 职责

安全 ZIP 检查与事务性 Mod 安装管线：本地 ZIP 与在线下载共用同一套候选识别、安全预检与安装逻辑。

### 安全限制常量

- `MAX_ENTRIES = 50_000`、`MAX_PATH_DEPTH = 32`、`MAX_COMPRESSION_RATIO = 1000`、`DISK_SAFETY_BYTES = 256MiB`（压缩炸弹防护）
- 拒绝：绝对路径、盘符/UNC、`..` 穿越、符号链接、重解析点、加密条目、不安全的 Windows 文件名（保留名、非法字符）

### 异常与数据类

| 名称 | 说明 |
|------|------|
| `ArchiveInstallError` | 安装错误（消息面向用户） |
| `InstallCancelled` | 用户取消安装 |
| `ArchiveCandidate` / `ArchiveInspection` | 压缩包内 Mod 候选与预检结果（候选、文件数、体积、SHA-256 摘要） |
| `InstallSelection` / `InstallResult` | 安装选择（目标名/启用/候选）与结果（成功/失败/跳过） |

### 公共函数

| 函数 | 说明 |
|------|------|
| `validate_mod_name(name)` | 校验并清洗 Mod 文件夹名 |
| `unique_target_name(preferred, target_roots)` | 冲突时生成唯一目标名（「保留两者」自动改名） |
| `inspect_zip(archive_path, archive_name)` | 预检压缩包：候选识别、安全校验、SHA-256 固定 |
| `install_zip(inspection, selection, ...)` | 事务安装：解压 → 暂存 → 原子替换；支持取消与进度 |
| `install_loose_file(...)` | 单文件安装（自动建独立 Mod 文件夹） |
| `cleanup_staging(max_age_seconds)` | 启动时清理过期安装暂存 |
| `cleanup_target_temporaries(target_roots)` | 清理隐藏目标临时目录（`.efmi-update-*` 等） |
| `format_bytes(size)` | 人类可读大小 |

### 被调用于

- `modules/gui.py`（本地 ZIP 安装、在线/Patreon 下载安装）
- `modules/update_manager.py`（复用预检与安全校验）

---

## modules/source_store.py — 在线来源记录

### 职责

记录在线安装 Mod 的来源元数据（中央索引 + Mod 内 `.efmi_mod_manager/source.json` 便携清单），并支持保存 GameBanana 封面为本地预览图。

### 常量

- `COVER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")`

### 公共函数

| 函数 | 说明 |
|------|------|
| `save_gamebanana_source(mod_path, details, remote_file)` | 记录 GameBanana 安装来源（provider=`gamebanana`，含 submission/file ID、MD5、URL），写中央索引 + Mod 内清单 |
| `save_patreon_source(mod_path, campaign_id, post, attachment)` | 记录 Patreon 安装来源（provider=`patreon`，含 campaign/post/file ID） |
| `get_installed_sources()` | 返回 `config["installed_sources"]` 全部记录 |
| `update_gamebanana_source(record, details, remote_file, path)` | 更新记录（更新安装后同步新 file ID/MD5） |
| `restore_source_from_manifest(mod_path, instance_id)` | 从 Mod 内清单恢复中央索引（Mod 被手动移动后重新关联） |
| `save_gamebanana_cover(fetch, cover_url, mod_path, mod_name, overwrite=False)` | 下载 GameBanana 封面原图存入 `.efmi_mod_manager/cover.<ext>` 并注册为预览图（相对路径，Mod 移动后仍可解析；已有预览不覆盖，失败静默） |

### 被调用于

- `modules/gui.py`（在线安装/更新/恢复备份、封面保存后台任务）

---

## modules/update_checker.py — 更新匹配

### 职责

保守的手动 GameBanana 更新匹配：只识别唯一对应的新文件，歧义分支绝不自动选择。

### 数据类

- `UpdateCandidate`：`kind`（`up_to_date` / `update_available` / `ambiguous` / `file_removed` / `source_unavailable` / `review`）、`installed_file_id`、`remote_file`

### 公共函数

| 函数 | 说明 |
|------|------|
| `check_file(installed, details)` | 对比安装记录与远程详情：精确 file ID/MD5 匹配 → 已是最新；同名同标签（NFKC 归一化）唯一新文件 → 有更新；多个候选 → `ambiguous`；原文件归档/移除 → `file_removed` |

### 被调用于

- `modules/gui.py`（「检查 GameBanana 模组更新」）

---

## modules/update_manager.py — 事务更新与回滚

### 职责

受管 Mod 目录的事务性替换与备份恢复：准备完整新版本 → 备份 → 原子切换 → 失败自动回滚。

### 公共函数

| 函数 | 说明 |
|------|------|
| `update_from_zip(inspection, candidate, target_path, source_record, progress_callback, cancel_event)` | 事务更新：校验 ZIP 未变（SHA-256）→ 解压到暂存 `data/staging/update-*` → 复制到目标盘临时目录 → 备份旧版本到 `data/backups/<instance_id>/` → `os.replace` 原子切换 → 失败自动恢复；仅保留最近一次备份。返回备份路径 |
| `restore_backup(source_record)` | 将最新备份安全换回目标目录（`.restore-*` 临时目录 + 原子替换），返回目标路径 |

### 被调用于

- `modules/gui.py`（检查更新确认、恢复备份）

---

## modules/cleanup.py — 缓存清理

### 职责

按类别统计与清理缓存/垃圾（多选式对话框），不影响登录态。每个可清理类别 = 若干目录（清空内容但保留目录本身）+ 可选文件后缀模式。

### 常量

- `_TEMP_SUFFIXES = (".part", ".crdownload", ".tmp")`：下载临时残留
- `_PATREON_WEBVIEW_CACHE_DIRS`：WebView2 profile 中纯缓存子目录（**不含** Network/Cookies 等登录态数据）

### 公共函数

| 函数 | 说明 |
|------|------|
| `cleanup_targets()` | 可清理类别列表：`gb_cache`（GameBanana API 缓存）、`patreon_images`（帖子图片缓存）、`local_previews`（本地缩略图）、`patreon_browser`（WebView2 缓存）、`downloads_temp`（下载临时残留） |
| `measure_target(target)` / `measure_all(targets)` | 统计占用字节数（后台线程计算） |
| `clean_target(target)` / `clean_all(targets)` | 清理并返回 `(释放字节数, 失败文件数)`；被占用的文件跳过不报错 |
| `format_size(value)` | 人类可读大小（B/KB/MB/GB/TB） |

### 被调用于

- `modules/gui.py`（「设置 → 🧹 清理缓存」对话框）

---

## modules/online_browser.py — GameBanana 在线浏览页

### 职责

customtkinter 实现的 GameBanana 在线浏览页面：三种视图、搜索、排序、动态分类级联筛选、敏感内容保护、详情弹窗、下载安装与分类翻译热更新。

### 主要功能

- **三视图**：紧凑列表 / 详情列表 / 卡片网格（尺寸规格与本地页一致：85×48 / 150×84 / 256 宽 16:9），偏好按页面持久化；窗口缩放自动重算卡片列数
- **控件布局（两行）**：第一行左对齐——搜索框、搜索、热门/最近更新排序（下拉按钮）、分类（逐级级联 `CTkOptionMenu`，深度由 API 数据驱动，`MAX_CATEGORY_DEPTH=8` 防御）、更新分类翻译、刷新；第二行右对齐——显示方式、隐藏敏感内容
- **分类筛选**：级 0 静态节（全部/Mods/工具/声音）+ 动态级联；`_category_nodes` 统一节点缓存按需懒加载，失败可重试；皮肤子级标记静态叶子避免空请求
- **敏感内容**：开启时缩略图模糊 + 详情前二次确认；关闭时直接显示（标题敏感标记始终保留）
- **详情弹窗**：封面、作者、分类、版本、正文（可 AI 翻译）、当前文件/归档文件、截图横向预览 + 点击大图（黑色背景）
- **安装**：选择具体文件 → `GameBananaClient.download()` 安全下载 → `archive_installer` 管线安装 → `source_store` 记录来源并后台保存封面为预览图
- **图片加载**：有界线程池 + 处理后缩略图内存 LRU + in-flight 去重；页面关闭取消未开始任务
- **分类翻译**：「更新分类翻译」按钮调用 `GBCategoryI18n.refresh()`（仅此时联网）
- **网络代理**：构造 `GameBananaClient` 时传入配置的全局代理（`ConfigManager.get_proxy()`），浏览/搜索/详情/下载与图片请求全部生效

### 被调用于

- `modules/gui.py`（页面切换 `_switch_page("online")` 时显示/隐藏）

---

## modules/patreon.py — Patreon 客户端

### 职责

Patreon 订阅内容访问：httpx 直连内部 API 优先（列表/详情/下载，零浏览器进程）+ WebView2（pywebview，Windows 自带 WebView2/Edge 内核）按需临时启动（登录、刷新订阅、外链下载捕获）。

### 设计要点

- 常规请求用 httpx + 导出的登录 cookie 直连 `/api/posts` 等端点，内存占用极低
- httpx 遇 403（Cloudflare 策略变化）自动用 WebView2 fetch 兜底重试
- 浏览器用完立即关闭（内存归还）；cookies 经系统钥匙串分块持久化（服务名 `EFMI_Mod_Manager.Patreon`），失败回退 `cookies.json` 文件
- **代理跟随**：httpx 请求每次读取 `ConfigManager.get_proxy()` 注入；WebView2 通过纯函数 `_webview_proxy_arg`（http/https 且无凭据且带端口 → `--proxy-server=...`，否则 `None`）在 `apply_compat_patches` 中追加到 Edge 内核的 `AdditionalBrowserArguments`，仅本进程生效

### 公共数据与函数

| 名称 | 说明 |
|------|------|
| `CookieStore` | cookie 读写：keyring 优先（分块存储，`cookies.count` 提交标记），回退文件 |
| `sanitize_filename(name, max_length)` | 清洗文件名 |
| `render_content_blocks` / `render_content_text` | 帖子正文内容块渲染（图片/文本）与纯文本提取 |
| `parse_posts_page` / `parse_collections_payload` / `parse_campaigns_payload` | Patreon API JSON 解析（帖子/合集/创作者） |
| `sort_posts(posts, sort)` | 最新 / 热门（点赞数）排序 |
| `extract_external_links(content_json)` | 提取外链（MEGA、Google Drive 等） |
| `PatreonError` / `PatreonNotLoggedIn` | 异常类 |

### 类：`PatreonSession`

| 方法 | 说明 |
|------|------|
| `start()` / `close()` | 启动/关闭浏览器（按需，超时保护） |
| `is_logged_in()` / `current_user_id()` | 登录检测（httpx 优先，403 时浏览器兜底） |
| `ensure_login(cancel_event)` | 打开可见浏览器窗口完成登录并导出 cookies |
| `list_subscribed_creators(cancel_event)` | 刷新订阅：读取账号关注的所有创作者（临时浏览器抓取 memberships 页面） |
| `creator_posts(campaign_id, cursor, sort)` | 创作者帖子分页（每页 30） |
| `post_details(post_id)` | 帖子详情（正文/附件/外链，按需加载） |
| `campaign_collections(campaign_id)` | 创作者的合集列表/帖子 |
| `download_attachment(url, suggested_name, dest_dir, cancel_event, progress_callback)` | 附件下载（httpx 优先，403 时 WebView2 兜底），进度/取消 |
| `open_external(url, cancel_event, on_message)` | 打开浏览器窗口手动下载外链，捕获下载完成事件（**打开并捕获**） |

### 被调用于

- `modules/patreon_browser.py`

---

## modules/patreon_browser.py — Patreon 订阅浏览页

### 职责

customtkinter 实现的 Patreon 订阅浏览页面：创作者列表、帖子三视图、详情对话框、附件安装与外链捕获。

### 主要功能

- **左侧**：已订阅/关注创作者列表（顶部可筛选，🔄 刷新订阅按钮临时启动浏览器抓取）；选中创作者后动态显示其 **📁 合集** 列表，🗂 全部帖子恢复完整列表
- **右侧**：帖子三视图（紧凑/详情/卡片，与 GameBanana 页一致，偏好持久化）；🕐 最新 / 🔥 热门排序（热门按点赞数，对应作者首页两个入口）；每页 30 篇 + 「加载更多」；顶部显示「显示 X / Y 篇」
- **帖子详情**：封面大图、正文全文与帖子内图片（图文混排，点击图片全屏）、附件列表与外链；均按需加载，打开过的帖子走缓存；正文可 AI 翻译
- **下载安装**：「下载并安装」→ httpx 下载附件 → `archive_installer` 标准安装流程（ZIP 可选候选，单文件自动建独立 Mod 文件夹）→ `source_store.save_patreon_source()` 记录来源；未订阅付费帖显示 🔒 需订阅标记
- **外链**：「打开并捕获」打开浏览器窗口手动下载，完成后自动捕获并询问是否安装；「复制」复制链接
- 隐藏无权限帖子开关、屏蔽创作者

### 被调用于

- `modules/gui.py`（页面切换 `_switch_page("patreon")` 时显示/隐藏；安装/外链回调）

---

## modules/dialogs.py — 自定义对话框

### 职责

替代系统原生 `tkinter.messagebox` 的深色自定义对话框（基于 `CTkToplevel`，与本地 Mod 备注/分组弹窗同款样式）；`gui.py` / `online_browser.py` / `patreon_browser.py` 的全部提示与确认弹窗均改由本模块提供，消除系统弹窗白底与深色主题不一致的问题。

### 公共函数

| 函数 | 说明 |
|------|------|
| `showinfo(title, message, parent=None)` | 信息提示（确定按钮） |
| `showwarning(title, message, parent=None)` | 警告提示 |
| `showerror(title, message, parent=None)` | 错误提示 |
| `askyesno(title, message, parent=None)` | 是/否确认，返回布尔值（Enter 是、Esc 否） |

### 实现细节

- 模态：`transient` + `grab_set` + `wait_window`，相对父窗口居中、不可缩放
- 深色标题栏：`_apply_dialog_titlebar_color()` 在 `grab_set()` **之前**同步完成 DWM 标题栏重绘（withdraw → update → DWM → deiconify，全程无延迟回调），避免库的延迟重绘在 grab 之后运行导致 Tk 事件循环卡死
- 文本自动换行（`wraplength=460`）；按钮文案走 i18n（`dialog.yes` / `dialog.no` / `dialog.ok`）

### 被调用于

- `modules/gui.py`、`modules/online_browser.py`、`modules/patreon_browser.py`

---

## modules/gui.py — GUI 主界面

### 职责

基于 `customtkinter` 的主窗口：本地/GameBanana/Patreon 三个页面、经典菜单栏、三种显示模式、响应式卡片布局、分组管理、预览图、README 菜单、批量操作、ZIP 安装、更新检查/备份恢复、缓存清理与 AI 翻译设置。

### 依赖

- `customtkinter`（第三方 GUI 框架）
- `Pillow`（可选，预览图功能；`HAS_PIL` 标志控制）
- `pypinyin`（可选，中文拼音首字母索引；`HAS_PYPINYIN` 标志控制）
- 内部模块：`config.py`、`mod_ops.py`、`i18n.py`、`catalog_view.py`、`local_preview_cache.py`、`archive_installer.py`、`source_store.py`、`update_checker.py`、`update_manager.py`、`ai_translate.py`、`cleanup.py`、`gamebanana.py`、`online_browser.py`、`patreon_browser.py`、`dialogs.py`

### 类：`ModManagerApp`

#### 类属性与常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `PREVIEW_SIZE` | `(85, 48)` | 紧凑列表预览的 16:9 逻辑尺寸 |
| `CARD_WIDTH` | `256` | 卡片固定逻辑宽度（当前 125% DPI 下约 320px） |
| `CARD_GAP` | `4` | 卡片网格的逻辑间距 |

#### 构造与运行

| 方法 | 说明 |
|------|------|
| `__init__()` | 设置 Dark 主题、创建主窗口、读取视图偏好、构建 UI，并延迟首次刷新直到布局宽度可用 |
| `run()` | 启动主事件循环 `self.root.mainloop()` |

#### UI 构建（私有方法，前缀 `_`）

| 方法 | 说明 |
|------|------|
| `_build_ui()` | 构建全部 UI：经典 Win32 风格菜单栏（设置/更多 Mod 设置左对齐 + 右侧 **ℹ️ 关于** 独立按钮，下方 1px 分割线）、标题栏（标题/三个页面按钮/路径/条件显示的选择文件夹）、本地工具栏、可滚动 Mod 区域、A-Z 侧边栏、底部状态栏、进度条 |
| `_switch_page(page)` | 在 `local` / `online` / `patreon` 三个页面间切换，隐藏/显示对应框架 |
| `_build_alphabet_bar(parent)` | 构建一级 A-Z 跳转侧边栏占位控件 |
| `_rebuild_alphabet_bar()` | 重建一级 A-Z 侧边栏按钮：按分组名首字母（支持中文拼音），点击跳转到对应分组标题。底部有未分组专用按钮 |
| `_build_group_mini_alpha_bar(content_frame, gname, mods, notes)` | 在分组内容区右侧构建该组的迷你 A-Z 二级索引栏 |
| `_scroll_to_group(letter)` / `_scroll_to_mini_letter(...)` / `_scroll_to_widget(widget)` | 滚动导航辅助 |
| `_get_sort_key(display)` / `_get_index_letter(display)` | 中英混合排序与索引辅助（中文 → 拼音首字母，无拼音归入 `'#'`） |
| `_font(base_size, weight)` / `_get_dpi_scale_factor()` | DPI 缩放字体与缩放因子（Windows API） |

#### 菜单栏与对话框

| 方法 | 说明 |
|------|------|
| `_show_settings_menu(anchor)` | 「设置」弹出菜单：语言级联子菜单（当前语言 ✓）、📁 选择文件夹、🧹 清理缓存、🌐 AI 翻译设置、🛰️ 网络代理设置 |
| `_show_mod_settings_menu(anchor)` | 「更多 Mod 设置」弹出菜单：恢复备份、检查 GameBanana 模组更新 |
| `_show_about_dialog()` | 「ℹ️ 关于」对话框（顶栏独立按钮）：`CTkScrollableFrame` 三段式布局——纪念图片+配文 / 关于本项目（简介、免责声明、版本、可点击的项目主页、GPLv3 许可证）/ 感谢开源（组件名称·版本·许可证·版权，点击跳转仓库，页脚指向本地 `licenses/` 与 `THIRD_PARTY_NOTICES.txt`）；无 PIL 或图片缺失时优雅降级 |
| `_show_cleanup_dialog()` | 缓存清理对话框：列出可清理类别与占用空间（后台统计），勾选后清理；下载进行中跳过临时残留；显示释放结果 |
| `_show_ai_settings_dialog()` | AI 翻译设置对话框：Base URL、API Key（`get/set_ai_api_key`，keyring 存储）、模型下拉 +「获取可用模型」（后台 `list_models`） |
| `_show_proxy_settings_dialog()` | 网络代理设置对话框：代理地址输入（保存时校验 http/https scheme 与 host/port，拒绝 socks5）、「测试连接」按钮（线程内请求 Google `generate_204`，结果内联显示）、保存后提示重启生效（「立即重启」/「稍后」） |
| `_test_proxy_connection(dialog, proxy_var, status_label, test_btn)` | 后台测试代理连通性，结果内联显示 |
| `_confirm_proxy_restart()` | 代理保存成功后的重启确认（延迟 150ms 弹出，等待旧对话框销毁） |
| `_restart_app()` | 重启应用：`subprocess.Popen` 重新拉起自身后 `os._exit(0)`，重启前尽力关闭 Patreon 会话 |
| `_browse_folder()` | 弹出文件夹选择对话框，设置游戏路径 |
| `_update_browse_btn_visibility()` | 顶栏「选择文件夹」按钮仅在未选路径时显示，选定后隐藏（设置菜单入口常驻） |

#### 本地页：视图与渲染

| 方法 | 说明 |
|------|------|
| `_view_mode_labels()` / `_update_view_switch_labels()` | 三视图分段按钮（☷ 紧凑列表 / ☰ 详情列表 / ▦ 卡片）的本地化标签 |
| `_on_view_mode_change(label)` | 切换本地视图模式并保存（`ConfigManager.set_view_mode("local", ...)`） |
| `_get_card_column_count(width)` | 根据可用宽度、固定卡片宽度和间距动态计算列数 |
| `_watch_card_area()` | 定时读取滚动 Canvas 宽度（150ms 轮询），仅当列数变化时触发卡片重排 |
| `_refresh_card_columns()` | 重排卡片列数，恢复 Mod 勾选与分组复选框状态 |
| `_load_config_and_refresh(defer=False)` | 加载配置；启动时可延迟刷新等待布局宽度 |
| `_refresh_when_layout_ready(attempt=0)` | 等待滚动区获得可靠宽度后执行首次刷新 |
| `_refresh()` | 校验路径 → 清理暂存 → 扫描 Mod → 清理失效数据 → 修剪勾选 → 渲染 → 更新统计 → 重建字母栏 |
| `_show_empty_state(message)` | 清空列表并显示提示文字 |
| `_render_mod_list()` | 按分组和当前视图模式渲染本地 Mod；清理旧控件后调用分组构建方法 |
| `_create_group_section(gname, mods, notes, images, is_collapsed)` | 创建分组标题和内容；紧凑/详情生成行，卡片生成动态满列宽网格并整体居中 |
| `_create_mod_row(parent, mod, note, image_path)` | 创建紧凑行（复选框/预览/名称/README/开关/更多） |
| `_create_mod_detailed_row(...)` | 创建详情行（150×84 预览 + 名称/原名 + README 摘要 + 开关 + 打开文件夹/更多） |
| `_create_mod_card(parent, mod, note, image_path, index, columns, width)` | 创建固定宽度卡片：16:9 预览、两行标题、状态与紧凑操作区 |
| `_toggle_group_collapse(gname, btn)` | 切换分组折叠/展开并持久化 |

#### 本地页：勾选、分组、备注与预览

| 方法 | 说明 |
|------|------|
| `_on_group_checkbox_toggle(gname)` | 分组复选框 → 同步该组所有 Mod |
| `_on_mod_checkbox_toggle(name)` | 单个 Mod 复选框 → 同步所属分组复选框 |
| `_select_all()` / `_deselect_all()` / `_invert_selection()` | 批量选择辅助 |
| `_sync_all_group_checkboxes()` | 同步所有分组复选框状态 |
| `_get_selected_mods()` | 返回当前勾选的 Mod 数据列表 |
| `_create_group()` / `_manage_groups()` | 创建/管理分组（重命名/删除/新建，对话框保持打开支持连续操作） |
| `_show_more_menu(mod)` | Mod「更多操作」弹出菜单（编辑备注/预览图/分组/清除） |
| `_show_readme_menu(button, readme_files)` | 多 README 时在按钮下方显示暗色文件选择菜单 |
| `_toggle_mod_group(mod, gname, add)` | 将 Mod 加入/移出指定分组 |
| `_resolve_preview_path(mod_path, stored_path)` | 解析预览图实际路径（相对路径拼 Mod 目录；绝对路径失效时尝试交换 `Mods\` / `Disabled_Mods\`） |
| `_set_preview_image(mod)` / `_clear_preview_image(mod)` | 设置/清除预览图（文件夹内存相对路径，外部存绝对路径） |
| `_show_full_image(path)` | 黑色背景大图窗口（≤屏幕 60%，点击/滚轮/Esc 关闭） |
| `_edit_note(mod)` / `_clear_note(mod)` | 编辑/清除备注（显示名称） |

#### 本地页：开关与批量操作

| 方法 | 说明 |
|------|------|
| `_on_switch_toggled(name, state)` | 开关切换 → 确认后异步线程执行移动 |
| `_toggle_mod_threaded(mod)` | 单个 Mod 切换：确认 → 禁用 UI → 进度条 → 工作线程 |
| `_batch_toggle(enable)` | 批量启用/禁用 |
| `_on_toggle_complete(...)` / `_on_batch_complete(...)` | 完成回调：恢复 UI → 报告结果 → 刷新 |
| `_update_progress(pct, status)` | 更新进度条与状态文字 |
| `_set_ui_enabled(enabled)` | 操作中禁用浏览/刷新/开关等控件 |

#### 安装 / 更新 / 备份

| 方法 | 说明 |
|------|------|
| `_install_zip_from_file()` | 本地 ZIP 安装：预检窗口（候选/文件数/体积、可编辑目标名、启用/禁用、多 Mod 勾选）→ `install_zip` 事务安装 |
| `_install_online_file(...)` | 在线下载安装：`GameBananaClient.download()` → 安装管线 → 记录来源 + 后台保存封面 |
| `_install_patreon_file(...)` | Patreon 附件下载安装（回调给 `patreon_browser`） |
| `_open_patreon_external(...)` | Patreon 外链「打开并捕获」 |
| `_check_updates()` | 检查 GameBanana 模组更新：逐条对比安装记录 → `check_file` 匹配 → 候选确认 → `update_from_zip` 事务更新（自动备份、失败回滚） |
| `_restore_managed_backup()` | 恢复备份：`restore_backup` 安全换回最近一次更新前版本 |

#### 其他

| 方法 | 说明 |
|------|------|
| `_open_mod_folder(mod)` | 在资源管理器中打开 Mod 文件夹 |
| `_update_stats()` | 更新底部状态栏统计 |
| `_apply_language()` | 语言切换后刷新全部静态 UI 文本与本地化标签并重建列表 |
| `_on_language_change(display_value)` | 语言子菜单切换：保存配置 → 更新 i18n → `_apply_language()` |

### 线程模型

- **UI 线程**：所有 `customtkinter`/`tkinter` 操作必须在主线程执行
- **工作线程**：文件移动、下载、解压、图片解码、哈希、更新检查、缓存统计与清理等全部在后台线程执行，不再阻塞 Tk
- **主线程回调**：后台结果通过 `self.root.after(0, callback)` 调度回主线程
- **尺寸监测**：`_watch_card_area()` 通过 `root.after(150, ...)` 在 UI 线程运行；仅列数变化时重建卡片
- **退出清理**：关闭程序时取消未开始的预览/README 后台任务，启动与刷新时清理过期暂存

### 被调用于

- `mod_manager.py`（`from modules.gui import ModManagerApp`）

---

## 调用流程图

```
┌──────────────────────────────────────────────────────────────┐
│ mod_manager.py (入口)                                        │
│  1. 获取 _APP_DIR                                             │
│  2. redirect_stderr_to_null()       ← console_setup.py        │
│  3. suppress_pkg_resources_warning() ← console_setup.py       │
│  4. setup_console_visibility(_APP_DIR) ← console_setup.py     │
│  5. init_i18n() + set_language()    ← i18n.py + config.py     │
│  6. import ModManagerApp            ← gui.py                  │
│  7. main() → ModManagerApp().run()                            │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ modules/gui.py (ModManagerApp)                               │
│ __init__():                                                  │
│   ├── _build_ui()        ← 菜单栏/标题栏/工具栏/三页面框架      │
│   ├── _watch_card_area() ← 监测响应式卡片列数                  │
│   └── _load_config_and_refresh(defer=True)                   │
│       └── _refresh_when_layout_ready() → _refresh()           │
│                                                              │
│ _refresh():   (本地页)                                        │
│   ├── ModManager(game_path).validate()/scan_mods()           │
│   ├── cleanup_target_temporaries()  ← archive_installer      │
│   ├── ConfigManager.cleanup_mod_data()                       │
│   ├── LocalCatalogState.prune_selection()  ← catalog_view    │
│   ├── _render_mod_list() → _create_group_section()           │
│   │                     ├→ _create_mod_row()/detail_row       │
│   │                     └→ _create_mod_card()                │
│   ├── _update_stats()                                        │
│   └── _rebuild_alphabet_bar()                                │
│                                                              │
│ 页面切换 _switch_page():                                      │
│   ├── online   → OnlineBrowserFrame (online_browser.py)      │
│   │                 ├── GameBananaClient.browse()/details()   │
│   │                 ├── GBCategoryI18n.translate()/refresh()  │
│   │                 ├── AiTranslate.translate_text()          │
│   │                 └── 安装 → gui._install_online_file()     │
│   │                       ├── GameBananaClient.download()     │
│   │                       ├── archive_installer.install_zip() │
│   │                       └── source_store.save_*_source()    │
│   └── patreon  → PatreonBrowserFrame (patreon_browser.py)    │
│                   ├── PatreonSession (httpx + WebView2)       │
│                   ├── archive_installer / source_store        │
│                   └── 外链 → gui._open_patreon_external()     │
│                                                              │
│ 用户操作:                                                    │
│   ├── 视图切换 → ConfigManager.set_view_mode(source, mode)    │
│   ├── 开关切换 → _toggle_mod_threaded() → ModManager.toggle() │
│   ├── 批量操作 → _batch_toggle() → ModManager.toggle_mods()   │
│   ├── 安装 ZIP → inspect_zip() → install_zip()                │
│   ├── 检查更新 → update_checker.check_file()                  │
│   │              → update_manager.update_from_zip()           │
│   ├── 恢复备份 → update_manager.restore_backup()              │
│   ├── 清理缓存 → cleanup.measure_all()/clean_all()            │
│   ├── AI 翻译  → ai_translate.translate_text()/list_models()  │
│   ├── 代理设置 → _show_proxy_settings_dialog()                │
│   └── 关于     → _show_about_dialog()                         │
└──────────────────────────────────────────────────────────────┘
```

### 依赖关系图

```
console_setup.py    (无内部依赖)
       ↑
mod_manager.py ─────┤
       │            │
       ↓            ↓
    gui.py ────→ config.py / mod_ops.py / i18n.py
       │
       ├──→ catalog_view.py / local_preview_cache.py
       ├──→ archive_installer.py → config.py
       ├──→ source_store.py      → config.py
       ├──→ update_checker.py    （纯逻辑）
       ├──→ update_manager.py    → archive_installer.py + config.py
       ├──→ ai_translate.py      → config.py（keyring 回退）
       ├──→ cleanup.py           → config.py
       ├──→ gamebanana.py        （httpx，纯逻辑）
       ├──→ online_browser.py    → gamebanana.py / gb_category_i18n.py
       │                          → catalog_view.py / ai_translate.py
       ├──→ patreon_browser.py   → patreon.py / catalog_view.py / ai_translate.py
       │                          → config.py / i18n.py
       └──→ dialogs.py           → i18n.py（按钮文案）
```

- **纯逻辑层（无 Tk）**：`config.py`、`mod_ops.py`、`i18n.py`、`catalog_view.py`、`gamebanana.py`、`gb_category_i18n.py`、`ai_translate.py`、`local_preview_cache.py`、`archive_installer.py`、`source_store.py`、`update_checker.py`、`update_manager.py`、`cleanup.py`、`patreon.py`
- **UI 层**：`gui.py`、`online_browser.py`、`patreon_browser.py`、`dialogs.py`
- `console_setup.py` 无内部依赖，只被 `mod_manager.py` 调用
- `mod_manager.py` 在步骤 5 初始化 `i18n.py`（接在 `console_setup.py` 之后、`gui.py` 之前）
