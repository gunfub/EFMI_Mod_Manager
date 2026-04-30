# EFMI Mod Manager — Modules 文档

> 本文档详细描述 `modules/` 文件夹中每个 Python 模块的职责、公共接口、调用关系与实现细节。

---

## 目录

1. [整体架构](#整体架构)
2. [modules/__init__.py — 包声明](#modules__init__py--包声明)
3. [modules/config.py — 配置管理](#modulesconfigpy--配置管理)
4. [modules/mod_ops.py — Mod 操作](#modulesmod_opspy--mod-操作)
5. [modules/console_setup.py — 控制台与启动设置](#modulesconsole_setuppy--控制台与启动设置)
6. [modules/gui.py — GUI 主界面](#modulesguipy--gui-主界面)
7. [调用流程图](#调用流程图)

---

## 整体架构

```
mod_manager.py          ← 入口文件，启动初始化 + 导入 GUI
  │
  ├── modules/console_setup.py   ← 控制台/警告管理（最早导入）
  └── modules/gui.py             ← 主窗口 UI（导入 customtkinter）
        ├── modules/config.py    ← 配置读写
        └── modules/mod_ops.py   ← Mod 扫描/移动
```

**核心原则：**
- 入口文件 `mod_manager.py` 是所有 import 的调度的唯一入口。
- 其他模块之间无循环依赖：`config` ← `mod_ops` → `gui` ← everything。
- `console_setup.py` 必须在 `import customtkinter` **之前**调用。

---

## modules/__init__.py — 包声明

- **文件**：`modules/__init__.py`
- **内容**：`# EFMI Mod Manager - modules package`
- **作用**：将 `modules/` 目录标记为 Python 包，允许 `from modules.xxx import yyy` 语法。无实际逻辑。

---

## modules/config.py — 配置管理

### 职责

管理程序的持久化配置，读写 `mod_manager_config.json`（JSON 格式，与可执行文件同目录）。

### 公共常量

| 名称 | 类型 | 说明 |
|------|------|------|
| `APP_DIR` | `str` | 程序所在目录（PyInstaller 下为 exe 同目录，否则为 py 文件所在目录） |
| `CONFIG_PATH` | `str` | 配置文件的完整路径 `APP_DIR/mod_manager_config.json` |
| `README_NAMES` | `list[str]` | 支持的 README 文件名列表 |
| `README_LABELS` | `dict[str, str]` | README 文件名 → GUI 按钮标签 的映射 |

### 公共函数

| 函数 | 说明 |
|------|------|
| `get_app_dir()` | 返回程序所在目录（同 `APP_DIR`，供外部引用） |

### 类：`ConfigManager`

全静态方法类，无需实例化。所有方法直接通过 `ConfigManager.xxx()` 调用。

#### 通用读写

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `load()` | — | `dict` | 读取配置 JSON，不存在或损坏返回 `{}` |
| `save(config)` | `config: dict` | — | 将 dict 写入 JSON 文件（UTF-8, indent=2） |

#### 游戏路径

| 方法 | 说明 |
|------|------|
| `get_game_path()` | 返回配置中保存的游戏目录路径，默认 `""` |
| `set_game_path(path)` | 设置游戏目录路径并保存 |

#### Mod 备注

| 方法 | 说明 |
|------|------|
| `get_mod_notes()` | 返回 `{mod_name: note_text, ...}` |
| `set_mod_note(mod_name, note)` | 设置/清除单个 Mod 的备注（note 为空则删除） |

#### Mod 预览图

| 方法 | 说明 |
|------|------|
| `get_mod_images()` | 返回 `{mod_name: image_path, ...}` |
| `set_mod_image(mod_name, image_path)` | 设置/清除单个 Mod 的预览图路径 |

#### 分组管理

| 方法 | 说明 |
|------|------|
| `get_mod_groups()` | 返回 `{group_name: [mod_name, ...], ...}` |
| `set_mod_groups(groups)` | 整体替换分组数据并保存 |
| `get_group_order()` | 返回 `[group_name, ...]`（分组排序列表） |
| `set_group_order(order)` | 整体替换排序列表并保存 |
| `get_collapsed_groups()` | 返回 `[group_name, ...]`（已折叠的分组名列表） |
| `set_collapsed_groups(lst)` | 整体替换并保存 |

#### 数据清理

| 方法 | 说明 |
|------|------|
| `cleanup_mod_data(valid_mod_names)` | 清理失效的 Mod 数据——扫描后调用，移除已不存在的 Mod 对应的备注、预览图、分组引用。同步清理 `group_order` 中不存在的分组名 |

### 配置文件结构 (`mod_manager_config.json`)

```json
{
  "game_path": "D:/Games/MyGame",
  "mod_notes": {
    "mod_abc": "My Custom Name"
  },
  "mod_images": {
    "mod_abc": "D:/Images/preview.png"
  },
  "mod_groups": {
    "UI Mods": ["mod_a", "mod_b"],
    "Gameplay": ["mod_c"]
  },
  "group_order": ["UI Mods", "Gameplay"],
  "collapsed_groups": ["Gameplay"]
}
```

### 被调用于

- `mod_manager.py`（间接，不直接引用）
- `modules/gui.py`（`from modules.config import ConfigManager, README_LABELS`）
- `modules/mod_ops.py`（`from modules.config import README_NAMES`）

---

## modules/mod_ops.py — Mod 操作

### 职责

Mod 文件夹的扫描、验证、移动（启用/禁用）、README 检测。**不涉及任何 UI 代码**，纯业务逻辑。

### 类：`ModManager`

需要传入游戏目录路径实例化。

#### 构造函数

| 签名 | 说明 |
|------|------|
| `__init__(game_path)` | `game_path` 为游戏根目录（包含 `Mods/` 和 `Disabled_Mods/`） |

#### 实例属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `game_path` | `str` | 游戏根目录 |
| `mods_dir` | `str` | `game_path/Mods` |
| `disabled_dir` | `str` | `game_path/Disabled_Mods` |

#### 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `validate()` | — | `(bool, str, bool)` | 校验路径有效性。返回 `(是否有效, 错误信息, 是否自动创建了 Disabled_Mods)` |
| `scan_mods()` | — | `list[dict]` | 扫描 Mods/Disabled_Mods 目录，返回 `[{"name": ..., "enabled": True/False, "path": ...}, ...]` |
| `check_readme_files(mod_name, enabled)` | `mod_name: str, enabled: bool` | `list[(fname, fpath)]` | 检查指定 Mod 目录下的 README 文件，返回存在的文件名和路径列表 |
| `open_file(filepath)` | `filepath: str` | — | 用系统默认程序打开文件（`os.startfile`） |
| `toggle_mod(mod_name, currently_enabled, progress_callback=None)` | `mod_name: str, currently_enabled: bool, progress_callback: callable` | — | 移动单个 Mod 文件夹（Mods ↔ Disabled_Mods）。失败抛出异常。callback 签名 `(current, total, bytes_done, status)` |
| `toggle_mods_batch(mod_list, enable, progress_callback=None, file_progress_callback=None)` | `mod_list: list[dict], enable: bool, progress_callback: callable, file_progress_callback: callable` | `list[(name, ok, err)]` | 批量移动。跳过已处于目标状态的 Mod。返回结果列表 |
| `open_mod_folder(mod_name, enabled)` | `mod_name: str, enabled: bool` | — | 用资源管理器打开 Mod 文件夹（`os.startfile`） |
| `_move_with_progress(src, dst, progress_callback=None)` | `src: str, dst: str, callback` | — | **内部方法**。先尝试 `os.rename`（同盘快速移动），失败则逐文件 `shutil.copy2` + `shutil.rmtree`。通过 callback 报告进度 |

### 移动策略

1. **同盘**：`os.rename(src, dst)` 原子操作，速度最快
2. **跨盘**：`shutil.copy2()` 逐文件复制 + `shutil.rmtree()` 删除源目录，保留文件元数据

两种方式都通过 `progress_callback(current, total, bytes_done, status)` 上报进度。

### 被调用于

- `modules/gui.py`（`from modules.mod_ops import ModManager`）

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
| `restore_stderr()` | — | 恢复原始 stderr（调试模式时调用）。关闭 devnull 文件对象并还原 |
| `setup_console_visibility(app_dir)` | `app_dir: str` — 程序所在目录 | 检查 `app_dir/debug_mode` 文件：存在→恢复 stderr + 分配/显示控制台；不存在→保持 stderr 重定向 + 隐藏/释放控制台 |

#### 内部函数

| 函数 | 说明 |
|------|------|
| `_devnull()` | 返回单例的 devnull 文件对象（惰性初始化，可复用） |

### 实现细节

#### 为什么使用 message-based 警告过滤？

PyInstaller 打包后，`customtkinter` 加载 `pkg_resources` 时发出的警告是从 `pyimod02_importers.py`（PyInstaller 的导入钩子）发出的，`warnings` 模块的 `module=` 参数匹配不到。改用 `message=.*pkg_resources is deprecated.*` 正则匹配警告消息内容来过滤。

#### 为什么需要 stderr 重定向？

即使使用 `--noconsole` 构建，PyInstaller 在某些情况下仍可能短暂显示控制台窗口并将 stderr 内容刷到窗口上。在启动最早阶段将 stderr 重定向到 devnull 可以彻底阻断这个行为。

### 调用时机（重要！）

在 `mod_manager.py` 中的调用顺序：

```python
# 步骤 1: 获取 APP_DIR
# 步骤 2: redirect_stderr_to_null()          ← 必须在 import 任何第三方库之前
# 步骤 3: suppress_pkg_resources_warning()    ← 必须在 import customtkinter 之前
# 步骤 4: setup_console_visibility(_APP_DIR)  ← 必须在 import customtkinter 之前
# 步骤 5: from modules.gui import ModManagerApp  ← 这里才 import customtkinter
```

### 被调用于

- `mod_manager.py`（唯一调用者，启动阶段专用）

---

## modules/gui.py — GUI 主界面

### 职责

基于 `customtkinter` 的 Mod 管理器主窗口，包含完整的 UI 构建、事件处理、分组管理、预览图、批量操作等功能。

### 依赖

- `customtkinter`（第三方 GUI 框架）
- `Pillow`（可选，预览图功能；`HAS_PIL` 标志控制）
- `pypinyin`（可选，中文 Mod 拼音首字母索引；`HAS_PYPINYIN` 标志控制）
- `modules.config.ConfigManager` + `modules.config.README_LABELS`
- `modules.mod_ops.ModManager`

### 类：`ModManagerApp`

应用程序唯一的主类，管理整个 GUI 生命周期。

#### 类属性

| 属性 | 值 | 说明 |
|------|-----|------|
| `PREVIEW_SIZE` | `48` | Mod 预览缩略图的尺寸（像素） |

#### 构造与运行

| 方法 | 说明 |
|------|------|
| `__init__()` | 初始化：设置 Dark 主题、创建主窗口、绑定快捷键、构建 UI、加载配置并刷新 |
| `run()` | 启动主事件循环 `self.root.mainloop()` |

#### UI 构建（私有方法，前缀 `_`）

| 方法 | 说明 |
|------|------|
| `_build_ui()` | 构建全部 UI：顶栏（标题/路径/刷新/选择）、工具栏（选择/操作/分组）、Mod 列表可滚动区域、A-Z 侧边栏、底部状态栏、进度条 |
| `_build_alphabet_bar(parent)` | 构建一级 A-Z 跳转侧边栏占位控件（仅分组级跳转） |
| `_rebuild_alphabet_bar()` | 重建一级 A-Z 侧边栏按钮：按分组名首字母（支持中文拼音），点击跳转到对应分组标题。底部有未分组专用按钮 |
| `_build_group_mini_alpha_bar(content_frame, gname, mods, notes)` | 在分组内容区右侧构建该组的迷你 A-Z 二级索引栏，仅显示该组 Mod 实际存在的首字母 |
| `_scroll_to_mini_letter(letter, alpha_index)` | 滚动到组内迷你索引中指定字母对应的第一个 Mod |
| `_scroll_to_group(letter)` | 滚动到一级索引中指定字母对应的第一个分组标题 |
| `_scroll_to_ungrouped()` | 滚动到未分组标题 |
| `_scroll_to_widget(widget)` | 将可滚动区域滚动到指定 widget 可见 |
| `_get_sort_key(display)` (static) | 返回 `(sort_key, display_lower)` 元组用于排序；中文 → 拼音首字母，英文 → 自身首字母，无拼音则归入 `'#'` |
| `_get_index_letter(display)` (static) | 返回显示名的索引字母（大写 A-Z 或 `'#'`）；中文通过 pypinyin 获取拼音首字母 |
| `_font(base_size, weight=None)` | 根据当前 DPI 缩放返回 `CTkFont` |
| `_get_dpi_scale_factor()` | 通过 Windows API 获取 DPI 缩放因子 |

#### 数据流（私有方法）

| 方法 | 说明 |
|------|------|
| `_browse_folder()` | 弹出文件夹选择对话框，设置游戏路径 |
| `_load_config_and_refresh()` | 加载配置并刷新 Mod 列表 |
| `_refresh()` | 校验路径 → 扫描 Mod → 清理失效数据 → 渲染列表 → 更新统计 → 重建字母栏 |
| `_show_empty_state(message)` | 清空列表并显示提示文字 |
| `_render_mod_list()` | 按分组渲染 Mod 列表（调用 `_create_group_section` + `_create_mod_row`） |
| `_create_group_section(gname, mods, notes, images, is_collapsed)` | 创建分组标题栏（折叠按钮/复选框/名称/数量）和内容区 |
| `_toggle_group_collapse(gname, btn)` | 切换分组的折叠/展开状态并持久化 |
| `_create_mod_row(parent, mod, note, image_path)` | 创建单个 Mod 行（复选框/预览图/名称/README按钮/开关/状态/打开/更多） |

#### 复选框逻辑（私有方法）

| 方法 | 说明 |
|------|------|
| `_on_group_checkbox_toggle(gname)` | 分组复选框勾选/取消 → 同步修改该组所有 Mod 的复选框 |
| `_on_mod_checkbox_toggle(mod_name)` | 单个 Mod 复选框变化 → 同步更新所属分组复选框状态 |
| `_select_all()` | 全选所有 Mod |
| `_deselect_all()` | 取消全选 |
| `_invert_selection()` | 反选 |
| `_sync_all_group_checkboxes()` | 同步所有分组复选框状态 |
| `_get_selected_mods()` | 返回当前勾选的 Mod 数据列表 |

#### 分组管理（私有方法）

| 方法 | 说明 |
|------|------|
| `_create_group()` | 弹出输入框创建新分组 |
| `_manage_groups()` | 弹出管理分组对话框（重命名/删除） |
| `_show_more_menu(mod)` | 显示 Mod 的「更多操作」弹出菜单（编辑备注/预览图/分组） |
| `_toggle_mod_group(mod, gname, add)` | 将 Mod 加入/移出指定分组并刷新 |

#### 预览图（私有方法）

| 方法 | 说明 |
|------|------|
| `_set_preview_image(mod)` | 选择预览图片并保存 |
| `_clear_preview_image(mod)` | 清除 Mod 的预览图 |
| `_show_full_image(image_path)` | 点击缩略图 → 弹出独立窗口全屏查看原图（≤屏幕 60%） |
| `_edit_note(mod)` | 编辑 Mod 备注（显示名称） |
| `_clear_note(mod)` | 清除 Mod 备注 |

#### 开关与批量操作（私有方法）

| 方法 | 说明 |
|------|------|
| `_on_switch_toggled(mod_name, new_state)` | 开关切换事件 → 确认后启动异步线程执行移动 |
| `_toggle_mod_threaded(mod)` | 单个 Mod 切换：确认弹窗 → 禁用 UI → 显示进度条 → 启动工作线程 |
| `_batch_toggle(enable)` | 批量启用/禁用：收集勾选的 Mod → 确认 → 显示进度 → 启动工作线程 |
| `_on_toggle_complete(name, action, success, error_msg)` | 单个切换完成回调：隐藏进度 → 恢复 UI → 刷新 |
| `_on_batch_complete(results, action)` | 批量操作完成回调：隐藏进度 → 恢复 UI → 报告结果 → 刷新 |
| `_update_progress(pct, status)` | 更新进度条和状态文字 |
| `_set_ui_enabled(enabled)` | 启用/禁用浏览按钮、刷新按钮和所有开关控件（操作中禁止交互） |

#### 辅助方法（私有方法）

| 方法 | 说明 |
|------|------|
| `_open_mod_folder(mod)` | 在资源管理器中打开 Mod 文件夹 |
| `_update_stats()` | 更新底部状态栏的统计信息 |

### 线程模型

- **UI 线程**：所有 `customtkinter`/`tkinter` 操作必须在主线程执行
- **工作线程**：`toggle_mod()` / `toggle_mods_batch()` 在 `threading.Thread` 中异步执行
- **主线程回调**：工作线程中的 UI 更新通过 `self.root.after(0, callback)` 调度到主线程

### 被调用于

- `mod_manager.py`（`from modules.gui import ModManagerApp`）

---

## 调用流程图

```
┌──────────────────────────────────────────────────────────────┐
│ mod_manager.py (入口)                                        │
│                                                              │
│ 1. 获取 _APP_DIR                                             │
│ 2. redirect_stderr_to_null()       ← console_setup.py        │
│ 3. suppress_pkg_resources_warning() ← console_setup.py       │
│ 4. setup_console_visibility(_APP_DIR) ← console_setup.py     │
│ 5. import ModManagerApp            ← gui.py                  │
│ 6. main() → ModManagerApp().run()                            │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ modules/gui.py (ModManagerApp)                               │
│                                                              │
│ __init__():                                                  │
│   ├── _build_ui()           ← 构建全部 UI 控件               │
│   │   └── _build_alphabet_bar() ← A-Z 侧边栏                 │
│   └── _load_config_and_refresh() ← 首次加载                  │
│                                                              │
│ _refresh():                                                  │
│   ├── ConfigManager.get_game_path()    ← config.py           │
│   ├── ModManager(game_path)            ← mod_ops.py          │
│   │   ├── validate()                                         │
│   │   └── scan_mods()                                        │
│   ├── ConfigManager.cleanup_mod_data() ← config.py           │
│   ├── _render_mod_list() → _create_group_section()           │
│   │                     → _create_mod_row()                  │
│   ├── _update_stats()                                        │
│   └── _rebuild_alphabet_bar()                                │
│                                                              │
│ 用户操作:                                                    │
│   ├── 开关切换 → _on_switch_toggled()                        │
│   │   └── _toggle_mod_threaded() → ModManager.toggle_mod()   │
│   ├── 批量操作 → _batch_toggle()                             │
│   │   └── ModManager.toggle_mods_batch()                     │
│   ├── 分组管理 → ConfigManager.set_mod_groups() etc.         │
│   ├── 备注/预览 → ConfigManager.set_mod_note() etc.          │
│   └── 更多菜单 → _show_more_menu()                           │
└──────────────────────────────────────────────────────────────┘
```

### 依赖关系图

```
console_setup.py    (无内部依赖)
       ↑
mod_manager.py ─────┤
       │            │
       ↓            ↓
    gui.py ────→ config.py
       │
       ↓
   mod_ops.py ──→ config.py (仅 README_NAMES)
```

- `gui.py` 同时依赖 `config.py` 和 `mod_ops.py`
- `mod_ops.py` 仅从 `config.py` 导入 `README_NAMES` 常量
- `console_setup.py` 无内部依赖，只被 `mod_manager.py` 调用