#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""关于：版本、开发者、开源声明、赞助码与相关链接。

静态页面，**不写任何文件**。二维码素材放在同目录的 `assets/` 下，
是 512×512 的 PNG —— Tk 8.6 原生支持 PNG，所以不需要 Pillow（零新增依赖）。

改版本号 / 开发者 / 链接请改下面这几个常量。
"""

import os
import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import ttk, messagebox

APP_NAME = "开发者调试工具 / devbugtools"
APP_VERSION = "v1.1.0"
DEVELOPER = "倾听风雨 / wuziyue840"
LICENSE_NAME = "MIT"

# 赞助码：文件名 → (标签, 标签颜色)。标签沿用 StarTaskBook 的 SponsorCard 那套说法
QR_CODES = (
    ("wechat.png", "微信赞助", "#07c160"),
    ("alipay.png", "支付宝赞助", "#1677ff"),
)

# 原图 512×512；Tk 的 PhotoImage 只支持整数倍 subsample，缩到 256 正好
QR_SUBSAMPLE = 2

NOTICE_TEXT = (
    f"本软件完全免费且开源（{LICENSE_NAME} 许可证），不收取任何费用。\n"
    "严禁任何形式的倒卖、转售与付费分发；\n"
    "未经授权以此牟利，作者保留追究权利。\n"
    "若你是花钱买到的，请退款后告知作者。"
)

SPONSOR_TITLE = "请作者喝杯咖啡吧~"
SPONSOR_SUB = "如果这个小工具帮到了你，可以请我喝一杯咖啡 ♡"

# 相关链接：按钮文字 → 网址（点击用系统默认浏览器打开）
LINKS = (
    ("GitHub", "https://github.com/wuziyue840/devbugtools"),
    ("QQ 群", "https://qm.qq.com/q/w1NJKwe1zO"),
    ("博客", "https://blog.qtfyu.top"),
    ("Gitee", "https://gitee.com/qtfynb"),
)


def resource_dir():
    """素材目录。

    源码运行时是本文件所在的目录；打包成 exe 后 PyInstaller 会把
    `--add-data` 带上的文件解到 `sys._MEIPASS`，所以两种情形都能找到。

    这里用 `__file__` 只是**只读**地定位素材，跟 share/settings.py 刻意
    不用 `__file__`（那份配置是要**写**的）是两件事。
    """
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets")


class AboutTab(ttk.Frame):
    """关于标签页，自身即容器，塞进 Notebook 就能用。"""

    def __init__(self, master):
        super().__init__(master)
        self._images = {}    # 必须保引用：不存住的话 PhotoImage 会被回收，界面变空白
        self._fonts = {}
        self.build_ui()

    # ==================== 界面 ====================
    def build_ui(self):
        # 内容装在 Canvas 里，这样窗口被压矮时还能滚，而不是把二维码裁掉
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.body = ttk.Frame(self.canvas)
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda event: self.on_body_configure())
        self.canvas.bind("<Configure>", lambda event: self.on_canvas_configure())

        self.build_fonts()
        self.build_content()
        self.bind_wheel(self.body)
        self.update_scrollbar()

    def build_fonts(self):
        """按默认字体派生出几档字号（不写死字号，跟随系统 DPI 缩放）。"""
        base = tkfont.nametofont("TkDefaultFont")
        family = base.cget("family")
        size = base.cget("size")
        step = 1 if size > 0 else -1     # 负数是像素单位，加减方向相反

        def make(key, delta, weight="normal"):
            self._fonts[key] = tkfont.Font(family=family, size=size + step * delta,
                                           weight=weight)

        make("title", 8, "bold")
        make("version", 2, "bold")
        make("subtitle", 2, "bold")
        make("body", 0)
        make("small", -1)

    def build_content(self):
        pad = ttk.Frame(self.body)
        pad.pack(expand=True, fill=tk.BOTH, padx=24, pady=(26, 22))

        ttk.Label(pad, text=APP_NAME, font=self._fonts["title"],
                  anchor="center").pack(fill=tk.X)
        ttk.Label(pad, text=APP_VERSION, font=self._fonts["version"],
                  foreground="#1677ff", anchor="center").pack(fill=tk.X, pady=(6, 0))
        ttk.Label(pad, text=f"开发者：{DEVELOPER}", font=self._fonts["body"],
                  anchor="center").pack(fill=tk.X, pady=(8, 0))

        notice = ttk.LabelFrame(pad, text="使用声明", padding=(16, 10))
        notice.pack(fill=tk.X, pady=(22, 0))
        ttk.Label(notice, text=NOTICE_TEXT, font=self._fonts["body"],
                  justify=tk.CENTER, anchor="center").pack(fill=tk.X)

        ttk.Label(pad, text=SPONSOR_TITLE, font=self._fonts["subtitle"],
                  foreground="#e85d8a", anchor="center").pack(fill=tk.X, pady=(24, 4))
        ttk.Label(pad, text=SPONSOR_SUB, font=self._fonts["small"],
                  foreground="#a8798c", anchor="center").pack(fill=tk.X)

        row = ttk.Frame(pad)
        row.pack(pady=(14, 0))
        for filename, label, color in QR_CODES:
            self.build_qr(row, filename, label, color)

        self.build_links(pad)

    def build_links(self, parent):
        """相关链接按钮：点了用系统默认浏览器打开。"""
        row = ttk.Frame(parent)
        row.pack(pady=(18, 0))
        for label, url in LINKS:
            # 必须把 url/label 绑成默认参数：否则四个按钮都会用循环最后那个值，
            # 全都会打开同一个网址（tkinter 最常见的坑之一）
            ttk.Button(row, text=label, width=10,
                       command=lambda u=url, t=label: self.open_link(u, t)
                       ).pack(side=tk.LEFT, padx=6)

    def open_link(self, url, label=""):
        """调系统默认浏览器打开；万一调不起来就把网址显示出来，方便手动复制。"""
        try:
            opened = webbrowser.open(url, new=2)     # new=2：尽量开新标签页
        except Exception:
            opened = False
        if not opened:
            messagebox.showinfo(f"打开「{label}」失败", f"没能调起默认浏览器。\n\n{url}")

    def build_qr(self, parent, filename, label, color):
        """一张赞助码。二维码底下压白色，保证扫码清晰。"""
        tile = tk.Frame(parent, background="white", padx=10, pady=10,
                        highlightthickness=1, highlightbackground="#ffd9e5")
        tile.pack(side=tk.LEFT, padx=12)

        path = os.path.join(resource_dir(), filename)
        image = self.load_qr(path)
        if image is not None:
            self._images[filename] = image
            tk.Label(tile, image=image, background="white", borderwidth=0).pack()
        else:
            # 素材缺失也不能崩：给一行说明，其余内容照常显示
            tk.Label(tile, text=f"二维码缺失\n{filename}\n（应放在 assets/ 目录下）",
                     background="white", foreground="#c0392b",
                     justify=tk.CENTER, font=self._fonts["small"]).pack(padx=20, pady=30)
        tk.Label(tile, text=label, background="white", foreground=color,
                 font=self._fonts["subtitle"]).pack(pady=(6, 0))

    def load_qr(self, path):
        """加载并缩小二维码；加载不了返回 None（由调用方显示占位提示）。"""
        try:
            image = tk.PhotoImage(file=path)
        except tk.TclError:
            return None
        if QR_SUBSAMPLE > 1:
            image = image.subsample(QR_SUBSAMPLE)
        return image

    # ==================== 滚动（按需显示滚动条） ====================
    def on_body_configure(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.update_scrollbar()

    def on_canvas_configure(self):
        # 让内容宽度跟着窗口走，否则标签不会居中
        self.canvas.itemconfigure(self._body_id, width=self.canvas.winfo_width())
        self.update_scrollbar()

    def update_scrollbar(self):
        """装得下就把滚动条收起来，装不下才显示（跟表格那边同一思路）。"""
        if not hasattr(self, "scroll"):
            return
        try:
            needed = self.body.winfo_reqheight() > self.canvas.winfo_height()
            managed = bool(self.scroll.winfo_manager())
        except tk.TclError:
            return
        if needed and not managed:
            self.scroll.pack(side=tk.RIGHT, fill=tk.Y)
        elif not needed and managed:
            self.scroll.pack_forget()

    def bind_wheel(self, widget):
        """把滚轮绑到本页每个控件上。

        不改成全局 bind_all —— 那会连代码统计页的表格也跟着滚，
        而 `<MouseWheel>` 只会送给指针底下的那个控件，不会自动冒泡到 Canvas。
        """
        widget.bind("<MouseWheel>", self.on_mousewheel)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def on_mousewheel(self, event):
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return                      # 内容装得下，不需要滚
        step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")
