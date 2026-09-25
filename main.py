#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""开发者调试工具：主窗口与标签页装配入口，具体功能各自独立成模块。"""

import tkinter as tk
from tkinter import ttk
import ctypes

from port_scan import PortScanTab
from code_count import CodeCountTab
from about import AboutTab


class ToolGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("开发者调试工具")

        win_w = 1200
        win_h = 900
        self.root.geometry(f"{win_w}x{win_h}")
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        off_x = int((scr_w - win_w)/2)
        off_y = int((scr_h - win_h)/2)
        self.root.geometry(f"{win_w}x{win_h}+{off_x}+{off_y}")
        self.root.resizable(True,True)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 新增功能页：写一个 ttk.Frame 子类，在这里补一行 add 即可
        self.port = PortScanTab(self.notebook)
        self.notebook.add(self.port, text="端口进程查看")

        self.code = CodeCountTab(self.notebook)
        self.notebook.add(self.code, text="代码行数统计")

        self.about = AboutTab(self.notebook)
        self.notebook.add(self.about, text="关于")


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = ToolGUI(root)
    root.mainloop()
