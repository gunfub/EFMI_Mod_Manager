# EFMI Mod Manager

基于 `customtkinter` 的 Windows PC Mod 管理器，通过移动文件夹的方式来启用/禁用 Mod。

## 功能特性

- **Mod 管理**：扫描 `Mods` 和 `Disabled_Mods` 文件夹，一键切换启用/禁用
- **批量操作**：支持全选、反选、批量启用、批量禁用
- **分组管理**：可创建、重命名、删除分组，支持折叠/展开分组
- **自定义备注**：为每个 Mod 设置自定义显示名称
- **预览图片**：为每个 Mod 设置预览缩略图，点击可全屏查看原图
- **README 检测**：自动识别 Mod 文件夹中的 `README.md` / `README.txt` 等文件，一键打开
- **A-Z 快速跳转**：侧边栏字母索引，快速定位 Mod
- **DPI 动态缩放**：自适应 Windows 高 DPI 显示器
- **暗色主题**：基于 customtkinter 的现代化暗色 UI
- **控制台隐藏**：PyInstaller 打包后默认隐藏终端窗口（在程序目录创建 `debug_mode` 文件可显示）

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

```bash
pip install customtkinter Pillow
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
uv pip install customtkinter Pillow
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

- **启用/禁用单个 Mod**：点击 Mod 行右侧的开关按钮
- **批量操作**：勾选 Mod 前的复选框（或使用分组复选框全选该组），点击 **批量启用** 或 **批量禁用**

### 3. 分组管理

- **新建分组**：工具栏点击 **➕ 新建分组**
- **管理分组**：工具栏点击 **✏️ 管理分组**，可重命名或删除分组
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

### 5. 快速跳转

右侧 A-Z 侧边栏可点击任意字母，快速滚动到以该字母开头的 Mod（按备注名或原始名排序）。

## 配置文件

程序配置保存在 `mod_manager_config.json`（与程序同目录），包含：

- `game_path`：游戏目录路径
- `mod_notes`：Mod 备注名称
- `mod_images`：Mod 预览图路径
- `mod_groups`：分组数据
- `group_order`：分组排序
- `collapsed_groups`：已折叠的分组列表

## 技术栈

- **语言**：Python 3
- **GUI 框架**：[customtkinter](https://github.com/TomSchimansky/CustomTkinter)
- **图片处理**：Pillow (PIL)
- **打包工具**：PyInstaller

## 许可证

This project is open source and available under the [GPLv3 License](https://github.com/gunfub/EFMI_Mod_Manager/blob/main/LICENSE).