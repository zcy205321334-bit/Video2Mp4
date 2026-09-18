"""
theme.py - 主题管理器（浅色 / 深色，跟随 Windows 系统）

设计原则：
- 启动时探测 Windows 注册表 AppsUseLightTheme（0=深色，1=浅色）
- 运行时通过 WMSettingChange 消息监听切换
- 提供 apply(widget) 方法递归应用配色
- 调色板集中管理，便于后续扩展
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from typing import Dict


# Windows 主题探测
def _is_windows_dark() -> bool:
    """读注册表 Personalize\\AppsUseLightTheme，0 = 深色，1 = 浅色。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        return False


# ────────────── 调色板 ──────────────

# 浅色：灰底白卡，蓝色主按钮
LIGHT = {
    "bg":           "#f3f3f3",   # 主背景（Windows 标准浅灰）
    "card":         "#ffffff",   # 卡片背景
    "card_alt":     "#fafafa",   # 隔行
    "border":       "#e0e0e0",
    "fg":           "#202020",
    "fg_muted":     "#6b6b6b",
    "accent":       "#0078d4",   # Windows 蓝
    "accent_fg":    "#ffffff",
    "accent_hover": "#106ebe",
    "success":      "#107c10",
    "warning":      "#ca5010",
    "error":        "#d13438",
    "log_bg":       "#ffffff",
    "log_fg":       "#202020",
    "drop_target":  "#e6f2fb",
}

# 深色：炭灰底
DARK = {
    "bg":           "#202020",
    "card":         "#2b2b2b",
    "card_alt":     "#333333",
    "border":       "#3f3f3f",
    "fg":           "#f0f0f0",
    "fg_muted":     "#a8a8a8",
    "accent":       "#4cc2ff",
    "accent_fg":    "#000000",
    "accent_hover": "#60cdff",
    "success":      "#6ccb5f",
    "warning":      "#fce100",
    "error":        "#ff99a4",
    "log_bg":       "#1e1e1e",
    "log_fg":       "#d4d4d4",
    "drop_target":  "#2a3f55",
}


def palette(dark: bool) -> Dict[str, str]:
    return DARK if dark else LIGHT


# ────────────── 主题管理器 ──────────────

