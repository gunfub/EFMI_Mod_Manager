# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - Windows PC Mod Manager
管理 Mods / Disabled_Mods 文件夹中的 Mod，通过移动文件夹来启用/禁用。
GUI 基于 customtkinter。

入口文件 —— 负责启动前的初始化（抑制警告、控制台管理），然后启动 GUI。

启动流程（调用顺序不可改变！）:
  1. 获取 APP_DIR          —— 确定程序所在目录（PyInstaller 下为 exe 目录）
  2. redirect_stderr_to_null()     —— 重定向 stderr 到 devnull
                                     （必须在 import 任何第三方库之前！）
  3. suppress_pkg_resources_warning() —— 抑制 pkg_resources 弃用警告
                                     （必须在 import customtkinter 之前！）
  4. setup_console_visibility()   —— 根据 debug_mode 文件决定控制台显隐
                                     （必须在 import customtkinter 之前！）
  5. finally: import GUI          —— 这里才导入 customtkinter 等第三方库

调试模式:
  在可执行文件同目录放置一个名为 'debug_mode' 的文件（任意内容），
  即可弹出控制台窗口并恢复 stderr 输出，方便查看错误。

模块架构:
  详见 modules/modules.md
  - modules/console_setup.py  —— 控制台/警告管理（本文件唯一直接引用的模块）
  - modules/gui.py            —— 主窗口 UI（ModManagerApp）
  - modules/config.py         —— 配置管理（被 gui.py / mod_ops.py 引用）
  - modules/mod_ops.py        —— Mod 操作（被 gui.py 引用）
"""

import os
import sys

# ================================================================
# 步骤 1: 获取 APP_DIR
# ================================================================
# 确定程序所在目录：
#   - PyInstaller 打包后 (sys.frozen=True)：exe 所在目录
#   - 直接运行 .py 文件：mod_manager.py 所在目录
# 供 console_setup.py 和 config.py 使用
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ================================================================
# 步骤 2: 重定向 stderr 到 devnull
# ================================================================
# 【关键】必须在 import 任何第三方库之前执行！
# 原因: PyInstaller 即使在 --noconsole 模式下，某些警告（如
#       pkg_resources 弃用警告）仍可能在 customtkinter 加载时
#       输出到 stderr 并刷到短暂闪现的控制台窗口。
#       这里将 stderr 重定向到 devnull 彻底阻断此行为。
#       debug_mode 存在时，setup_console_visibility() 会恢复 stderr。
from modules.console_setup import redirect_stderr_to_null
redirect_stderr_to_null()

# ================================================================
# 步骤 3: 抑制 pkg_resources 弃用警告
# ================================================================
# 【关键】必须在 import customtkinter 之前执行！
# 原因: customtkinter 内部会触发 pkg_resources 加载，在 PyInstaller
#       环境下该警告从 pyimod02_importers.py 发出，module-based 过滤
#       无效，故使用 message-based 过滤器匹配警告内容。
# 注意: 这是防御纵深的一层——即使步骤 2 已重定向 stderr，这里仍然
#       设置警告过滤器以防止警告在 Python 内部累积。
from modules.console_setup import suppress_pkg_resources_warning
suppress_pkg_resources_warning()

# ================================================================
# 步骤 4: 控制台显示/隐藏
# ================================================================
# 【关键】必须在 import customtkinter 之前执行！
# 检查 _APP_DIR 下的 debug_mode 文件：
#   - 存在: 恢复 stderr，分配/显示控制台窗口（调试模式）
#   - 不存在: 保持 stderr 重定向，隐藏/释放控制台窗口（正常模式）
# 对非 PyInstaller（直接 .py 运行）: 恢复可能被重定向的 stderr
from modules.console_setup import setup_console_visibility
setup_console_visibility(_APP_DIR)

# ================================================================
# 步骤 5: 初始化多语言
# ================================================================
# 必须在导入 GUI 之前完成 i18n 初始化，这样 GUI 构建时就能使用正确的语言。
# 优先读取配置文件中的语言设置，若不存在则使用自动检测。
from modules.i18n import init_i18n
from modules.config import ConfigManager
_i18n = init_i18n()
_i18n.set_language(ConfigManager.get_language())

# ================================================================
# 步骤 6: 导入 GUI 并启动
# ================================================================
# 到这里所有的启动前准备工作已完成，可以安全导入 customtkinter 了。
# ModManagerApp 在 modules/gui.py 中定义，类构造时会初始化整个 GUI。
from modules.gui import ModManagerApp


def main():
    """创建 ModManagerApp 实例并启动主事件循环。"""
    app = ModManagerApp()
    app.run()


if __name__ == "__main__":
    main()
