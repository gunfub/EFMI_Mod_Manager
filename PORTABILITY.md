# PORTABILITY.md — 跨平台兼容性参考

> 本文档记录了项目中所有**平台相关代码的抽象隔离方式**，以及**已从平台专属 API 迁移到标准库/跨平台封装的位置**。
> 供后续开发者和 AI 参考，确保新增代码保持跨平台兼容，避免重新引入平台耦合。

---

## 1. 文件/文件夹打开：`os.startfile()` → `_open_in_os()`

**位置**：`modules/mod_ops.py:15-21`

`os.startfile()` 是 Windows 专属 API，在 Linux/macOS 上不存在。

**已替换为跨平台封装**：

```python
def _open_in_os(path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
```

- `open_mod_folder()` 和 `open_file()` 均调用 `_open_in_os()`
- 不引入任何额外第三方依赖（`subprocess` 为标准库）

**🔴 规则**：任何时候需要"用系统默认程序打开文件/文件夹"，一律通过 `_open_in_os()`，禁止直接调用 `os.startfile()` 或 `subprocess`。

---

## 2. 路径分隔符：硬编码 `"\\"` → `os.sep`

**位置**：`modules/gui.py:867-868`（`_resolve_preview_path`）

原代码用 `"\\Mods\\"` 和 `"\\Disabled_Mods\\"` 硬编码 Windows 反斜杠路径匹配。

**已替换为**：

```python
mods_sep = f"{os.sep}Mods{os.sep}"
disabled_sep = f"{os.sep}Disabled_Mods{os.sep}"
```

`os.sep` 在 Windows 上是 `\`，在 Linux/macOS 上是 `/`。

**🔴 规则**：禁止在任何字符串中硬编码 `\` 或 `/` 作为路径分隔符。使用 `os.sep`、`os.path.join()`、`os.path.normpath()` 或 `pathlib`。

---

## 3. Windows API (`ctypes.windll`) 隔离

项目中有三处使用 `ctypes.windll` 直接调用 Windows API，均已添加 `sys.platform` 守卫，非 Windows 平台会自动回退。

### 3.1 DPI 缩放检测

**位置**：`modules/gui.py:99-136`（`_get_dpi_scale_factor`）

- 使用 `ctypes.windll.shcore.GetDpiForMonitor` 和 `ctypes.windll.gdi32.GetDeviceCaps`
- **守卫**：`if sys.platform != "win32": return 1.0`
- 非 Windows 返回 `1.0`（无缩放），不影响正常使用

### 3.2 系统语言检测

**位置**：`modules/i18n.py:21-37`（`_detect_system_language`）

- 使用 `ctypes.windll.kernel32.GetUserDefaultUILanguage` 获取 Windows UI 语言 ID
- **守卫**：`if sys.platform == "win32":` 包裹 Windows API 调用
- **回退**：非 Windows 或 API 失败时，使用 `locale.getdefaultlocale()` 检测语言

### 3.3 控制台窗口管理

**位置**：`modules/console_setup.py:68-127`（`setup_console_visibility`）

- 使用 `kernel32.GetConsoleWindow` / `AllocConsole` / `FreeConsole` / `user32.ShowWindow`
- **守卫**：`if sys.platform != "win32": restore_stderr(); return`
- 非 Windows 仅恢复 stderr，跳过所有控制台操作

**🔴 规则**：
- 任何 `ctypes.windll` 调用必须在 `if sys.platform == "win32":` 守卫内
- 必须在守卫外提供合理的回退行为或早期返回
- 新增平台功能时，优先寻找标准库替代方案，避免引入 `ctypes` 调用

---

## 4. `locale.getdefaultlocale()` 已弃用

**位置**：`modules/i18n.py:40`

`locale.getdefaultlocale()` 自 Python 3.11 起标记为弃用（返回 `(language, encoding)` 元组）。

**现状**：仍在使用，但被 `except Exception` 捕获保护。目前不影响功能，但未来版本可能移除。

**TODO**：迁移到更可靠的方案：
- `locale.getlocale()[0]`（当前进程 locale，但默认可能返回 `None`）
- 读取环境变量：`os.environ.get('LANG', '')` 或 `os.environ.get('LC_ALL', '')`（Linux/macOS）
- 综合考虑两者：先查环境变量，失败再查 `locale.getlocale()`

---

## 5. 依赖库的平台兼容性总览

| 库 | 类型 | 平台兼容性 | 备注 |
|----|------|------------|------|
| `customtkinter` | 必须 | ✅ 跨平台 | 基于 tkinter，全平台可用 |
| `Pillow` | 可选 | ✅ 跨平台 | `modules/gui.py` 中以 `HAS_PIL` 标志保护，未安装时预览图功能降级 |
| `pypinyin` | 可选 | ✅ 跨平台 | `modules/gui.py` 中以 `HAS_PYPINYIN` 标志保护，未安装时中文排序/索引降级为原始字符 |
| `ctypes` | 标准库 | ⚠️ 部分平台 | 仅 `ctypes.windll` 为 Windows 专属，项目已做平台守卫 |
| `pyinstaller` | 开发依赖 | ⚠️ 各平台独立 | 打包为各平台原生可执行文件，`--noconsole` 和 `--windowed` 参数行为各平台一致 |

---

## 6. 新增代码检查清单

在提交新代码前，确认以下事项：

- [ ] 没有新的 `os.startfile()` 直接调用 → 使用 `_open_in_os()`
- [ ] 没有硬编码 `\` 或 `/` 路径分隔符 → 使用 `os.sep` / `pathlib`
- [ ] 没有未守卫的 `ctypes.windll` 调用 → 加 `sys.platform == "win32"` 守卫+回退
- [ ] 新的系统操作（打开文件、启动进程等）优先使用标准库（`subprocess`、`os`、`pathlib`），其次 `sys.platform` 分支，避免引入新第三方依赖
- [ ] 如果引入新第三方依赖，评估其跨平台兼容性，更新 `pyproject.toml` 和 `uv.lock`
- [ ] 如果依赖是可选的，添加 `try/except ImportError` + `HAS_XXX` 标志保护
