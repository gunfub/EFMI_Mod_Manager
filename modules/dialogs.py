# -*- coding: utf-8 -*-
"""自定义对话框（替代系统原生 messagebox）。

全部基于 customtkinter 的 CTkToplevel，与本地 Mod 备注/分组弹窗同款
深色样式；依赖 gui.py 的 transient 标题栏补丁（DWM 深色标题栏 + 禁用
库的 withdraw 重绘，避免 grab_set 后 Tk 事件循环卡死）。
"""

import sys
import tkinter as tk

import customtkinter as ctk

from modules.i18n import t

_BUTTON_WIDTH = 100
_WRAP_WIDTH = 460


def _master(parent):
    if parent is not None:
        return parent
    try:
        return tk._default_root
    except Exception:
        return None


def _apply_dialog_titlebar_color(window):
    """同步完成标题栏深色重绘（withdraw → update → DWM → deiconify）。

    仅设置 DWM 属性在部分系统上不会触发标题栏重绘（视觉上仍是浅色）；
    ctk 的 _windows_set_titlebar_color() 用 withdraw+update 强制重绘，
    但 deiconify 延迟 5ms，在 grab_set() 之后运行会卡死事件循环。
    这里全程同步执行、无延迟回调，必须在 grab_set() 之前调用。"""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        state = window.state()
        window.withdraw()
        window.update()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(
            1 if ctk.get_appearance_mode().lower() == "dark" else 0)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
        if state == "iconic":
            window.iconify()
        elif state == "zoomed":
            window.state("zoomed")
        else:
            # 新建未显示过的窗口 state() 常为 "withdrawn"，统一 deiconify
            # 确保对话框正常显示
            window.deiconify()
        window.update()
    except Exception:
        try:
            window.deiconify()
        except Exception:
            pass


def _center(dialog, master):
    dialog.update_idletasks()
    dw = dialog.winfo_reqwidth()
    dh = dialog.winfo_reqheight()
    try:
        if master is not None and master.winfo_exists():
            px = master.winfo_rootx()
            py = master.winfo_rooty()
            pw = master.winfo_width()
            ph = master.winfo_height()
        else:
            px = 0
            py = 0
            pw = dialog.winfo_screenwidth()
            ph = dialog.winfo_screenheight()
    except Exception:
        px = 0
        py = 0
        pw = dialog.winfo_screenwidth()
        ph = dialog.winfo_screenheight()
    x = max(0, px + (pw - dw) // 2)
    y = max(0, py + (ph - dh) // 3)
    dialog.geometry("+{}+{}".format(x, y))


def _show_message(title, message, parent=None, buttons=("ok",), default=False):
    master = _master(parent)
    dialog = ctk.CTkToplevel(master) if master is not None else ctk.CTkToplevel()
    dialog.title(title)
    if master is not None:
        try:
            dialog.transient(master)
        except Exception:
            pass
    dialog.lift()
    try:
        dialog.attributes("-topmost", True)
    except Exception:
        pass
    dialog.resizable(False, False)

    ctk.CTkLabel(
        dialog,
        text=message,
        wraplength=_WRAP_WIDTH,
        justify="left",
        anchor="w",
        text_color=("gray20", "gray80"),
    ).pack(padx=20, pady=(20, 14))

    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(fill="x", padx=20, pady=(0, 16))

    result = [default]

    def _close(value=None):
        result[0] = value
        dialog.destroy()

    if buttons == ("yes", "no"):
        ctk.CTkButton(
            btn_frame, text=t("dialog.yes", "是"), width=_BUTTON_WIDTH,
            command=lambda: _close(True),
        ).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(
            btn_frame, text=t("dialog.no", "否"), width=_BUTTON_WIDTH,
            fg_color="transparent", border_width=1,
            command=lambda: _close(False),
        ).pack(side="right", expand=True, fill="x", padx=(5, 0))
        dialog.bind("<Escape>", lambda e: _close(False))
        dialog.bind("<Return>", lambda e: _close(True))
    else:
        ctk.CTkButton(
            btn_frame, text=t("dialog.ok", "确定"), width=_BUTTON_WIDTH,
            command=lambda: _close(None),
        ).pack(expand=True)
        dialog.bind("<Escape>", lambda e: _close(None))

    _center(dialog, master)
    dialog.grab_set()
    dialog.wait_window()
    return result[0]


def showinfo(title, message, parent=None):
    return _show_message(title, message, parent=parent)


def showwarning(title, message, parent=None):
    return _show_message(title, message, parent=parent)


def showerror(title, message, parent=None):
    return _show_message(title, message, parent=parent)


def askyesno(title, message, parent=None):
    return _show_message(
        title, message, parent=parent,
        buttons=("yes", "no"), default=False)