class ThemeManager:
    """监听 Windows 主题变化 + 应用调色板到 widget 树。"""

    def __init__(self, app: tk.Tk):
        self.app = app
        self.dark = _is_windows_dark()
        self.pal = palette(self.dark)
        self._observers: list = []

        # Windows 主题切换消息（0x001A = WM_SETTINGCHANGE）
        if sys.platform == "win32":
            try:
                # 用 tk 的 bind 收不到 WM_SETTINGCHANGE，需要直接接 Win32 消息
                # 这里用 WM 钩子：在 ttk.Style 上 hook 一个假属性触发重读
                app.tk.call("tk", "useinputmethods", "1")
                # 简化方案：每隔几秒轮询一次主题变化（开销极小）
                self._start_polling()
            except Exception:
                pass

    def _start_polling(self):
        """每 2 秒检查一次系统主题变化。"""
        def poll():
            try:
                now_dark = _is_windows_dark()
                if now_dark != self.dark:
                    self.dark = now_dark
                    self.pal = palette(self.dark)
                    for fn in list(self._observers):
                        try:
                            fn(self.pal, self.dark)
                        except Exception:
                            pass
            except Exception:
                pass
            self.app.after(2000, poll)
        self.app.after(2000, poll)

    def on_change(self, fn):
        """注册主题变化回调。fn(palette_dict, is_dark)"""
        self._observers.append(fn)

    def apply_to_ttk_style(self, style: ttk.Style):
        """把调色板写进 ttk.Style。"""
        p = self.pal
        # ttk 标准 widget
        style.configure(".",
                        background=p["bg"],
                        foreground=p["fg"],
                        fieldbackground=p["card"],
                        bordercolor=p["border"])
        style.configure("TFrame", background=p["bg"])
        style.configure("Card.TFrame", background=p["card"], relief="flat", borderwidth=0)
        style.configure("TLabel", background=p["bg"], foreground=p["fg"])
        style.configure("Card.TLabel", background=p["card"], foreground=p["fg"])
        style.configure("Muted.TLabel", background=p["bg"], foreground=p["fg_muted"])
        style.configure("Title.TLabel", background=p["bg"], foreground=p["fg"],
                        font=("", 14, "bold"))
        style.configure("Subtitle.TLabel", background=p["bg"], foreground=p["fg_muted"],
                        font=("", 9))
        style.configure("Card.Title.TLabel", background=p["card"], foreground=p["fg"],
                        font=("", 11, "bold"))
        style.configure("Card.Muted.TLabel", background=p["card"], foreground=p["fg_muted"],
                        font=("", 9))

        # 按钮
        style.configure("TButton", background=p["card"], foreground=p["fg"],
                        bordercolor=p["border"], padding=(14, 6))
        style.map("TButton",
                  background=[("active", p["card_alt"]), ("disabled", p["bg"])],
                  foreground=[("active", p["fg"]), ("disabled", p["fg_muted"])])
        # 主操作按钮（蓝色）
        style.configure("Accent.TButton", background=p["accent"],
                        foreground=p["accent_fg"], padding=(20, 8), font=("", 10, "bold"),
                        bordercolor=p["accent"])
        style.map("Accent.TButton",
                  background=[("active", p["accent_hover"]), ("disabled", p["border"]),
                             ("!disabled", p["accent"])],
                  foreground=[("active", p["accent_fg"]), ("disabled", p["fg_muted"]),
                             ("!disabled", p["accent_fg"])])
        # 危险（红色）
        style.configure("Danger.TButton", background=p["card"],
                        foreground=p["error"], padding=(14, 6),
                        bordercolor=p["error"])
        style.map("Danger.TButton",
                  background=[("active", p["card_alt"])],
                  foreground=[("active", p["error"]), ("!disabled", p["error"])])

        # 输入框
        style.configure("TEntry", fieldbackground=p["card"],
                        foreground=p["fg"], bordercolor=p["border"],
                        insertcolor=p["fg"], padding=4)
        style.configure("TCombobox", fieldbackground=p["card"],
                        foreground=p["fg"], bordercolor=p["border"],
                        padding=4)
        style.map("TCombobox",
                  fieldbackground=[("readonly", p["card"])])
        # listbox / treeview 走 tk，不是 ttk；用 option_add 全局设
        # spinbox 也是 tk，单独配

        # 进度条
        style.configure("TProgressbar", background=p["accent"],
                        troughcolor=p["card"], bordercolor=p["border"],
                        lightcolor=p["accent"], darkcolor=p["accent"])

        # LabelFrame
        style.configure("TLabelFrame", background=p["bg"], foreground=p["fg"],
                        bordercolor=p["border"])
        style.configure("TLabelFrame.Label", background=p["bg"], foreground=p["fg"],
                        font=("", 10, "bold"))

        # Notebook
        style.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
        style.configure("TNotebook.Tab", background=p["card"],
                        foreground=p["fg"], padding=(12, 6))
        style.map("TNotebook.Tab",
                  background=[("selected", p["accent"])],
                  foreground=[("selected", p["accent_fg"])])

        # Treeview（文件列表）
        style.configure("Treeview", background=p["card"], foreground=p["fg"],
                        fieldbackground=p["card"], bordercolor=p["border"],
                        rowheight=26)
        style.map("Treeview",
                  background=[("selected", p["accent"])],
                  foreground=[("selected", p["accent_fg"])])
        style.configure("Treeview.Heading", background=p["card_alt"],
                        foreground=p["fg"], padding=4, relief="flat")

    def apply_to_root(self, root: tk.Tk):
        """配置 tk 级别（option_add）和 root 自身。"""
        p = self.pal
        root.configure(bg=p["bg"])
        # Listbox / Text / Spinbox 等 tk widget
        root.option_add("*Background", p["card"])
        root.option_add("*Foreground", p["fg"])
        root.option_add("*selectBackground", p["accent"])
        root.option_add("*selectForeground", p["accent_fg"])
        root.option_add("*Font", ("Microsoft YaHei UI", 9))
        root.option_add("*TCombobox*Listbox*Background", p["card"])
        root.option_add("*TCombobox*Listbox*Foreground", p["fg"])
        root.option_add("*TCombobox*Listbox*selectBackground", p["accent"])
        root.option_add("*TCombobox*Listbox*selectForeground", p["accent_fg"])
