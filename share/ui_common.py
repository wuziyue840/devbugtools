#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""功能页公共部件：状态栏、进度条、分片任务、表格排序筛选、导出、复制、右键菜单。

各功能页继承 ToolTab，只写自己的业务；这里的东西一律不依赖具体功能。
"""

import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
import csv


TREE_STYLE = "Tool.Treeview"

# 列宽自适应时每列内容两侧预留的留白（像素）。给大了会让 9 列的端口表
# 在 1200px 窗口下略微超出、白白多出一条横向滚动条，故取 20。
COLUMN_PADDING = 20


def open_path(path):
    """用系统默认方式打开文件或目录。

    Windows 用 os.startfile；macOS 用 `open`；其余用 `xdg-open`（现有行为，
    保留但不针对 Linux 做验证）。失败会抛 OSError，由调用方弹各自的提示。
    """
    if hasattr(os, "startfile"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def privilege_hint():
    """权限不足时的提示语：Windows 说管理员，macOS/Linux 说 root/sudo。"""
    if os.name == "nt":
        return "以管理员身份运行"
    return "以 root 权限运行（如 sudo python main.py）"


def ensure_tree_style(widget):
    """按实际字体高度设置表格行高，返回该行高。

    高 DPI 感知开启后字体被放大，而 ttk 的默认 rowheight 仍按未放大的字体算，
    结果行内文字被纵向裁掉（下划线、g/y/p 的下伸部最先消失）。这里按
    TkDefaultFont 的 linespace 重新算，并留出上下留白。
    """
    font = tkfont.nametofont("TkDefaultFont")
    row_height = font.metrics("linespace") + 8
    style = ttk.Style(widget)
    try:
        current = int(style.lookup(TREE_STYLE, "rowheight"))
    except (TypeError, ValueError):
        current = 0
    if current != row_height:
        style.configure(TREE_STYLE, rowheight=row_height)
    return row_height


class ToolTab(ttk.Frame):
    """功能页基类。自身即容器，塞进 Notebook 就能用。

    子类通常需要提供：
      - row_values(row) -> tuple     数据行渲染成表格一行的值
      - row_text(row)   -> str       可选，关键字筛选匹配的文本（默认取 row_values）
      - on_busy_changed(busy)        可选，忙闲切换时改自己的按钮状态
      - on_row_activate(row)         可选，双击一行时做什么
    数据源是 self.rows（dict 列表），表格只是它的视图；排序/筛选只重排内存，不重新取数。
    """

    def __init__(self, master, initial_status="就绪"):
        super().__init__(master)
        self.rows = []             # 数据源
        self.filter_text = ""      # 关键字筛选
        self.sort_column = None    # 当前排序列
        self.sort_reverse = False
        self.running = False       # 分片任务是否在跑
        self.tree = None           # 当前活动表格（多视图时由子类切换）
        self.menu = None           # 右键菜单

        self._item_rows = {}       # 表格行 id -> 数据行 dict
        self._scrollbars = {}      # 表格 -> (垂直滚动条, 水平滚动条)
        self._needed_widths = {}   # 表格 -> {列: 内容所需宽度}
        self._manual_widths = {}   # 表格 -> 用户是否手动拖过列宽
        self._queue = []           # 分片任务待处理项快照
        self._handler = None
        self._chunk = 80
        self._index = 0
        self._on_done = None
        self._on_tick = None
        self._on_item_error = None
        self.item_errors = 0
        self._after_id = None

        self._initial_status = initial_status

    # ==================== 状态栏 ====================
    def make_status_bar(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=3, pady=(0, 3))
        self.var_status = tk.StringVar(value=self._initial_status)
        ttk.Label(frame, textvariable=self.var_status, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self.progress = ttk.Progressbar(frame, mode="determinate", length=200)
        self.progress.pack(side=tk.RIGHT)
        return frame

    def set_status(self, text):
        self.var_status.set(text)

    def set_progress(self, value, maximum=None):
        if maximum is not None:
            self.progress.configure(maximum=max(maximum, 1))
        self.progress.configure(value=value)

    # ==================== 忙闲状态 ====================
    def set_busy(self, busy):
        self.on_busy_changed(busy)

    def on_busy_changed(self, busy):
        """子类覆写：切换自己的按钮可用状态。"""
        pass

    # ==================== 分片任务（界面不卡死、可中断） ====================
    def start_chunked(self, items, handler, chunk=80, on_done=None, on_tick=None,
                      on_item_error=None):
        """items 为数据快照；handler(item) 处理一条；每个事件循环处理 chunk 条。

        on_item_error(item, exc) 在单条处理失败时回调；返回 False 表示已有任务在跑。
        """
        if self.running:
            return False
        self._queue = list(items)
        self._handler = handler
        self._chunk = chunk
        self._on_done = on_done
        self._on_tick = on_tick
        self._on_item_error = on_item_error
        self._index = 0
        self.item_errors = 0
        self.running = True
        self.on_busy_changed(True)
        self.step_chunked()
        return True

    def step_chunked(self):
        if not self.running:
            return
        end = min(self._index + self._chunk, len(self._queue))
        for item in self._queue[self._index:end]:
            # 单条失败不能拖垮整批，更不能把 running 卡在 True 让界面假死：
            # 异常漏到 Tk 只会把堆栈打到 stderr，进度条冻住、按钮一直禁用。
            try:
                self._handler(item)
            except Exception as exc:
                self.item_errors += 1
                if self._on_item_error is not None:
                    try:
                        self._on_item_error(item, exc)
                    except Exception:
                        pass
        self._index = end
        if self._on_tick is not None:
            self._on_tick(self._index, len(self._queue))
        if self._index >= len(self._queue):
            self.running = False
            self._after_id = None
            self.on_busy_changed(False)
            if self._on_done is not None:
                self._on_done()
            return
        self._after_id = self.after(1, self.step_chunked)

    def stop_chunked(self):
        """中断分片任务，返回 False 表示本来就没在跑。"""
        if not self.running:
            return False
        self.running = False
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self.on_busy_changed(False)
        return True

    @property
    def processed(self):
        return self._index

    @property
    def total_items(self):
        return len(self._queue)

    # ==================== 表格 ====================
    def make_table(self, parent, headings, selectmode="extended"):
        """headings: ((列id, 表头, 宽度), ...)。返回 Treeview。

        第一张表会同时成为 self.tree（基类的排序/导出/复制都作用于它）；
        多视图的功能页可以在切换视图时改指 self.tree。
        滚动条按需显示：装得下就收起来，装不下才出现。
        """
        self.row_height = ensure_tree_style(self)
        columns = tuple(h[0] for h in headings)
        tree = ttk.Treeview(parent, columns=columns, show="headings",
                            selectmode=selectmode, style=TREE_STYLE)
        for col, text, width in headings:
            tree.heading(col, text=text, command=lambda c=col: self.sort_by(c))
            # stretch 全部关掉：列宽统一由 apply_column_widths 分配（内容所需宽度 +
            # 富余按比例分摊）。若留给 Tk 伸缩，它会为了不溢出而偷偷把某一列压窄，
            # 结果横向滚动条永远不出现、文字反倒被截断。
            tree.column(col, width=width, anchor="w", minwidth=40, stretch=False)

        vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        self._scrollbars[str(tree)] = (vsb, hsb)
        tree.bind("<Double-1>", self.on_row_double_click)
        tree.bind("<Control-c>", lambda event: self.copy_selected())
        # macOS 的复制习惯是 Cmd-C，两个都绑
        tree.bind("<Command-c>", lambda event: self.copy_selected())
        # 尺寸变化或拖过列宽之后重新判断滚动条要不要显示。
        # 用 after_idle 而不是当场判断：Tk 要等这一轮事件处理完才会重新布局，
        # 当场读到的 yview 还是旧的。
        tree.bind("<Configure>", lambda event, t=tree: self.on_tree_configure(t))
        tree.bind("<Button-1>", self.note_manual_width)
        tree.bind("<ButtonRelease-1>", lambda event, t=tree: self.schedule_scrollbars(t))
        if self.tree is None:
            self.tree = tree
        return tree

    def on_tree_configure(self, tree):
        """表格尺寸变了：按新宽度重新分配列宽，再判断滚动条。

        Tk 的 Treeview 在窗口变窄时会把各列压扁来强行塞进窗口，结果是文字被截断
        而不是出现横向滚动条。这里按当前宽度重算一次列宽，于是装不下时就真的溢出、
        滚动条出现，可以横向滚动查看而不是被截掉。

        必须推迟到 after_idle 才做：widget 级的 <Configure> 绑定先于 Tk 自己的
        类绑定执行，当场重算会被 Tk 随后又压回去（实测就是这样把宽度吃掉的）。
        用户手动拖过列宽之后不再干预。
        """
        def reapply(t=tree):
            if not self._manual_widths.get(str(t)):
                self.apply_column_widths(t)
            self.update_scrollbars(t)

        self.after_idle(reapply)

    def note_manual_width(self, event):
        """记住用户拖过列宽，之后就不要再自动按回去了。"""
        tree = event.widget
        try:
            if tree.identify_region(event.x, event.y) == "separator":
                self._manual_widths[str(tree)] = True
        except tk.TclError:
            pass

    def schedule_scrollbars(self, tree=None):
        """等布局跑完再判断一次滚动条是否需要显示。"""
        tree = tree if tree is not None else self.tree
        if tree is None:
            return
        self.after_idle(lambda t=tree: self.update_scrollbars(t))

    def update_scrollbars(self, tree=None):
        """内容装得下就把滚动条收起来，装不下才显示。

        横向按"所有列宽之和 vs 表格可视宽度"算，比读 xview 更直接可靠；
        纵向用 yview 判断（行数与可视行数的比例，由表格自己维护）。
        """
        tree = tree if tree is not None else self.tree
        if tree is None:
            return
        bars = self._scrollbars.get(str(tree))
        if bars is None:
            return
        vsb, hsb = bars
        try:
            y_first, y_last = tree.yview()
            width_used = sum(tree.column(c, "width") for c in tree["columns"])
            visible = tree.winfo_width()
        except tk.TclError:
            return
        self._toggle_scrollbar(hsb, width_used > visible)
        self._toggle_scrollbar(vsb, (y_last - y_first) < 0.999)

    @staticmethod
    def _toggle_scrollbar(bar, needed):
        """用 grid_info 判断是否受 grid 管理（比 ismapped 可靠，父容器未映射时也准）。"""
        try:
            managed = bool(bar.grid_info())
        except tk.TclError:
            return
        if needed and not managed:
            bar.grid()
        elif not needed and managed:
            bar.grid_remove()

    def clear_table(self):
        if self.tree is None:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._item_rows = {}

    def row_values(self, row):
        """子类必须实现：数据行 -> 表格行的值元组。"""
        raise NotImplementedError

    def row_text(self, row):
        """关键字筛选匹配的文本，默认取表格显示的值。"""
        return " ".join(str(v) for v in self.row_values(row)).lower()

    def sort_key(self, row):
        """数值列按数值排，其余按小写文本排；混合时数值在前。"""
        value = row.get(self.sort_column)
        if isinstance(value, (int, float)):
            return (0, value, "")
        return (1, 0, str(value if value is not None else "").lower())

    def visible_rows(self):
        rows = self.rows
        text = (self.filter_text or "").strip().lower()
        if text:
            rows = [r for r in rows if text in self.row_text(r)]
        if self.sort_column:
            rows = sorted(rows, key=self.sort_key, reverse=self.sort_reverse)
        return rows

    def refresh_table(self):
        if self.tree is None:
            return
        self.clear_table()
        for row in self.visible_rows():
            item = self.tree.insert("", tk.END, values=self.row_values(row))
            self._item_rows[item] = row
        # 数据换了就按新内容重新量一次列宽；你手动拖过列宽之后就不再自动干预
        if self.tree.get_children() and not self._manual_widths.get(str(self.tree)):
            self.autofit_columns()
        self.update_scrollbars()

    # ==================== 列宽自适应 ====================
    def autofit_columns(self, max_width=600, sample=300):
        """按表头与单元格内容量出每列"需要多宽"，再按当前表格宽度铺开。

        只量前 sample 行以免大表变慢；列宽之后仍可手动拖动，本方法不会被自动重复触发。
        """
        if self.tree is None:
            return
        font = tkfont.nametofont("TkDefaultFont")
        columns = self.tree["columns"]
        needed = {}
        for col in columns:
            needed[col] = font.measure(str(self.tree.heading(col, "text"))) + COLUMN_PADDING
        for index, item in enumerate(self.tree.get_children()):
            if index >= sample:
                break
            for col, value in zip(columns, self.tree.item(item, "values")):
                needed[col] = max(needed[col], font.measure(str(value)) + COLUMN_PADDING)
        self._needed_widths[str(self.tree)] = {
            col: min(max(needed[col], 40), max_width) for col in columns
        }
        self._manual_widths[str(self.tree)] = False
        self.apply_column_widths(self.tree)

    def apply_column_widths(self, tree):
        """按"内容所需宽度 + 富余空间按比例分摊"算出最终列宽并应用。

        窗口比内容宽：每列都按比例拿到一点富余，正好铺满、右侧不留空白，
        也不会出现某一列独吞空间、把别的列挤到看不见。
        窗口比内容窄：保持内容所需宽度，真的装不下就交给横向滚动条，
        而不是让 Tk 把列压扁、把文字截掉。
        """
        needed = self._needed_widths.get(str(tree))
        if not needed:
            return
        try:
            visible = tree.winfo_width()
        except tk.TclError:
            return
        total = sum(needed.values())
        if visible > total > 0:
            final = {col: needed[col] + int((visible - total) * needed[col] / total)
                     for col in needed}
        else:
            final = dict(needed)
        for col, width in final.items():
            try:
                if int(tree.column(col, "width")) != width:
                    tree.column(col, width=width)
            except tk.TclError:
                return

    def sort_by(self, column):
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.refresh_table()

    # ==================== 关键字筛选 ====================
    def apply_filter(self):
        """按 self.entry_filter 的内容筛选（功能页需提供该输入框）。"""
        self.filter_text = self.entry_filter.get().strip()
        self.refresh_table()
        shown = len(self.tree.get_children()) if self.tree is not None else 0
        if self.filter_text:
            self.set_status(f"筛选“{self.filter_text}”：显示 {shown} 条 / 共 {len(self.rows)} 条")
        else:
            self.set_status(f"显示全部 {len(self.rows)} 条")

    def clear_filter(self):
        self.entry_filter.delete(0, tk.END)
        self.filter_text = ""
        self.refresh_table()
        self.set_status(f"已清除筛选，显示全部 {len(self.rows)} 条")

    # ==================== 选中行 ====================
    def selected_rows(self):
        if self.tree is None:
            return []
        return [self._item_rows[i] for i in self.tree.selection() if i in self._item_rows]

    def selected_row(self):
        rows = self.selected_rows()
        return rows[0] if rows else None

    def copy_selected(self):
        if self.tree is None:
            return
        sel = self.tree.selection()
        if not sel:
            self.set_status("未选中任何行")
            return
        lines = ["\t".join(self.tree.item(i, "values")) for i in sel]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.set_status(f"已复制 {len(lines)} 行到剪贴板")

    def on_row_double_click(self, event):
        self.on_row_activate(self.selected_row())

    def on_row_activate(self, row):
        """子类覆写：双击一行时做什么。"""
        pass

    # ==================== 右键菜单 ====================
    def make_row_menu(self, entries):
        """entries: ((标签, 回调), None 表示分隔线, ...)"""
        self.menu = tk.Menu(self, tearoff=0)
        for entry in entries:
            if entry is None:
                self.menu.add_separator()
            else:
                self.menu.add_command(label=entry[0], command=entry[1])
        if self.tree is not None:
            # macOS Aqua 的 Tk 把右键上报为 Button-2；其余平台是 Button-3。
            # 不在非 macOS 上绑 Button-2 —— X11 的 Button-2 是中键，会变成中键弹菜单。
            if sys.platform == "darwin":
                self.tree.bind("<Button-2>", self.on_row_right_click)
            else:
                self.tree.bind("<Button-3>", self.on_row_right_click)
        return self.menu

    def on_row_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.menu.tk_popup(event.x_root, event.y_root)
        return "break"

    # ==================== 导出 ====================
    def export_csv(self, headers, default_name="export.csv"):
        if self.tree is None:
            return
        items = self.tree.get_children()
        if not items:
            messagebox.showinfo("提示", "当前表格没有可导出的数据")
            return
        save_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")]
        )
        if not save_path:
            return
        rows = [self.tree.item(i, "values") for i in items]
        try:
            with open(save_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
        except OSError as exc:
            messagebox.showerror("错误", f"写入文件失败：{exc}")
            return
        messagebox.showinfo("成功", f"已导出 {len(rows)} 条记录")
