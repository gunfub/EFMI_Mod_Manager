# EFMI Mod Manager

[English](README_EN.md) | **中文**

基于 `customtkinter` 的 Mod 管理器，通过移动文件夹的方式来启用/禁用 Mod。主支持 Windows，兼容 Linux 与 macOS。

> **重要声明**：EFMI Mod Manager 不负责 Mod 的加载、解析或注入。Mod 的加载与运行时逻辑由 EFMI 在游戏启动阶段完成。本程序仅提供一个图形化的前端界面，用于快捷地启用或禁用 Mod —— 其底层实现仅是将 Mod 文件夹在 `Mods`（已启用）与 `Disabled_Mods`（已禁用）目录之间移动，以控制 EFMI 启动时应当加载哪些 Mod。本程序不修改任何 Mod 内容，也不参与 EFMI 的运行时行为。

## 功能特性

- **Mod 管理**：扫描 `Mods` 和 `Disabled_Mods` 文件夹，一键切换启用/禁用
- **批量操作**：支持全选、反选、批量启用、批量禁用
- **分组管理**：可创建、重命名、删除分组，支持折叠/展开分组
- **双视图模式**：支持详细列表与 16:9 预览卡片，可记住上次选择
- **响应式卡片布局**：固定卡片尺寸，窗口放大时自动增加列数，各分组保持统一对齐
- **自定义备注**：为每个 Mod 设置自定义显示名称
- **预览图片**：为每个 Mod 设置预览缩略图，点击可全屏查看原图；缺图时显示占位符
- **README 检测**：识别中/英/日/韩常见 README 文件名；卡片模式支持多文件选择菜单
- **多语言 A-Z 快速跳转**：侧边栏字母索引支持英文、中文拼音首字母（可选依赖 `pypinyin`），混合排序快速定位
- **多语言界面**：自动检测系统语言，支持中文 / English / 日本語 / 한국어 切换
- **DPI 动态缩放**：自适应 Windows 高 DPI 显示器（仅 Windows）
- **暗色主题**：基于 customtkinter 的现代化暗色 UI
- **控制台隐藏**：PyInstaller 打包后默认隐藏终端窗口（仅 Windows；在程序目录创建 `debug_mode` 文件可显示）

## 运行截图

![](./README.assets/screenshot-1.png)

![](./README.assets/screenshot-2.png)

![](./README.assets/screenshot-3.png)

## 目录结构要求

程序需要指向包含以下结构的游戏目录：

```
游戏目录/
├── Mods/                  # 已启用的 Mod（必须存在）
│   ├── ModA/
│   └── ModB/
└── Disabled_Mods/         # 已禁用的 Mod（首次运行自动创建）
    └── ModC/
```

启用/禁用 Mod 的本质是将对应文件夹在 `Mods` 和 `Disabled_Mods` 之间移动。

## 安装与运行

### 方式一：pip（传统方式）

#### 依赖

- Python 3.8+
- customtkinter
- Pillow（可选，用于预览图功能）
- pypinyin（可选，用于中文拼音首字母索引）

```bash
pip install customtkinter Pillow pypinyin
```

#### 直接运行

```bash
python mod_manager.py
```

#### 打包为 exe

```bash
pip install pyinstaller
pyinstaller --name "EFMI_Mod_Manager" mod_manager.py
```

- `--windowed` 会隐藏终端窗口
- 如需调试，在 exe 同目录创建名为 `debug_mode` 的空文件即可显示控制台

### 方式二：uv（推荐，更快更轻量）

