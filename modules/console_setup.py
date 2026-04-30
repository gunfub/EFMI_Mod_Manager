# -*- coding: utf-8 -*-
"""
EFMI Mod Manager - 控制台与启动设置模块
抑制 pkg_resources 弃用警告 + 控制终端窗口显示/隐藏。
"""

import os
import sys
import warnings

_original_stderr = sys.stderr
_stderr_devnull = None


def _devnull():
    """返回一个可复用的 devnull 文件对象。"""
    global _stderr_devnull
    if _stderr_devnull is None:
        _stderr_devnull = open(os.devnull, "w", encoding="utf-8")
    return _stderr_devnull


def suppress_pkg_resources_warning():
    """
    在 import customtkinter 之前调用，抑制 pkg_resources 弃用警告。

    使用 message-based 过滤器而非 module-based，因为在 PyInstaller
    环境下警告实际是从 pyimod02_importers.py 发出的，module 名不匹配。
    """
    warnings.filterwarnings(
        "ignore",
        message=".*pkg_resources is deprecated.*",
        category=UserWarning,
    )
    # 同时捕获从 setuptools 自身发出的 DeprecationWarning
    warnings.filterwarnings(
        "ignore",
        message=".*pkg_resources.*deprecated.*",
        category=DeprecationWarning,
    )


def redirect_stderr_to_null():
    """
    将 stderr 重定向到 devnull，阻止任何警告/错误信息在启动早期
    刷到控制台窗口。调试模式下可调用 restore_stderr() 恢复。
    """
    global _original_stderr
    _original_stderr = sys.stderr
    try:
        sys.stderr = _devnull()
    except Exception:
        pass


def restore_stderr():
    """恢复原始的 stderr（调试模式下调用）。"""
    global _original_stderr
    if _original_stderr is not None:
        try:
            sys.stderr.close()
        except Exception:
            pass
        sys.stderr = _original_stderr
        _original_stderr = None


def setup_console_visibility(app_dir):
    """
    控制终端窗口显示/隐藏。

    推荐 PyInstaller 构建方式：
      - 正常版本：pyinstaller --noconsole ...
        → 启动时无任何终端窗口，stderr 被重定向到 devnull。
      - 调试版本：仍使用 --noconsole 构建，但程序所在目录放置一个
        任意内容的 'debug_mode' 文件即可自动弹出终端窗口并恢复 stderr。

    兼容情况：
      - 直接运行 .py 文件时：终端始终可见，自动恢复可能被重定向的 stderr。
      - 若使用 --console 构建：无 debug_mode 文件时会尽力隐藏控制台
        并释放，推荐使用 --noconsole 方式避免短暂闪现。
    """
    if not getattr(sys, "frozen", False):
        # 非 PyInstaller 产物，终端自然可见，恢复可能被 redirect_stderr_to_null 重定向的 stderr
        restore_stderr()
        return

    import ctypes

    debug_file = os.path.join(app_dir, "debug_mode")
    kernel32 = ctypes.windll.kernel32

    if os.path.exists(debug_file):
        # debug_mode 文件存在 → 确保控制台可见并恢复 stderr
        restore_stderr()
        console_hwnd = kernel32.GetConsoleWindow()
        if not console_hwnd:
            # --noconsole 构建：分配一个新控制台
            if kernel32.AllocConsole():
                import io
                try:
                    conout = open("CONOUT$", "w", buffering=1)
                    sys.stdout = io.TextIOWrapper(conout, line_buffering=True)
                except Exception:
                    pass
                try:
                    conerr = open("CONOUT$", "w", buffering=1)
                    sys.stderr = io.TextIOWrapper(conerr, line_buffering=True)
                except Exception:
                    pass
        # --console 构建：窗口已存在且可见，stderr 已恢复，无需额外操作
        return

    # debug_mode 文件不存在 → stderr 保持重定向状态
    console_hwnd = kernel32.GetConsoleWindow()
    if not console_hwnd:
        # --noconsole 构建：本来就没有终端，什么都不用做
        return

    # --console 构建但有控制台窗口：先隐藏再释放
    user32 = ctypes.windll.user32
    user32.ShowWindow(console_hwnd, 0)  # SW_HIDE
    kernel32.FreeConsole()
