#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""功能页：代码成分表 + 屎山指数。

与「代码行数统计」页**完全独立**（各自一套控件，互不读写彼此的配置），但共用
share 下的枚举、注释口径与 UI 基类，所以两页的数字可以逐语言交叉校验。

页面自下而上三块：
  1. 控制栏：扫描目标 / 引擎 / 排除目录 / 筛选 / 导出；
  2. Canvas 成分表卡：语言成分 + 行成分 + 屎山指数 + 七维小条（纯手绘，零图表库）；
  3. 表格：按语言 / 按文件 / 维度明细，三种视图共用排序、筛选与导出。

本页**默认不写盘**：只有「导出CSV」「导出分享卡片」会写你亲自选定的那个文件。
"""

import html
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import ttk, filedialog, messagebox

from about import APP_NAME, APP_VERSION
from share import health_engine, health_rules, ignore_rules, loc_engine
from share.ui_common import ToolTab, open_path

VIEW_LANG = "lang"
VIEW_FILE = "file"
VIEW_DIM = "dim"

LANG_HEADINGS = (
    ("language", "语言", 170),
    ("files", "文件数", 70),
    ("total", "总行数", 80),
    ("blank", "空行", 70),
    ("comment", "注释行", 80),
    ("code", "代码行", 80),
    ("share", "代码占比", 90),
)

FILE_HEADINGS = (
    ("rel", "文件路径", 380),
    ("language", "语言", 110),
    ("total", "总行数", 80),
    ("code", "代码行", 80),
    ("branch", "分支数", 70),
    ("indent", "最大缩进", 80),
    ("dup", "重复行", 70),
    ("todo", "TODO", 60),
    ("score", "文件分", 70),
)

DIM_HEADINGS = (
    ("name", "维度", 120),
    ("raw_text", "原始值", 100),
    ("unit", "单位", 130),
    ("normalized", "子分", 70),
    ("weight", "权重", 60),
    ("weighted", "加权", 70),
    ("note", "点评", 560),
)

# 卡片尺寸
CARD_HEIGHT = 342
CARD_MARGIN = 20


class CodeProfileTab(ToolTab):
    """代码成分表标签页：自身即容器，塞进 Notebook 就能用。"""

    def __init__(self, master):
        super().__init__(master, initial_status="就绪：加好扫描目标后点「开始分析」")
        self._fonts = {}
        self.optional = health_engine.detect_optional()
        self.engine_ids = ["builtin", "builtin_precise", "scc", "tokei",
                           "fuck_u_code", "swt"]
        self.engine_key = "builtin"
        self.file_rows = []
        self.lang_rows = []
        self.dim_rows = []
        self.rows = self.lang_rows
        self.view_mode = VIEW_LANG
        self.enum_result = None
        self.extra = {}
        self.precise_rows = []
        self.precise_note = ""
        self.index = None
        self.unknown = {"top": [], "kinds": 0, "files": 0}
        self.failed = []
        self.analyze_started = time.perf_counter()
        self.scanned_at = ""
        self.build_fonts()
        self.build_ui()
        self.switch_view(self.view_mode, refresh=False)
        # 先画一次空态：本页可能不是 Notebook 里第一个被显示的标签，
        # 未映射前拿不到 <Configure>，不先画就是一块空白面板。
        self.draw_card()

    # ==================== 字体与控件 ====================
    def build_fonts(self):
        """字体阶梯：全部基于 TkDefaultFont，跟着系统 DPI 一起缩放。"""
        base = tkfont.nametofont("TkDefaultFont")
        family = base.cget("family")
        size = base.cget("size")
        step = 1 if size > 0 else -1

        def make(key, delta, weight="normal"):
            self._fonts[key] = tkfont.Font(family=family, size=size + step * delta,
                                           weight=weight)

        make("title", 6, "bold")
        make("score", 20, "bold")
        make("section", 1, "bold")
        make("body", 0)
        make("small", -1)
        make("tiny", -2)

    def build_ui(self):
        self.build_control_bar()
        self.build_option_bar()
        self.build_workspace()
        self.build_summary()
        self.make_status_bar(self)

    def build_control_bar(self):
        box = ttk.Frame(self)
        box.pack(fill=tk.X, padx=6, pady=(6, 3))

        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="扫描目标:").pack(side=tk.LEFT)
        ttk.Button(row1, text="添加目录", width=9,
                   command=self.pick_dir).pack(side=tk.LEFT, padx=(6, 3))
        ttk.Button(row1, text="添加文件", width=9,
                   command=self.pick_files).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="填入本工具目录", width=15,
                   command=self.fill_default).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="删除选中", width=9,
                   command=self.del_targets).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="清空", width=7,
                   command=self.clear_targets).pack(side=tk.LEFT, padx=3)

        ttk.Label(row1, text="引擎:").pack(side=tk.LEFT, padx=(16, 0))
        labels = [self.engine_label(e) for e in self.engine_ids]
        self.var_engine = tk.StringVar()
        self.combo_engine = ttk.Combobox(row1, textvariable=self.var_engine,
                                         values=labels, state="readonly", width=26)
        self.combo_engine.current(0)
        self.combo_engine.pack(side=tk.LEFT, padx=(4, 12))

        self.btn_run = ttk.Button(row1, text="开始分析", width=10, command=self.start_analyze)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 3))
        self.btn_stop = ttk.Button(row1, text="停止", width=7, command=self.stop_analyze,
                                   state="disabled")
        self.btn_stop.pack(side=tk.LEFT)
        # 只有真出现读不了的文件才显示，平时不占位置
        self.btn_retry = ttk.Button(row1, text="重试失败项", width=13, command=self.retry_failed)

        body = ttk.Frame(box)
        body.pack(fill=tk.X, pady=(4, 0))
        self.list_targets = tk.Listbox(body, height=3, selectmode="extended")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.list_targets.yview)
        self.list_targets.configure(yscrollcommand=sb.set)
        self.list_targets.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    def build_option_bar(self):
        box = ttk.Frame(self)
        box.pack(fill=tk.X, padx=6, pady=(0, 4))

        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="排除目录:").pack(side=tk.LEFT)
        ttk.Button(row1, text="添加目录", width=9,
                   command=self.add_exclude).pack(side=tk.LEFT, padx=(6, 3))
        ttk.Button(row1, text="填入 git 忽略项", width=15,
                   command=self.fill_git_ignored).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="删除选中", width=9,
                   command=self.del_exclude).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="清空", width=7,
                   command=self.clear_excludes).pack(side=tk.LEFT, padx=3)
        ttk.Label(row1, text="（黑名单遍历时生效；git 模式只按这里的条目排除）"
                  ).pack(side=tk.LEFT, padx=(6, 0))

        self.list_excludes = tk.Listbox(box, height=2, selectmode="extended")
        self.list_excludes.pack(fill=tk.X, pady=(3, 0))

        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(row2, text="视图:").pack(side=tk.LEFT)
        self.var_view = tk.StringVar(value=self.view_mode)
        ttk.Radiobutton(row2, text="按语言", value=VIEW_LANG, variable=self.var_view,
                        command=lambda: self.switch_view(VIEW_LANG)).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(row2, text="按文件", value=VIEW_FILE, variable=self.var_view,
                        command=lambda: self.switch_view(VIEW_FILE)).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(row2, text="维度明细", value=VIEW_DIM, variable=self.var_view,
                        command=lambda: self.switch_view(VIEW_DIM)).pack(side=tk.LEFT, padx=2)

        ttk.Label(row2, text="关键字:").pack(side=tk.LEFT, padx=(16, 0))
        self.entry_filter = ttk.Entry(row2, width=18)
        self.entry_filter.pack(side=tk.LEFT, padx=3)
        self.entry_filter.bind("<Return>", lambda event: self.apply_filter())
        ttk.Button(row2, text="清除筛选", width=9,
                   command=self.clear_filter).pack(side=tk.LEFT, padx=(6, 3))

        self.var_snark = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="毒舌模式", variable=self.var_snark,
                        command=self.on_snark_changed).pack(side=tk.LEFT, padx=(12, 3))
        ttk.Button(row2, text="复制选中", width=9,
                   command=self.copy_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="复制Markdown", width=13,
                   command=self.copy_markdown).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="导出CSV", width=9,
                   command=self.export_result).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="导出分享卡片", width=13,
                   command=self.export_card).pack(side=tk.LEFT, padx=3)

    def build_workspace(self):
        """卡片与表格放进可拖动容器：卡片想大就往上拖分隔条，反之亦然。"""
        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self.pane = pane

        card_box = ttk.Frame(pane)
        self.card = tk.Canvas(card_box, height=CARD_HEIGHT, highlightthickness=0,
                              background=health_rules.PALETTE["paper"])
        self.card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.card.bind("<Configure>", lambda event: self.draw_card())
        pane.add(card_box, weight=0)

        holder = ttk.Frame(pane)
        self.frame_lang = ttk.Frame(holder)
        self.tree_lang = self.make_table(self.frame_lang, LANG_HEADINGS)
        self.frame_file = ttk.Frame(holder)
        self.tree_file = self.make_table(self.frame_file, FILE_HEADINGS)
        self.frame_dim = ttk.Frame(holder)
        self.tree_dim = self.make_table(self.frame_dim, DIM_HEADINGS)
        self.tree = self.tree_lang
        pane.add(holder, weight=1)

        self.make_row_menu((
            ("复制该行", self.copy_selected),
            ("自适应列宽", self.autofit_columns),
            None,
            ("打开文件", self.open_selected_file),
            ("打开所在目录", self.open_selected_dir),
            ("复制完整路径", self.copy_selected_path),
        ))
        # 基类只把右键菜单绑在第一张表上；本页三张表共用同一个菜单，
        # 所以先拆掉那张表的绑定，再统一绑到三张表（回调用 event.widget 判定表格）。
        for tree in (self.tree_lang, self.tree_file, self.tree_dim):
            tree.unbind("<Button-3>")
            tree.unbind("<Button-2>")
            tree.bind(self.right_click_seq, self.on_any_right_click)

    @property
    def right_click_seq(self):
        """macOS 的 Tk 把右键上报为 Button-2，其余平台是 Button-3。"""
        return "<Button-2>" if sys.platform == "darwin" else "<Button-3>"

    def on_any_right_click(self, event):
        tree = event.widget
        item = tree.identify_row(event.y)
        if item:
            if item not in tree.selection():
                tree.selection_set(item)
            self.menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def clear_all_tables(self):
        """三张表都清空：切视图时旧表不会残留上一次的结果。"""
        for tree in (self.tree_lang, self.tree_file, self.tree_dim):
            for item in tree.get_children():
                tree.delete(item)
        self._item_rows = {}

    def build_summary(self):
        self.var_summary = tk.StringVar(value="尚未分析")
        self.label_summary = ttk.Label(self, textvariable=self.var_summary, anchor="w",
                                       justify=tk.LEFT)
        self.label_summary.pack(fill=tk.X, padx=8, pady=(0, 3))
        self.bind("<Configure>", lambda event: self.label_summary.configure(
            wraplength=max(event.width - 24, 240)))

    # ==================== 扫描目标 ====================
    def engine_label(self, engine_id):
        label = health_engine.ENGINE_LABELS[engine_id]
        if engine_id == "builtin_precise" and not self.optional.get("lizard"):
            return f"{label}·未安装"
        if engine_id in ("scc", "tokei") and not self.optional.get(engine_id):
            return f"{label}·未安装"
        return label

    def default_dir(self):
        here = os.path.dirname(os.path.abspath(__file__))
        return ignore_rules.find_git_root(here) or os.getcwd()

    def target_entries(self):
        return [self.list_targets.get(i) for i in range(self.list_targets.size())]

    def add_targets(self, paths):
        existing = {os.path.normcase(os.path.abspath(p)) for p in self.target_entries()}
        added = 0
        for raw in paths:
            path = os.path.abspath(str(raw).strip().strip('"'))
            key = os.path.normcase(path)
            if not path or key in existing:
                continue
            existing.add(key)
            self.list_targets.insert(tk.END, path)
            added += 1
        return added

    def current_targets(self):
        return ignore_rules.normalize_targets(self.target_entries())

    def pick_dir(self):
        entries = self.target_entries()
        current = entries[0] if entries else self.default_dir()
        path = filedialog.askdirectory(
            title="选择要分析的目录",
            initialdir=current if os.path.isdir(current) else None)
        if path:
            added = self.add_targets([os.path.normpath(path)])
            self.set_status(f"已加入 {added} 个目录" if added else "该目录已在列表里")

    def pick_files(self):
        entries = self.target_entries()
        current = entries[0] if entries else self.default_dir()
        paths = filedialog.askopenfilenames(
            title="选择要分析的文件（可多选）",
            initialdir=current if os.path.isdir(current) else None)
        if paths:
            added = self.add_targets(list(paths))
            self.set_status(f"已加入 {added} 个文件" if added else "这些文件已在列表里")

    def fill_default(self):
        added = self.add_targets([self.default_dir()])
        self.set_status(f"已填入默认目录" if added else "默认目录已在列表里")

    def del_targets(self):
        for index in reversed(self.list_targets.curselection()):
            self.list_targets.delete(index)

    def clear_targets(self):
        self.list_targets.delete(0, tk.END)

    # ==================== 排除目录 ====================
    def exclude_entries(self):
        return [self.list_excludes.get(i) for i in range(self.list_excludes.size())]

    def add_exclude(self):
        path = filedialog.askdirectory(title="选择要排除的目录")
        if path and path not in self.exclude_entries():
            self.list_excludes.insert(tk.END, path)

    def del_exclude(self):
        for index in reversed(self.list_excludes.curselection()):
            self.list_excludes.delete(index)

    def clear_excludes(self):
        self.list_excludes.delete(0, tk.END)

    def fill_git_ignored(self):
        roots = [t["path"] for t in self.current_targets() if t["kind"] == "dir"]
        repos = [r for r in roots if ignore_rules.is_git_repo(r)]
        if not repos:
            messagebox.showinfo("提示", "扫描目标里没有 git 仓库目录，无法读取忽略项")
            return
        existing = set(self.exclude_entries())
        added = 0
        for root in repos:
            for rel in ignore_rules.git_ignored_dirs(root):
                if rel not in existing:
                    self.list_excludes.insert(tk.END, rel)
                    existing.add(rel)
                    added += 1
        self.set_status(f"已填入 {added} 个 git 忽略目录（{len(repos)} 个仓库）")

    # ==================== 基类钩子 ====================
    def on_busy_changed(self, busy):
        state = "disabled" if busy else "normal"
        self.btn_run.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def row_values(self, row):
        if self.view_mode == VIEW_DIM:
            return (row["name"], row["raw_text"], row["unit"], row["normalized"],
                    row["weight"], row["weighted"], row["note"])
        if self.view_mode == VIEW_FILE:
            return (row["rel"], row["language"], row["total"], row["code"],
                    row["branch_hits"], row["max_indent"], row["dup_lines"],
                    row["todo_count"], row["score"])
        return (row["language"], row["files"], row["total"], row["blank"],
                row["comment"], row["code"], f"{row['share']}%")

    def row_text(self, row):
        if self.view_mode == VIEW_DIM:
            return f"{row['name']} {row['unit']} {row['note']}".lower()
        if self.view_mode == VIEW_FILE:
            return " ".join(str(row.get(k, "")) for k in
                            ("rel", "language", "total", "code", "score")).lower()
        return row["language"].lower()

    def on_row_activate(self, row):
        self.open_selected_file()

    # ==================== 视图 ====================
    def switch_view(self, mode, refresh=True):
        self.view_mode = mode
        self.var_view.set(mode)
        for frame in (self.frame_lang, self.frame_file, self.frame_dim):
            frame.pack_forget()
        if mode == VIEW_DIM:
            self.rows = self.dim_rows
            self.frame_dim.pack(fill=tk.BOTH, expand=True)
            self.tree = self.tree_dim
        elif mode == VIEW_FILE:
            self.rows = self.file_rows
            self.frame_file.pack(fill=tk.BOTH, expand=True)
            self.tree = self.tree_file
        else:
            self.rows = self.lang_rows
            self.frame_lang.pack(fill=tk.BOTH, expand=True)
            self.tree = self.tree_lang
        if refresh:
            self.refresh_table()

    def on_snark_changed(self):
        """切换毒舌模式：只重算文案，不重读磁盘（分数完全不变）。"""
        if self.index is None:
            return
        self.index = health_engine.build_index(
            self.file_rows, extra=self.extra, precise=self.precise_agg(),
            snark=self.var_snark.get())
        self.build_dim_rows()
        if self.view_mode == VIEW_DIM:
            self.refresh_table()
        self.draw_card()
        self.update_summary()
        self.set_status("已切换文案风格（分数不受影响）")

    # ==================== 分析流程 ====================
    def start_analyze(self):
        if self.running:
            return
        targets = self.current_targets()
        if not targets:
            messagebox.showerror("错误", "请先添加扫描目标（目录或文件）。")
            return

        engine = self.engine_ids[self.combo_engine.current()]
        # 先把所有"选不了"的情况挡在前面：被挡下时不动任何已有结果，
        # 也不改 self.engine_key（否则一次误选就把页面状态带偏了）。
        if engine in health_engine.UNADAPTED_EXTERNAL:
            messagebox.showerror(
                "引擎未适配",
                f"{health_engine.UNADAPTED_EXTERNAL[engine]} 的输出格式本页暂未适配，"
                "请改用「内置启发式」或「内置 + 精确·lizard」。")
            return
        if engine == "builtin_precise" and not self.optional.get("lizard"):
            messagebox.showerror(
                "精确层不可用",
                "精确层需要 lizard（函数级圈复杂度/嵌套）。\n\n"
                "安装：pip install lizard\n"
                "未安装时请改用「内置启发式」。")
            return
        if engine in ("scc", "tokei"):
            if not self.optional.get(engine):
                messagebox.showerror("引擎不可用",
                                     f"{engine} 未安装或不在 PATH 上。")
                return
            if len(targets) != 1 or targets[0]["kind"] != "dir":
                messagebox.showerror(
                    "引擎不支持多目标",
                    f"{engine} 一次只能扫一个目录，当前有 {len(targets)} 个目标。\n"
                    "请改用内置引擎，或把目标减到一个目录。")
                return

        self.engine_key = engine
        if engine in ("scc", "tokei"):
            self.reset_state()
            self.run_external(engine, targets[0]["path"])
            return

        self.reset_state()
        try:
            enum = ignore_rules.enumerate_targets(
                targets, excludes=self.exclude_entries(), extensions=None,
                tracked_only=False)
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return

        self.enum_result = enum
        self.failed = list(enum.failed)
        if not enum.files:
            self.set_status("没有可分析的文件（检查扫描目标与排除列表）")
            self.update_retry_button()
            return

        self.set_status(f"分析中... 0/{len(enum.files)}")
        self.set_progress(0, len(enum.files))
        self.analyze_started = time.perf_counter()
        self.start_chunked(enum.files, self.analyze_one, chunk=40,
                           on_tick=self.on_analyze_tick, on_done=self.on_analyze_done,
                           on_item_error=self.on_item_error)

    def reset_state(self):
        self.file_rows = []
        self.lang_rows = []
        self.dim_rows = []
        self.rows = self.lang_rows
        self.enum_result = None
        self.extra = {}
        self.precise_rows = []
        self.precise_note = ""
        self.index = None
        self.unknown = {"top": [], "kinds": 0, "files": 0}
        self.failed = []
        self.scanned_at = ""
        self.clear_all_tables()

    def analyze_one(self, path):
        """分析一个文件；读不了就记进失败清单，不让它拖垮整批。"""
        row = health_engine.scan_file(path)     # 读不了会抛 ReadError，由分片层兜住
        self.file_rows.append(row)
        if self.engine_key == "builtin_precise":
            self.precise_rows.append(health_engine.lizard_metrics(path))

    def analyze_one_checked(self, path):
        """重试用：先重新探一遍（被锁的二进制文件不能当文本读进来），再分析。"""
        ok, reason = ignore_rules.probe_file(path)
        if not ok:
            if reason in ignore_rules.RETRYABLE_REASONS:
                self.record_failure(path, reason)
            return
        self.analyze_one(path)

    def record_failure(self, path, reason, detail=""):
        self.failed.append((path, reason, detail))

    def on_item_error(self, item, exc):
        if isinstance(exc, loc_engine.ReadError):
            self.record_failure(item, exc.reason, exc.detail)
            return
        self.record_failure(str(item), "分析出错", f"{type(exc).__name__}: {exc}")

    def on_analyze_tick(self, index, total):
        self.set_progress(index)
        if index < total:
            self.set_status(f"分析中... {index}/{total}")

    def on_analyze_done(self):
        elapsed = time.perf_counter() - self.analyze_started
        self.finish_analysis(elapsed=elapsed)

    def stop_analyze(self):
        if not self.stop_chunked():
            self.set_status("当前没有正在进行的分析")
            return
        self.finish_analysis()
        self.set_status(f"已停止：已分析 {len(self.file_rows)} 个文件")

    def run_external(self, engine, root):
        self.set_status(f"正在调用外部引擎 {engine}...（大目录可能较慢）")
        self.update_idletasks()
        try:
            rows, extra, note = health_engine.scan_external(engine, root)
        except loc_engine.EngineError as exc:
            messagebox.showerror("外部引擎失败", f"{exc}\n\n已回退为内置引擎重新分析。")
            self.combo_engine.current(0)
            self.engine_key = "builtin"
            self.start_analyze()
            return
        self.file_rows = rows
        self.extra = extra
        root_abs = os.path.abspath(root)
        for row in self.file_rows:
            row["origin"] = ignore_rules.target_label(root_abs)
        self.finish_analysis(note=note, root=root_abs)

    def precise_agg(self):
        if not self.precise_rows:
            return None
        return health_engine.aggregate_precise(self.precise_rows)

    def finish_analysis(self, elapsed=None, note="", root=None):
        if not self.file_rows:
            self.index = None
            self.draw_card()
            self.update_summary()
            self.update_retry_button()
            self.set_status(f"没有分析到任何文件"
                            + (f"，其中 {len(self.failed)} 个读不了" if self.failed else ""))
            return

        summary, by_language = health_engine.build_profile(self.file_rows)
        self.lang_rows = loc_engine.language_rows(by_language)

        for row in self.file_rows:
            score, grade = health_engine.score_single(row)
            row["score"] = score
            row["grade_name"] = grade["name"]
            if root is not None:
                row["rel"] = self.relative(row["path"], root)

        if self.enum_result is not None:
            enum = self.enum_result
            for row in self.file_rows:
                key = os.path.normcase(row["path"])
                base = enum.file_roots.get(key) or os.path.dirname(row["path"])
                row["rel"] = self.relative(row["path"], base)
                row["origin"] = enum.origins.get(key, "")

        agg = self.precise_agg() if self.engine_key == "builtin_precise" else None
        if self.engine_key == "builtin_precise":
            self.precise_note = ("精确层已生效（函数级圈复杂度）" if agg
                                 else "精确层未取到函数（本批文件无可用函数级指标）")
        else:
            self.precise_note = ""

        self.index = health_engine.build_index(self.file_rows, extra=self.extra,
                                               precise=agg, snark=self.var_snark.get())
        self.unknown = health_engine.unknown_extensions(self.file_rows)
        self.scanned_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.build_dim_rows()
        self.switch_view(self.view_mode, refresh=False)
        self.refresh_table()
        self.draw_card()
        self.set_progress(1, 1)
        self.update_summary(elapsed=elapsed, note=note)
        self.update_retry_button()

        parts = [f"完成：{len(self.file_rows)} 个文件"]
        if self.index:
            parts.append(f"屎山指数 {self.index['score']}（{self.index['grade']['name']}）")
        if elapsed is not None:
            parts.append(f"耗时 {elapsed:.2f} 秒")
        if self.enum_result is not None:
            parts.append(f"（{self.enum_result.mode_summary()}）")
        if self.precise_note:
            parts.append(self.precise_note)
        unknown_text = health_engine.unknown_summary(self.unknown)
        if unknown_text:
            parts.append(unknown_text)
        if self.failed:
            parts.append(f"有 {len(self.failed)} 个文件读不了，可点「重试失败项」")
        self.set_status(" · ".join(parts))

    def build_dim_rows(self):
        if not self.index:
            self.dim_rows = []
            return
        self.dim_rows = list(self.index["dimensions"])

    def update_retry_button(self):
        if self.failed:
            self.btn_retry.configure(text=f"重试失败项({len(self.failed)})")
            if not self.btn_retry.winfo_manager():
                self.btn_retry.pack(side=tk.LEFT, padx=(8, 0))
        elif self.btn_retry.winfo_manager():
            self.btn_retry.pack_forget()

    def retry_failed(self):
        if self.running:
            return
        pending = [path for path, _reason, _detail in self.failed]
        if not pending:
            self.set_status("没有需要重试的文件")
            self.update_retry_button()
            return
        self.failed = []
        self.update_retry_button()
        self.set_status(f"重试中... 0/{len(pending)}")
        self.set_progress(0, len(pending))
        self.analyze_started = time.perf_counter()
        self.start_chunked(pending, self.analyze_one_checked, chunk=20,
                           on_tick=self.on_analyze_tick,
                           on_done=self.on_retry_done,
                           on_item_error=self.on_item_error)

    def on_retry_done(self):
        self.finish_analysis(elapsed=time.perf_counter() - self.analyze_started)
        if self.failed:
            self.set_status(f"重试后仍有 {len(self.failed)} 个文件读不了（可能还被占用）")
        else:
            self.set_status("重试完成，失败项已全部并入结果")

    @staticmethod
    def relative(path, base):
        try:
            return os.path.relpath(path, base)
        except ValueError:
            return path

    def update_summary(self, elapsed=None, note=""):
        if not self.file_rows:
            self.var_summary.set("尚未分析")
            return
        stats = self.index["stats"] if self.index else {}
        parts = [
            f"文件 {len(self.file_rows)}",
            f"总行 {stats.get('total', 0)}",
            f"代码 {stats.get('code', 0)}",
            f"注释 {stats.get('comment', 0)}",
            f"空行 {stats.get('blank', 0)}",
        ]
        if self.index:
            parts.append(f"屎山指数 {self.index['score']}（{self.index['grade']['name']}）"
                         f"· {self.index['grade_short']}")
        if self.enum_result is not None and self.enum_result.skipped:
            parts.append("跳过 " + self.enum_result.skip_summary())
        if note:
            parts.append(note)
        self.var_summary.set(" · ".join(parts))

    # ==================== 成分表卡（纯 Canvas 手绘） ====================
    def draw_card(self):
        canvas = getattr(self, "card", None)
        if canvas is None:
            return
        palette = health_rules.PALETTE
        width = max(canvas.winfo_width(), 480)
        height = max(canvas.winfo_height(), CARD_HEIGHT)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill=palette["paper"],
                                outline=palette["border"])
        if not self.index or not self.file_rows:
            canvas.create_text(width / 2, height / 2 - 10, text="代码成分表",
                               font=self._fonts["title"], fill=palette["ink"])
            canvas.create_text(width / 2, height / 2 + 26,
                               text="加好扫描目标后点「开始分析」，这里会生成成分表与屎山指数",
                               font=self._fonts["small"], fill=palette["ink_soft"])
            return

        margin = CARD_MARGIN
        title_y = 16
        canvas.create_text(margin, title_y, text="代码成分表", anchor="nw",
                           font=self._fonts["title"], fill=palette["ink"])
        subtitle = f"{self.project_label()} · {self.scanned_at} · {self.engine_label_plain()}"
        canvas.create_text(margin, title_y + 32, text=self._ellipsis(subtitle,
                           self._fonts["small"], width * 0.55), anchor="nw",
                           font=self._fonts["small"], fill=palette["ink_soft"])

        self._draw_score(width - margin, title_y, margin)
        divider_y = 84
        canvas.create_line(margin, divider_y, width - margin, divider_y,
                           fill=palette["border"])

        left_x0 = margin
        left_x1 = int(width * 0.52)
        right_x0 = int(width * 0.56)
        right_x1 = width - margin
        body_y = divider_y + 16
        strip_y = height - 74

        self._draw_language(left_x0, left_x1, body_y, strip_y - 14)
        self._draw_lines(right_x0, right_x1, body_y, strip_y - 14)
        self._draw_dimension_strip(margin, width - margin, strip_y)

    def _draw_score(self, right_x, top_y, margin):
        palette = health_rules.PALETTE
        index = self.index
        grade = index["grade"]
        self.card.create_text(right_x, top_y, text="屎山指数", anchor="ne",
                              font=self._fonts["small"], fill=palette["ink_soft"])
        self.card.create_text(right_x, top_y + 16, text=str(index["score"]), anchor="ne",
                              font=self._fonts["score"], fill=grade["color"])
        self.card.create_text(right_x, top_y + 56,
                              text=f"{grade['name']} · {index['grade_short']}",
                              anchor="ne", font=self._fonts["section"], fill=grade["color"])

    def _draw_language(self, x0, x1, y0, y1):
        """语言成分：色块 + 语言名 + 占比 + 占比条（按代码行，Top 8 + 其他）。"""
        palette = health_rules.PALETTE
        self.card.create_text(x0, y0, text="语言成分（按代码行）", anchor="nw",
                              font=self._fonts["section"], fill=palette["ink"])
        rows = [r for r in self.lang_rows if r.get("code")]
        if not rows:
            self.card.create_text(x0, y0 + 30, text="没有可展示的语言成分",
                                  anchor="nw", font=self._fonts["small"],
                                  fill=palette["ink_soft"])
            return
        top = rows[:8]
        rest = rows[8:]
        total_code = sum(r["code"] for r in rows)
        items = [(r["language"], r["code"]) for r in top]
        if rest:
            items.append(("其他 %d 种" % len(rest), sum(r["code"] for r in rest)))

        row_h = 22
        max_rows = max(1, int((y1 - y0 - 26) // row_h))
        items = items[:max_rows]
        bar_x0 = x0 + 108
        for i, (name, code) in enumerate(items):
            y = y0 + 26 + i * row_h
            share = code * 100.0 / total_code if total_code else 0.0
            self.card.create_rectangle(x0, y + 1, x0 + 10, y + 11,
                                       fill=health_rules.lang_color(name),
                                       outline=palette["border"])
            self.card.create_text(x0 + 16, y + 6,
                                  text=self._ellipsis(name, self._fonts["small"], 84),
                                  anchor="w", font=self._fonts["small"], fill=palette["ink"])
            self.card.create_text(x1, y + 6, text=f"{share:.1f}%", anchor="e",
                                  font=self._fonts["small"], fill=palette["ink_soft"])
            self.card.create_rectangle(bar_x0, y + 12, x1, y + 17,
                                       fill=palette["track"], outline="")
            fill_w = int((x1 - bar_x0) * min(share, 100.0) / 100.0)
            if fill_w > 1:
                self.card.create_rectangle(bar_x0, y + 12, bar_x0 + fill_w, y + 17,
                                           fill=health_rules.lang_color(name), outline="")

    def _draw_lines(self, x0, x1, y0, y1):
        """行成分：代码/注释/空 三段堆叠条 + 图例 + 体量。"""
        palette = health_rules.PALETTE
        stats = self.index["stats"]
        total = max(stats.get("total", 0), 1)
        self.card.create_text(x0, y0, text="行成分", anchor="nw",
                              font=self._fonts["section"], fill=palette["ink"])

        bar_y0 = y0 + 26
        bar_y1 = bar_y0 + 26
        cursor = x0
        spans = (("code", stats.get("code", 0)), ("comment", stats.get("comment", 0)),
                 ("blank", stats.get("blank", 0)))
        for key, value in spans:
            seg = (x1 - x0) * value / total
            if seg > 0:
                self.card.create_rectangle(cursor, bar_y0, cursor + seg, bar_y1,
                                           fill=health_rules.LINE_COLORS[key], outline="")
            cursor += seg
        self.card.create_rectangle(x0, bar_y0, x1, bar_y1, outline=palette["border"])

        labels = (("code", "有效代码"), ("comment", "注释"), ("blank", "空行"))
        legend_y = bar_y1 + 14
        for i, (key, text) in enumerate(labels):
            y = legend_y + i * 19
            value = stats.get(key, 0)
            self.card.create_rectangle(x0, y, x0 + 10, y + 10,
                                       fill=health_rules.LINE_COLORS[key], outline="")
            self.card.create_text(x0 + 16, y + 5, text=text, anchor="w",
                                  font=self._fonts["small"], fill=palette["ink"])
            self.card.create_text(x1, y + 5,
                                  text=f"{value} 行 · {value * 100.0 / total:.1f}%",
                                  anchor="e", font=self._fonts["small"],
                                  fill=palette["ink_soft"])

        foot_y = legend_y + 3 * 19 + 6
        extra = [f"文件 {stats.get('files', 0)}", f"总行 {stats.get('total', 0)}"]
        cover = self._comment_rate_text(stats)
        if cover:
            extra.append(cover)
        if self.precise_note:
            extra.append(self.precise_note)
        unknown_text = health_engine.unknown_summary(self.unknown)
        if unknown_text:
            extra.append(unknown_text)
        self.card.create_text(x0, foot_y,
                              text=self._ellipsis(" · ".join(extra),
                                                  self._fonts["small"], x1 - x0),
                              anchor="nw", font=self._fonts["small"],
                              fill=palette["ink_soft"])

    def _comment_rate_text(self, stats):
        non_blank = stats.get("non_blank", 0)
        if not non_blank:
            return ""
        rate = stats.get("comment", 0) * 100.0 / non_blank
        return f"注释率 {rate:.1f}%（占非空行）"

    def _unknown_notice_html(self):
        """导出卡片里的「未识别扩展名」一行；没有未识别时不产生任何节点。"""
        text = health_engine.unknown_summary(self.unknown)
        if not text:
            return ""
        return f'<div class="notice">未识别扩展名：{html.escape(text)}</div>'

    def _draw_dimension_strip(self, x0, x1, y0):
        """底部七维小条：每条是「维度名 + 子分 + 子分条」，颜色取该档的等级色。"""
        palette = health_rules.PALETTE
        dims = self.index["dimensions"]
        self.card.create_text(x0, y0, text="维度子分（越高越差）", anchor="nw",
                              font=self._fonts["small"], fill=palette["ink_soft"])
        if not dims:
            return
        gap = 10
        chip_w = (x1 - x0 - gap * (len(dims) - 1)) / len(dims)
        for i, dim in enumerate(dims):
            cx0 = x0 + i * (chip_w + gap)
            cx1 = cx0 + chip_w
            color = health_rules.grade_for(int(round(dim["normalized"])))["color"]
            self.card.create_text(cx0, y0 + 18,
                                  text=self._ellipsis(dim["name"], self._fonts["tiny"], chip_w),
                                  anchor="w", font=self._fonts["tiny"], fill=palette["ink"])
            self.card.create_text(cx1, y0 + 18, text=f"{dim['normalized']:.0f}",
                                  anchor="e", font=self._fonts["small"], fill=color)
            bar_y = y0 + 32
            self.card.create_rectangle(cx0, bar_y, cx1, bar_y + 6,
                                       fill=palette["track"], outline="")
            fill_w = int(chip_w * min(dim["normalized"], 100.0) / 100.0)
            if fill_w > 1:
                self.card.create_rectangle(cx0, bar_y, cx0 + fill_w, bar_y + 6,
                                           fill=color, outline="")

    def _ellipsis(self, text, font, max_width):
        """按实际字宽裁到 max_width，超出补省略号（Tk 不做工具提示，宁短不遮）。"""
        if not text:
            return ""
        if font.measure(text) <= max_width:
            return text
        cut = str(text)
        while cut and font.measure(cut + "…") > max_width:
            cut = cut[:-1]
        return cut + "…"

    def project_label(self):
        entries = self.target_entries()
        if not entries:
            return "未知目标"
        if len(entries) == 1:
            return os.path.basename(os.path.normpath(entries[0])) or entries[0]
        return f"{len(entries)} 个目标"

    def engine_label_plain(self):
        return health_engine.ENGINE_LABELS.get(self.engine_key, self.engine_key)

    # ==================== 选中行操作 ====================
    def open_selected_file(self):
        row = self.selected_row()
        if row is None or "path" not in row:
            self.set_status("请先切到「按文件」视图并选中一行")
            return
        if not os.path.isfile(row["path"]):
            messagebox.showerror("错误", f"文件不存在：{row['path']}")
            return
        try:
            open_path(row["path"])
            self.set_status(f"已打开：{row['path']}")
        except Exception as exc:
            messagebox.showerror("错误", f"打开失败：{exc}")

    def open_selected_dir(self):
        row = self.selected_row()
        if row is None or "path" not in row:
            self.set_status("请先切到「按文件」视图并选中一行")
            return
        try:
            open_path(os.path.dirname(row["path"]))
            self.set_status(f"已打开目录：{os.path.dirname(row['path'])}")
        except Exception as exc:
            messagebox.showerror("错误", f"打开目录失败：{exc}")

    def copy_selected_path(self):
        row = self.selected_row()
        if row is None or "path" not in row:
            self.set_status("请先切到「按文件」视图并选中一行")
            return
        self.clipboard_clear()
        self.clipboard_append(row["path"])
        self.set_status(f"已复制路径：{row['path']}")

    # ==================== 导出 ====================
    def export_result(self):
        if self.view_mode == VIEW_DIM:
            headers = ["维度", "原始值", "单位", "子分", "权重", "加权", "点评"]
            name = "代码成分表_维度明细.csv"
        elif self.view_mode == VIEW_FILE:
            headers = ["文件路径", "语言", "总行数", "代码行", "分支数", "最大缩进",
                       "重复行", "TODO", "文件分"]
            name = "代码成分表_按文件.csv"
        else:
            headers = ["语言", "文件数", "总行数", "空行", "注释行", "代码行", "代码占比"]
            name = "代码成分表_按语言.csv"
        self.export_csv(headers, name)

    def copy_markdown(self):
        if not self.file_rows:
            self.set_status("还没有可复制的分析结果")
            return
        self.clipboard_clear()
        self.clipboard_append(self._markdown_text())
        self.set_status("已复制 Markdown 报告到剪贴板")

    def _markdown_text(self):
        index = self.index
        lines = [f"# 代码成分表 · {self.project_label()}", ""]
        lines.append(f"- 扫描时间：{self.scanned_at}")
        lines.append(f"- 引擎：{self.engine_label_plain()}")
        lines.append(f"- **屎山指数：{index['score']} / 100（{index['grade']['name']} · "
                     f"{index['grade_short']}）**")
        lines.append("")
        lines.append("## 语言成分")
        lines.append("")
        lines.append("| 语言 | 文件数 | 总行 | 注释行 | 代码行 | 代码占比 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for row in self.lang_rows:
            lines.append(f"| {row['language']} | {row['files']} | {row['total']} | "
                         f"{row['comment']} | {row['code']} | {row['share']}% |")
        stats = index["stats"]
        lines += ["", "## 行成分", "",
                  f"- 有效代码 {stats.get('code', 0)} 行",
                  f"- 注释 {stats.get('comment', 0)} 行",
                  f"- 空行 {stats.get('blank', 0)} 行",
                  "", "## 屎山指数明细", "",
                  "| 维度 | 原始值 | 单位 | 子分 | 权重 | 点评 |",
                  "| --- | ---: | --- | ---: | ---: | --- |"]
        for dim in index["dimensions"]:
            lines.append(f"| {dim['name']} | {dim['raw_text']} | {dim['unit']} | "
                         f"{dim['normalized']} | {dim['weight']} | {dim['note']} |")
        if self.unknown.get("files"):
            lines += ["", "## 未识别扩展名", "",
                      "这些文件目前按「纯文本」统计（没有注释语法）：", "",
                      "| 扩展名 | 文件数 |", "| --- | ---: |"]
            for ext, count in self.unknown["top"]:
                lines.append(f"| {ext} | {count} |")
            rest = self.unknown["kinds"] - len(self.unknown["top"])
            if rest > 0:
                lines.append(f"| 其他 {rest} 种 | … |")
        lines += ["", f"> {index['overall']}", "",
                  f"*由 {APP_NAME} {APP_VERSION} 生成*", ""]
        return "\n".join(lines)

    def export_card(self):
        """导出可分享卡片：自包含 HTML（内联 SVG/CSS，零外链、断网可开）。"""
        if not self.file_rows or not self.index:
            messagebox.showinfo("提示", "还没有分析结果，先点「开始分析」")
            return
        project = self.project_label()
        default_name = f"代码成分表_{project}_{datetime.now():%Y%m%d}.html"
        save_path = filedialog.asksaveasfilename(
            defaultextension=".html", initialfile=default_name,
            filetypes=[("HTML 卡片", "*.html"), ("所有文件", "*.*")])
        if not save_path:
            return
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(self._html_card(project))
        except OSError as exc:
            messagebox.showerror("错误", f"写入文件失败：{exc}")
            return
        self.set_status(f"已导出分享卡片：{save_path}")
        messagebox.showinfo("成功", f"已导出分享卡片：\n{save_path}")

    def _html_card(self, project):
        index = self.index
        stats = index["stats"]
        palette = health_rules.PALETTE
        total = max(stats.get("total", 0), 1)
        grade = index["grade"]

        def esc(text):
            return html.escape(str(text))

        lang_rows = "".join(
            f'<div class="lang">'
            f'<span class="swatch" style="background:{health_rules.lang_color(r["language"])}"></span>'
            f'<span class="lname">{esc(r["language"])}</span>'
            f'<span class="lbar"><i style="width:{min(r["share"], 100.0):.1f}%;'
            f'background:{health_rules.lang_color(r["language"])}"></i></span>'
            f'<span class="lpct">{r["share"]}%</span></div>'
            for r in self.lang_rows[:10]
        )

        def seg(key):
            return stats.get(key, 0) * 100.0 / total

        dim_rows = "".join(
            f'<tr><td>{esc(d["name"])}</td><td class="num">{esc(d["raw_text"])}</td>'
            f'<td class="unit">{esc(d["unit"])}</td>'
            f'<td class="num">{d["normalized"]}</td><td class="num">{d["weight"]}</td>'
            f'<td>{esc(d["note"])}</td></tr>'
            for d in index["dimensions"]
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>代码成分表 · {esc(project)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; padding: 32px; background: #f3efe6;
         font-family: "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB",
                      system-ui, -apple-system, sans-serif;
         color: {palette["ink"]}; }}
  .card {{ max-width: 860px; margin: 0 auto; background: {palette["paper"]};
           border: 1px solid {palette["border"]}; border-radius: 14px;
           padding: 22px 26px 20px; box-shadow: 0 10px 30px rgba(61,53,41,.10); }}
  .head {{ display: flex; align-items: flex-start; justify-content: space-between;
           gap: 20px; border-bottom: 1px solid {palette["border"]};
           padding-bottom: 14px; }}
  h1 {{ margin: 0; font-size: 24px; letter-spacing: .5px; }}
  .meta {{ margin-top: 6px; font-size: 12px; color: {palette["ink_soft"]}; }}
  .score {{ text-align: right; line-height: 1.1; }}
  .score .num {{ font-size: 44px; font-weight: 700; }}
  .score .cap {{ font-size: 12px; color: {palette["ink_soft"]}; }}
  .score .grade {{ font-size: 14px; font-weight: 600; margin-top: 2px; }}
  .cols {{ display: flex; gap: 28px; margin-top: 18px; flex-wrap: wrap; }}
  .col {{ flex: 1 1 320px; }}
  h2 {{ font-size: 14px; margin: 0 0 10px; }}
  .lang {{ display: flex; align-items: center; gap: 8px; font-size: 13px; margin: 7px 0; }}
  .swatch {{ width: 11px; height: 11px; border-radius: 3px; flex: none;
             border: 1px solid {palette["border"]}; }}
  .lname {{ width: 108px; flex: none; overflow: hidden; text-overflow: ellipsis;
            white-space: nowrap; }}
  .lbar {{ flex: 1 1 auto; height: 8px; border-radius: 4px;
           background: {palette["track"]}; overflow: hidden; }}
  .lbar i {{ display: block; height: 100%; }}
  .lpct {{ width: 52px; flex: none; text-align: right;
           color: {palette["ink_soft"]}; }}
  .stack {{ display: flex; height: 28px; border-radius: 6px; overflow: hidden;
            border: 1px solid {palette["border"]}; }}
  .stack span {{ display: block; height: 100%; }}
  .legend {{ margin-top: 12px; font-size: 13px; }}
  .legend div {{ display: flex; align-items: center; gap: 8px; margin: 5px 0; }}
  .legend b {{ font-weight: 600; }}
  .legend em {{ margin-left: auto; font-style: normal;
                color: {palette["ink_soft"]}; }}
  .notice {{ margin-top: 16px; font-size: 13px; color: {palette["ink_soft"]}; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid {palette["border"]}; padding: 8px 10px;
            text-align: left; vertical-align: top; }}
  th {{ font-size: 12px; color: {palette["ink_soft"]}; font-weight: 600;
        background: rgba(61,53,41,.03); }}
  td.num {{ text-align: right; white-space: nowrap; }}
  td.unit {{ color: {palette["ink_soft"]}; white-space: nowrap; }}
  footer {{ margin-top: 18px; font-size: 12px; color: {palette["ink_soft"]};
            text-align: center; }}
</style>
</head>
<body>
<div class="card">
  <div class="head">
    <div>
      <h1>代码成分表</h1>
      <div class="meta">{esc(project)} · {esc(self.scanned_at)} ·
        引擎 {esc(self.engine_label_plain())}</div>
    </div>
    <div class="score">
      <div class="cap">屎山指数（越高越差）</div>
      <div class="num" style="color:{grade['color']}">{index["score"]}</div>
      <div class="grade" style="color:{grade['color']}">
        {grade['emoji']} {esc(grade['name'])} · {esc(index["grade_short"])}</div>
    </div>
  </div>

  <div class="cols">
    <div class="col">
      <h2>语言成分（按代码行）</h2>
      {lang_rows}
    </div>
    <div class="col">
      <h2>行成分</h2>
      <div class="stack">
        <span style="width:{seg('code'):.2f}%;background:{health_rules.LINE_COLORS['code']}"></span>
        <span style="width:{seg('comment'):.2f}%;background:{health_rules.LINE_COLORS['comment']}"></span>
        <span style="width:{seg('blank'):.2f}%;background:{health_rules.LINE_COLORS['blank']}"></span>
      </div>
      <div class="legend">
        <div><span class="swatch" style="background:{health_rules.LINE_COLORS['code']}"></span>
          <b>有效代码</b><em>{stats.get('code', 0)} 行 · {seg('code'):.1f}%</em></div>
        <div><span class="swatch" style="background:{health_rules.LINE_COLORS['comment']}"></span>
          <b>注释</b><em>{stats.get('comment', 0)} 行 · {seg('comment'):.1f}%</em></div>
        <div><span class="swatch" style="background:{health_rules.LINE_COLORS['blank']}"></span>
          <b>空行</b><em>{stats.get('blank', 0)} 行 · {seg('blank'):.1f}%</em></div>
      </div>
      <div class="notice">文件 {stats.get('files', 0)} 个 · 总行 {stats.get('total', 0)} 行 ·
        {esc(self._comment_rate_text(stats))}</div>
      {self._unknown_notice_html()}
    </div>
  </div>

  <table>
    <thead>
      <tr><th>维度</th><th>原始值</th><th>单位</th><th>子分</th><th>权重</th><th>点评</th></tr>
    </thead>
    <tbody>{dim_rows}</tbody>
  </table>

  <div class="notice">{esc(index["overall"])}</div>
  <footer>由 {esc(APP_NAME)} {esc(APP_VERSION)} 生成 · 离线本地分析，零外链</footer>
</div>
</body>
</html>
"""