[uv](https://github.com/astral-sh/uv) 是一个基于 Rust 的高速 Python 包管理器，可直接读取 `pyproject.toml` 配置文件。

#### 安装 uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或使用 pip
pip install uv
```

#### 安装依赖

```bash
# 根据 pyproject.toml 自动同步依赖（推荐）
uv sync

# 或手动安装
uv pip install customtkinter Pillow pypinyin
```

#### 直接运行

```bash
# 在 uv 管理的虚拟环境中运行
uv run python mod_manager.py
```

#### 打包为 exe

```bash
# 安装开发依赖（含 pyinstaller）
uv sync --group dev

# 使用 uv 环境中的 pyinstaller 打包
uv run pyinstaller --name "EFMI_Mod_Manager" mod_manager.py
```

- `--windowed` 会隐藏终端窗口
- 如需调试，在 exe 同目录创建名为 `debug_mode` 的空文件即可显示控制台

## 使用说明

### 1. 选择游戏目录

点击顶部 **📁 选择文件夹**，选择包含 `Mods` 文件夹的游戏根目录。程序会自动检测并在需要时创建 `Disabled_Mods` 文件夹。

### 2. 管理 Mod

- **切换视图**：使用工具栏右侧的 **列表 / 卡片** 按钮切换显示方式，选择会自动保存
- **启用/禁用单个 Mod**：点击 Mod 行或卡片中的开关按钮
- **批量操作**：勾选 Mod 前的复选框（或使用分组复选框全选该组），点击 **批量启用** 或 **批量禁用**
- **卡片布局**：卡片保持固定尺寸，窗口变宽时自动增加列数；每个分组整体居中，卡片从左侧依次排列

### 3. 分组管理

- **新建分组**：工具栏点击 **➕ 新建分组**
- **管理分组**：工具栏点击 **✏️ 管理分组**，可新建、重命名或删除分组，对话框保持打开支持连续操作
- **添加 Mod 到分组**：点击 Mod 行右侧的 **⋯** 按钮 → **📁 添加到分组 / 移出分组**
- **折叠分组**：点击分组标题栏左侧的箭头按钮

### 4. 更多操作

点击 Mod 行右侧的 **⋯** 按钮：

| 操作 | 说明 |
|------|------|
| 📝 编辑备注 | 设置 Mod 的显示名称（替代原文件夹名） |
| 🖼️ 设置预览图 | 选择图片作为 Mod 缩略图 |
| 📁 分组操作 | 将 Mod 加入或移出分组 |
| 🗑️ 清除备注/预览图 | 移除已设置的备注或预览图 |

README 文件会显示在 Mod 的操作区。列表模式会逐个显示；卡片模式只有一个 README 时直接打开，有多个时显示 **📄 README xN**，点击后从菜单中选择文件。支持 `.md` / `.txt` 以及 `ZH`、`CN`、`CHS`、`TW`、`EN`、`JA`、`JP`、`KO`、`KR` 等常见语言后缀。

### 5. 快速跳转

右侧 A-Z 侧边栏采用两级索引：

- **一级索引（全局）**：按分组名首字母列出 A-Z 按钮，点击跳转到对应分组标题。底部有未分组专用按钮。
- **二级迷你索引（组内）**：每个分组内容区右侧嵌入该组的迷你 A-Z 栏，只显示组内 Mod 实际存在的首字母，点击跳转到组内对应 Mod。多组迷你索引同时可见，互不干扰。

安装 `pypinyin` 后，中文名称会按拼音首字母参与混合排序和索引（例如"中文分组"出现在"Z"下），未安装则按原始字符排序。

## 配置文件

程序配置保存在 `mod_manager_config.json`（与程序同目录），包含：

- `language`：语言设置（`"auto"`, `"zh"`, `"en"`, `"ja"`, `"ko"`）
- `view_mode`：Mod 显示模式（`"list"` 或 `"card"`）
- `game_path`：游戏目录路径
- `mod_notes`：Mod 备注名称
- `mod_images`：Mod 预览图路径（Mod 文件夹内的图片存相对路径，外部图片存绝对路径）
- `mod_groups`：分组数据
- `group_order`：分组排序
- `collapsed_groups`：已折叠的分组列表

## 代码结构

项目采用模块化架构，核心代码拆分到 `modules/` 包中：

```
mod_manager.py              ← 入口文件，启动初始化
modules/
├── __init__.py             ← 包声明
├── config.py               ← 配置管理（JSON 读写、分组、备注、预览图）
├── mod_ops.py              ← Mod 操作（扫描、移动、验证、README 检测）
├── i18n.py                 ← 多语言（系统语言检测、JSON 翻译加载）
├── console_setup.py        ← 控制台/警告管理（stderr 重定向、pkg_resources 警告抑制）
└── gui.py                  ← GUI 主界面（customtkinter 窗口、事件处理、批量操作）

locales/
├── en.json                 ← 英语翻译文件
├── ja.json                 ← 日语翻译文件
└── ko.json                 ← 韩语翻译文件
```

**模块调用链：**  
`mod_manager.py` → `console_setup.py` + `i18n.py`（启动阶段）  
`mod_manager.py` → `gui.py` → `config.py` + `mod_ops.py`

详细文档见 [中文模块文档](modules/modules.md) / [English Modules Documentation](modules/modules_EN.md)。

## 技术栈

- **语言**：Python 3
- **GUI 框架**：[customtkinter](https://github.com/TomSchimansky/CustomTkinter)
- **图片处理**：Pillow (PIL)
- **打包工具**：PyInstaller

## 许可证

This project is open source and available under the [GPLv3 License](https://github.com/gunfub/EFMI_Mod_Manager/blob/main/LICENSE).
