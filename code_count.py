#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""代码行数统计：按目录统计每个文件/每种语言的总行数、空行、注释行、有效代码行。

性能要点（本仓库 13.6 万文件 / 29GB，只有约 1000 个文件值得统计）：
  - 枚举走 git 清单或黑名单剪枝，绝不遍历构建产物目录；
  - 二进制嗅探 + 体积上限，避免 zip/exe/png 被当文本读出上百万行假代码；
  - 逐文件分片统计，界面不卡死、可中断；
  - 排序/筛选/切换视图/切换统计口径全部只重排内存，不重读磁盘。
"""

import os
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from share import ignore_rules, loc_engine, loc_langs, settings
from share.ui_common import ToolTab

FILE_HEADINGS = (
    ("origin", "来源", 130),
    ("rel", "文件路径", 420),
    ("language", "语言", 110),
    ("total", "总行数", 80),
    ("blank", "空行", 70),
    ("comment", "注释行", 80),
    ("metric", "有效代码行", 100),
)

LANG_HEADINGS = (
    ("language", "语言", 190),
    ("files", "文件数", 80),
    ("total", "总行数", 90),
    ("blank", "空行", 80),
    ("comment", "注释行", 90),
    ("metric", "有效代码行", 110),
    ("share", "代码占比", 90),
)


class CodeCountTab(ToolTab):
    """代码行数统计标签页，自身即容器，塞进 Notebook 就能用。"""

    def __init__(self, master):
        super().__init__(master, initial_status="就绪：加好扫描目标后点“开始统计”")
        loaded = settings.load()
        # 只有上次开着「记住设置」时才应用记录里的值；否则一律用默认值，
        # 也就是"关掉记忆"之后打开工具看到的是干净的默认状态。
        self.conf = loaded if loaded.get("remember") else dict(settings.DEFAULTS)
        self.prefs = settings.load_prefs()
        self.file_rows = []       # 文件级结果
        self.lang_rows = []       # 语言级结果
        self.rows = self.file_rows
        self.view_mode = self.conf.get("view_mode") or "file"
        self.enum_result = None
        self.fallback_count = 0   # 词法失败回退轻量的次数
        self.count_started = time.perf_counter()   # 避免异常路径算出天文数字耗时
        self.failed = []          # [(路径, 原因, 详情)] 读不了的文件，供「重试失败项」
        self.initial_targets, self.initial_note = self.resolve_initial_targets()
        self.build_ui()
        self.switch_view(self.view_mode, refresh=False)
        if self.initial_note:
            self.set_status(self.initial_note)

    def resolve_initial_targets(self):
        """决定扫描目标的初值。

        优先级：记忆的目标（且还在）> 默认目录（仅当开了「自动填入默认目标」）> 空列表。
        配置被改坏、或上次的目标已被删除/移动时，回到默认目录并在状态栏说明，
        而不是把一个不存在的路径填进去、等点统计时才报错。
        """
        remembered = list(self.conf.get("targets") or [])
        alive = [t for t in remembered if os.path.exists(t.get("path", ""))]
        if alive:
            return [t["path"] for t in alive], ""
        autofill = bool(self.prefs.get("autofill_default_target"))
        if remembered:
            if not autofill:
                return [], f"上次的扫描目标已不存在，列表已清空"
            missing = "、".join(t.get("path", "") for t in remembered[:2])
            return [self.default_dir()], f"上次的扫描目标不存在（{missing}…），已回到默认目录"
        if autofill:
            return [self.default_dir()], ""
        return [], ""

    # ==================== 界面 ====================
    def build_ui(self):
        self.build_control_bar()
        self.build_option_bar()
        self.build_workspace()
        self.build_summary()
        self.make_status_bar(self)

    def build_control_bar(self):
        box = ttk.Frame(self)
        box.pack(fill=tk.X, padx=3, pady=(3, 2))

        # 第一行：引擎 + 后缀 + 开始/停止/重试
        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="引擎:").pack(side=tk.LEFT)
        self.engine_specs = loc_engine.available_engines()
        self.engine_ids = list(self.engine_specs.keys())
        labels = [self.engine_label(e) for e in self.engine_ids]
        self.var_engine = tk.StringVar()
        self.combo_engine = ttk.Combobox(row1, textvariable=self.var_engine, values=labels,
                                         state="readonly", width=24)
        self.combo_engine.pack(side=tk.LEFT, padx=(3, 14))
        wanted = self.conf.get("engine") or "builtin"
        if wanted not in self.engine_ids:
            wanted = "builtin"
        self.combo_engine.current(self.engine_ids.index(wanted))

        ttk.Label(row1, text="后缀:").pack(side=tk.LEFT)
        self.var_ext = tk.StringVar(value=self.conf.get("extensions", ""))
        self.entry_ext = ttk.Entry(row1, textvariable=self.var_ext, width=22)
        self.entry_ext.pack(side=tk.LEFT, padx=3)
        ttk.Label(row1, text="留空=全部文本，多个用逗号分隔").pack(side=tk.LEFT, padx=(0, 14))

        self.btn_run = ttk.Button(row1, text="开始统计", width=10, command=self.start_count)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 3))
        self.btn_stop = ttk.Button(row1, text="停止", width=7, command=self.stop_count,
                                   state="disabled")
        self.btn_stop.pack(side=tk.LEFT)

        # 重试按钮平时不占位置：只有真的出现读不了的文件才显示
        self.btn_retry = ttk.Button(row1, text="重试失败项", width=13, command=self.retry_failed)

    def build_target_area(self, parent):
        """扫描目标：可混合放多个目录与多个单文件（照排除目录那套列表做）。

        作为可拖动容器的一个面板，所以高度能像排除目录那样拖。
        """
        frame = ttk.Frame(parent)

        head = ttk.Frame(frame)
        head.pack(fill=tk.X)
        ttk.Label(head, text="扫描目标（可混合目录与文件）:").pack(side=tk.LEFT)
        ttk.Button(head, text="添加目录", width=9,
                   command=self.pick_dir).pack(side=tk.LEFT, padx=(8, 3))
        ttk.Button(head, text="添加文件", width=9,
                   command=self.pick_files).pack(side=tk.LEFT, padx=3)
        ttk.Button(head, text="删除选中", width=9,
                   command=self.del_targets).pack(side=tk.LEFT, padx=3)
        ttk.Button(head, text="清空", width=7,
                   command=self.clear_targets).pack(side=tk.LEFT, padx=3)

        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.list_targets = tk.Listbox(body, height=3, selectmode="extended")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.list_targets.yview)
        self.list_targets.configure(yscrollcommand=sb.set)
        self.list_targets.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        # 走 add_targets 而不是直接 insert：统一分隔符（git 返回的路径是正斜杠）
        self.add_targets(self.initial_targets)
        return frame

    def target_entries(self):
        return [self.list_targets.get(i) for i in range(self.list_targets.size())]

    def add_targets(self, paths):
        """加入扫描目标：去重、按是否存在判目录还是文件。"""
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

    def del_targets(self):
        for index in reversed(self.list_targets.curselection()):
            self.list_targets.delete(index)

    def clear_targets(self):
        self.list_targets.delete(0, tk.END)

    def current_targets(self):
        """把列表里的路径转成枚举层要的 targets 结构。"""
        return ignore_rules.normalize_targets(self.target_entries())

    def build_option_bar(self):
        box = ttk.Frame(self)
        box.pack(fill=tk.X, padx=3, pady=(0, 3))

        # 第一行：统计选项与视图
        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X)
        self.var_lexical = tk.BooleanVar(value=self.conf.get("lexical", False))
        ttk.Checkbutton(row1, text="词法精确模式", variable=self.var_lexical,
                        command=self.on_metric_changed).pack(side=tk.LEFT, padx=(0, 10))
        self.var_skip_blank = tk.BooleanVar(value=self.conf.get("skip_blank", True))
        ttk.Checkbutton(row1, text="排除空行", variable=self.var_skip_blank,
                        command=self.on_metric_changed).pack(side=tk.LEFT, padx=(0, 10))
        self.var_skip_comment = tk.BooleanVar(value=self.conf.get("skip_comment", True))
        ttk.Checkbutton(row1, text="排除注释行", variable=self.var_skip_comment,
                        command=self.on_metric_changed).pack(side=tk.LEFT, padx=(0, 10))
        self.var_tracked = tk.BooleanVar(value=self.conf.get("tracked_only", False))
        ttk.Checkbutton(row1, text="只统计已跟踪文件", variable=self.var_tracked,
                        command=self.on_metric_changed).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(row1, text="视图:").pack(side=tk.LEFT)
        self.var_view = tk.StringVar(value=self.view_mode)
        ttk.Radiobutton(row1, text="按文件", value="file", variable=self.var_view,
                        command=lambda: self.switch_view("file")).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(row1, text="按语言", value="lang", variable=self.var_view,
                        command=lambda: self.switch_view("lang")).pack(side=tk.LEFT, padx=2)

        # 第二行：关键字筛选与导出
        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, pady=(3, 0))
        ttk.Label(row2, text="关键字:").pack(side=tk.LEFT)
        self.entry_filter = ttk.Entry(row2, width=20)
        self.entry_filter.pack(side=tk.LEFT, padx=3)
        self.entry_filter.bind("<Return>", lambda event: self.apply_filter())
        ttk.Button(row2, text="清除筛选", width=9,
                   command=self.clear_filter).pack(side=tk.LEFT, padx=(8, 3))
        ttk.Button(row2, text="复制选中", width=9,
                   command=self.copy_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="导出CSV", width=9,
                   command=self.export_result).pack(side=tk.LEFT, padx=3)

        # 记忆开关、自动填入开关与清除记录：放在这一行最右侧，跟导出这类动作挨着
        self.var_remember = tk.BooleanVar(value=bool(self.conf.get("remember")))
        ttk.Checkbutton(row2, text="记住设置", variable=self.var_remember,
                        command=self.on_remember_changed).pack(side=tk.LEFT, padx=(16, 3))
        # 这个开关的状态存在 prefs.json（与 settings.json 分开），默认关闭
        self.var_autofill = tk.BooleanVar(
            value=bool(self.prefs.get("autofill_default_target")))
        ttk.Checkbutton(row2, text="自动填入当前目录项目", variable=self.var_autofill,
                        command=self.on_autofill_changed).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(row2, text="清除记录", width=9,
                   command=self.clear_record).pack(side=tk.LEFT, padx=3)

    def build_workspace(self):
        """扫描目标、排除列表、结果表格三块放进同一个可拖动容器。

        每个面板之间的分隔条都能拖：目标列表太挤就往大拖，表格想更大就把它上面
        两块拖小 —— 高度分配完全由你决定。
        """
        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill=tk.BOTH, expand=True, padx=3, pady=(0, 3))
        self.pane = pane

        pane.add(self.build_target_area(pane), weight=0)
        pane.add(self.build_exclude_area(pane), weight=0)

        holder = ttk.Frame(pane)
        self.frame_file = ttk.Frame(holder)
        self.tree_file = self.make_table(self.frame_file, FILE_HEADINGS)
        self.frame_lang = ttk.Frame(holder)
        self.tree_lang = self.make_table(self.frame_lang, LANG_HEADINGS)
        self.frame_file.pack(fill=tk.BOTH, expand=True)
        self.tree = self.tree_file
        pane.add(holder, weight=1)

        self.make_row_menu((
            ("复制该行", self.copy_selected),
            ("自适应列宽", self.autofit_columns),
            None,
            ("打开文件", self.open_selected_file),
            ("打开所在目录", self.open_selected_dir),
            ("复制完整路径", self.copy_selected_path),
        ))

    def build_exclude_area(self, parent):
        frame = ttk.Frame(parent)

        head = ttk.Frame(frame)
        head.pack(fill=tk.X)
        ttk.Label(head, text="排除目录（黑名单遍历时生效；git 模式只按这里的条目排除）:"
                  ).pack(side=tk.LEFT)
        ttk.Button(head, text="添加目录", width=9,
                   command=self.add_exclude).pack(side=tk.LEFT, padx=(8, 3))
        ttk.Button(head, text="填入 git 忽略项", width=15,
                   command=self.fill_git_ignored).pack(side=tk.LEFT, padx=3)
        ttk.Button(head, text="删除选中", width=9,
                   command=self.del_exclude).pack(side=tk.LEFT, padx=3)
        ttk.Button(head, text="清空", width=7,
                   command=self.clear_excludes).pack(side=tk.LEFT, padx=3)

        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.list_excludes = tk.Listbox(body, height=4, selectmode="extended")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.list_excludes.yview)
        self.list_excludes.configure(yscrollcommand=sb.set)
        self.list_excludes.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        for entry in self.conf.get("excludes", []):
            self.list_excludes.insert(tk.END, entry)
        if not self.conf.get("excludes"):
            self.fill_git_ignored(quiet=True)
        return frame

    def build_summary(self):
        self.var_summary = tk.StringVar(value="尚未统计")
        self.label_summary = ttk.Label(self, textvariable=self.var_summary, anchor="w",
                                       justify=tk.LEFT)
        self.label_summary.pack(fill=tk.X, padx=6, pady=(0, 3))
        # 汇总信息很长，按窗口实际宽度换行，避免把窗口撑宽
        self.bind("<Configure>",
                  lambda event: self.label_summary.configure(wraplength=max(event.width - 20, 200)))

    def engine_label(self, engine_id):
        label, ok, note = self.engine_specs[engine_id]
        return label if ok else f"{label}·未安装"

    def default_dir(self):
        """默认扫描目标：本工具所在仓库根；不是仓库则用当前工作目录。"""
        here = os.path.dirname(os.path.abspath(__file__))
        return ignore_rules.find_git_root(here) or os.getcwd()

    def pick_dir(self):
        entries = self.target_entries()
        current = entries[0] if entries else self.default_dir()
        path = filedialog.askdirectory(
            title="选择要加入的目录",
            initialdir=current if os.path.isdir(current) else None,
        )
        if path:
            added = self.add_targets([os.path.normpath(path)])
            self.set_status(f"已加入 {added} 个目录" if added else "该目录已在列表里")

    def pick_files(self):
        entries = self.target_entries()
        current = entries[0] if entries else self.default_dir()
        paths = filedialog.askopenfilenames(
            title="选择要加入的文件（可多选）",
            initialdir=current if os.path.isdir(current) else None,
        )
        if paths:
            added = self.add_targets(list(paths))
            self.set_status(f"已加入 {added} 个文件" if added else "这些文件已在列表里")

    # ==================== 基类钩子 ====================
    def on_busy_changed(self, busy):
        state = "disabled" if busy else "normal"
        self.btn_run.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def row_values(self, row):
        if self.view_mode == "lang":
            return (row["language"], row["files"], row["total"], row["blank"],
                    row["comment"], row["metric"], f"{row['share']}%")
        return (row.get("origin", ""), row["rel"], row["language"], row["total"],
                row["blank"], row["comment"], row["metric"])

    def row_text(self, row):
        if self.view_mode == "lang":
            return row["language"].lower()
        return " ".join(str(row.get(k, "")) for k in
                        ("origin", "rel", "language", "total", "blank",
                         "comment", "metric")).lower()

    def on_row_activate(self, row):
        self.open_selected_file()

    # ==================== 视图与口径 ====================
    def switch_view(self, mode, refresh=True):
        self.view_mode = mode
        if mode == "lang":
            self.rows = self.lang_rows
            self.frame_file.pack_forget()
            self.frame_lang.pack(fill=tk.BOTH, expand=True)
            self.tree = self.tree_lang
        else:
            self.rows = self.file_rows
            self.frame_lang.pack_forget()
            self.frame_file.pack(fill=tk.BOTH, expand=True)
            self.tree = self.tree_file
        self.var_view.set(mode)
        if refresh:
            self.refresh_table()

    def current_metric(self, row):
        """有效代码行口径：默认剔除空行与注释行，可各自开关。"""
        value = row["total"]
        if self.var_skip_blank.get():
            value -= row["blank"]
        if self.var_skip_comment.get():
            value -= row["comment"]
        return value

    def on_metric_changed(self):
        """口径或模式变化：只重算内存里的数，不重读磁盘。"""
        if not self.file_rows and not self.lang_rows:
            return
        self.recompute_metrics()
        self.refresh_table()
        self.update_summary()

    def recompute_metrics(self):
        for row in self.file_rows:
            row["metric"] = self.current_metric(row)
        for row in self.lang_rows:
            row["metric"] = self.current_metric(row)
            row["share"] = round(row["metric"] * 100.0 / row["total"], 1) if row["total"] else 0.0
        self.lang_rows.sort(key=lambda r: r["metric"], reverse=True)

    # ==================== 排除列表 ====================
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

    def fill_git_ignored(self, quiet=False):
        """把 git 实际忽略掉的目录填进排除列表（git 扫描到的自动加进来）。

        多目标时对**每个目录目标**各查一次并合并去重 —— 不同目标可能属于不同仓库。
        """
        roots = [t["path"] for t in self.current_targets() if t["kind"] == "dir"]
        repos = [r for r in roots if ignore_rules.is_git_repo(r)]
        if not repos:
            if not quiet:
                messagebox.showinfo("提示", "扫描目标里没有 git 仓库目录，无法读取忽略项")
            return
        existing = set(self.exclude_entries())
        added = 0
        total = 0
        for root in repos:
            dirs = ignore_rules.git_ignored_dirs(root)
            total += len(dirs)
            for rel in dirs:
                if rel not in existing:
                    self.list_excludes.insert(tk.END, rel)
                    existing.add(rel)
                    added += 1
        if not quiet:
            self.set_status(f"已填入 {added} 个 git 忽略目录"
                            f"（{len(repos)} 个仓库共 {total} 个）")

    # ==================== 统计流程 ====================
    def start_count(self):
        if self.running:
            return
        targets = self.current_targets()
        if not targets:
            if self.target_entries():
                messagebox.showerror("错误", "列表里的目标都不存在了，请重新添加")
            else:
                messagebox.showerror(
                    "错误",
                    "请先添加扫描目标（目录或文件）。\n\n"
                    "如果希望每次启动都自动填好默认目录，"
                    "可以勾选「自动填入默认目标」。")
            return

        engine = self.engine_ids[self.combo_engine.current()]
        label, available, note = self.engine_specs[engine]
        if not available:
            messagebox.showerror("引擎不可用", f"{label}：{note}")
            return
        if loc_engine.is_external(engine) and len(targets) > 1:
            messagebox.showerror(
                "引擎不支持多目标",
                f"{label} 一次只能扫一个目标，当前有 {len(targets)} 个。\n"
                "请改用内置引擎，或把目标减到一个。")
            return

        # 只在开着「记住设置」时才写盘；关闭状态下点统计不会产生任何文件
        if self.var_remember.get():
            self.save_conf()
        self.file_rows = []
        self.lang_rows = []
        self.fallback_count = 0
        self.failed = []
        self.enum_result = None
        self.clear_table()

        if loc_engine.is_external(engine):
            self.run_external_engine(engine, targets[0]["path"])
            return

        # 枚举：每个目录目标各自判 git / walk（一 git 一非 git 的混合要各自正确）
        try:
            enum = ignore_rules.enumerate_targets(
                targets,
                excludes=self.exclude_entries(),
                extensions=self.parse_extensions(),
                tracked_only=self.var_tracked.get(),
            )
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return

        self.enum_result = enum
        # 枚举阶段就读不了的文件（被占用/无权限）也进失败清单，可以一起重试
        self.failed = list(enum.failed)
        if not enum.files:
            self.set_status("没有需要统计的文件（检查扫描目标、排除列表与后缀筛选）")
            self.update_summary()
            self.update_retry_button()
            return

        self.set_status(f"统计中... 0/{len(enum.files)}")
        self.set_progress(0, len(enum.files))
        self.count_started = time.perf_counter()
        self.start_chunked(enum.files, self.count_one, chunk=40,
                           on_tick=self.on_count_tick, on_done=self.on_count_done,
                           on_item_error=self.on_item_error)

    def parse_extensions(self):
        raw = self.var_ext.get().strip()
        if not raw:
            return None
        return [e.strip() for e in raw.replace("，", ",").split(",") if e.strip()]

    def count_one(self, path):
        """统计一个文件。读不了（被占用/无权限）就记进失败清单，不让它拖垮整批。"""
        lexical = self.var_lexical.get()
        try:
            row = loc_engine.count_file(path, lexical)
        except loc_engine.ReadError as exc:
            self.record_failure(path, exc.reason, exc.detail)
            return
        except loc_engine.EngineError:
            # 词法模式不可用才回退（ReadError 已在上面拦掉了，不会拿被锁文件重试）
            try:
                row = loc_engine.count_file_light(path)
            except loc_engine.ReadError as exc:
                self.record_failure(path, exc.reason, exc.detail)
                return
            self.fallback_count += 1
        self.file_rows.append(row)

    def count_one_checked(self, path):
        """重试用：先重新探一遍（被锁的二进制文件不能当文本读进来），再统计。"""
        ok, reason = ignore_rules.probe_file(path)
        if not ok:
            if reason in ignore_rules.RETRYABLE_REASONS:
                self.record_failure(path, reason)
            return
        self.count_one(path)

    def record_failure(self, path, reason, detail=""):
        self.failed.append((path, reason, detail))

    def on_item_error(self, item, exc):
        """分片执行里单条抛异常（兜底）：记一笔，不让界面卡死。"""
        self.record_failure(str(item), "统计出错", f"{type(exc).__name__}: {exc}")

    def on_count_tick(self, index, total):
        self.set_progress(index)
        if index < total:
            self.set_status(f"统计中... {index}/{total}")

    def on_count_done(self):
        elapsed = time.perf_counter() - self.count_started
        self.after_finish(elapsed)
        total = sum(r["total"] for r in self.file_rows)
        parts = [f"完成：{len(self.file_rows)} 个文件、{total} 行，耗时 {elapsed:.2f} 秒"]
        if self.enum_result is not None:
            parts.append(f"（{self.enum_result.mode_summary()}）")
        if self.failed:
            parts.append(f"有 {len(self.failed)} 个文件读不了，可点「重试失败项」")
        self.set_status("".join(parts))
        self.update_retry_button()

    def update_retry_button(self):
        """重试按钮按需显示：没有读不了的文件就不占位置。"""
        if not hasattr(self, "btn_retry"):
            return
        if self.failed:
            self.btn_retry.configure(text=f"重试失败项({len(self.failed)})")
            if not self.btn_retry.winfo_manager():
                self.btn_retry.pack(side=tk.LEFT, padx=(8, 0))
        elif self.btn_retry.winfo_manager():
            self.btn_retry.pack_forget()

    def retry_failed(self):
        """只重跑失败的那几个文件。"""
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
        self.count_started = time.perf_counter()
        self.start_chunked(pending, self.count_one_checked, chunk=20,
                           on_tick=self.on_count_tick, on_done=self.on_retry_done,
                           on_item_error=self.on_item_error)

    def on_retry_done(self):
        ok = len(self.failed)
        self.after_finish(time.perf_counter() - self.count_started)
        self.update_retry_button()
        if ok:
            self.set_status(f"重试后仍有 {ok} 个文件读不了（可能还被占用）")
        else:
            self.set_status("重试完成，失败项已全部统计进去")

    def run_external_engine(self, engine, root):
        self.set_status(f"正在调用外部引擎 {engine}...（大目录可能较慢）")
        self.update_idletasks()
        try:
            result = loc_engine.count_external(engine, root)
        except loc_engine.EngineError as exc:
            messagebox.showerror("外部引擎失败", f"{exc}\n\n已回退为内置引擎重新统计。")
            self.start_count()
            return
        self.absorb_result(result)
        self.set_status(f"完成：{result['note']}")

    def absorb_result(self, result):
        """把引擎结果装进表格数据（外部引擎只支持单目标）。"""
        targets = self.current_targets()
        root = os.path.abspath(targets[0]["path"]) if targets else os.getcwd()
        label = ignore_rules.target_label(root)
        self.file_rows = []
        for row in result["files"]:
            item = dict(row)
            item["rel"] = self.relative(item["path"], root)
            item["origin"] = label
            self.file_rows.append(item)
        self.lang_rows = loc_engine.language_rows(result["by_language"])
        self.recompute_metrics()
        self.switch_view(self.view_mode, refresh=False)
        self.refresh_table()
        self.set_progress(1, 1)
        self.update_summary(result)

    def after_finish(self, elapsed=None):
        if self.enum_result is None:
            return
        summary, by_language = loc_engine.summarize(self.file_rows)
        enum = self.enum_result
        for row in self.file_rows:
            key = os.path.normcase(row["path"])
            # 相对路径按"该文件所属的目标"换算：多目标时不同目标各相对各的
            base = enum.file_roots.get(key) or enum.root or os.path.dirname(row["path"])
            row["rel"] = self.relative(row["path"], base)
            row["origin"] = enum.origins.get(key, "")
        self.lang_rows = loc_engine.language_rows(by_language)
        self.recompute_metrics()
        self.switch_view(self.view_mode, refresh=False)
        self.refresh_table()
        self.set_progress(1, 1)
        self.update_summary({
            "engine": "builtin_lexical" if self.var_lexical.get() else "builtin",
            "summary": summary,
            "elapsed": elapsed,
            "note": enum.note,
        })

    @staticmethod
    def relative(path, root):
        try:
            return os.path.relpath(path, root)
        except ValueError:
            return path

    def stop_count(self):
        if not self.stop_chunked():
            self.set_status("当前没有正在进行的统计")
            return
        self.after_finish()
        self.set_status(f"已停止：已统计 {len(self.file_rows)} 个文件"
                        + (f"，{self.fallback_count} 个回退轻量模式" if self.fallback_count else ""))

    def update_summary(self, result=None):
        """汇总只放"统计结果"本身。

        枚举方式/引擎/耗时这些诊断信息都挪到状态栏的完成提示里（耗时与文件数
        在那儿本来就重复、引擎在下拉框里也看得见），避免这一行又长又占两行。
        """
        if not self.file_rows:
            self.var_summary.set("尚未统计")
            return
        total = sum(r["total"] for r in self.file_rows)
        blank = sum(r["blank"] for r in self.file_rows)
        comment = sum(r["comment"] for r in self.file_rows)
        metric = sum(r["metric"] for r in self.file_rows)
        parts = [f"文件 {len(self.file_rows)}", f"总行 {total}",
                 f"空行 {blank}", f"注释 {comment}", f"有效代码 {metric}"]
        if self.fallback_count:
            parts.append(f"{self.fallback_count} 个文件回退轻量模式")
        # 跳过统计只在真的有跳过时才出现 —— 它是"有文件被排除"的信任信号
        if self.enum_result is not None and self.enum_result.skipped:
            parts.append("跳过 " + self.enum_result.skip_summary())
        skip = []
        if self.var_skip_blank.get():
            skip.append("空行")
        if self.var_skip_comment.get():
            skip.append("注释行")
        parts.append("口径 总行数" + ("".join(f" - {s}" for s in skip) if skip else "（不剔除）"))
        self.var_summary.set(" · ".join(parts))

    # ==================== 选中行操作 ====================
    def open_selected_file(self):
        row = self.selected_row()
        if row is None or "path" not in row:
            self.set_status("请先选中一行文件记录（按语言视图不支持打开文件）")
            return
        path = row["path"]
        if not os.path.isfile(path):
            messagebox.showerror("错误", f"文件不存在：{path}")
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
            self.set_status(f"已打开：{path}")
        except Exception as exc:
            messagebox.showerror("错误", f"打开失败：{exc}")

    def open_selected_dir(self):
        row = self.selected_row()
        if row is None or "path" not in row:
            self.set_status("请先选中一行文件记录")
            return
        folder = os.path.dirname(row["path"])
        try:
            if hasattr(os, "startfile"):
                os.startfile(folder)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
            self.set_status(f"已打开目录：{folder}")
        except Exception as exc:
            messagebox.showerror("错误", f"打开目录失败：{exc}")

    def copy_selected_path(self):
        row = self.selected_row()
        if row is None or "path" not in row:
            self.set_status("请先选中一行文件记录")
            return
        self.clipboard_clear()
        self.clipboard_append(row["path"])
        self.set_status(f"已复制路径：{row['path']}")

    # ==================== 配置与导出 ====================
    def current_conf(self):
        """把界面上的选择收集成一份配置字典。"""
        return {
            "remember": bool(self.var_remember.get()),
            "targets": self.current_targets(),
            "engine": self.engine_ids[self.combo_engine.current()],
            "extensions": self.var_ext.get().strip(),
            "excludes": self.exclude_entries(),
            "lexical": self.var_lexical.get(),
            "skip_blank": self.var_skip_blank.get(),
            "skip_comment": self.var_skip_comment.get(),
            "tracked_only": self.var_tracked.get(),
            "view_mode": self.view_mode,
        }

    def save_conf(self):
        """写配置，返回是否成功（失败要在界面上说出来，不能静默）。"""
        return settings.save(self.current_conf())

    def on_remember_changed(self):
        """切换「记住设置」。

        打开：立刻把当前界面写进记录（不用等点开始统计）。
        关闭：只把标记改成 false，**保留记录里的其他值**，也不删文件 ——
              想彻底清掉请点「清除记录」。这样"关掉"这个状态本身能被记住，
              下次启动不会又变回打开。
        """
        if self.var_remember.get():
            if self.save_conf():
                self.set_status(f"已开启记忆，设置已保存到 {settings.SETTINGS_PATH}")
            else:
                self.set_status(f"保存失败：{settings.SETTINGS_PATH} 无法写入")
                return
        else:
            if not settings.set_remember(False):
                self.set_status(f"保存失败：{settings.SETTINGS_PATH} 无法写入")
                return
            if settings.exists():
                self.set_status("已关闭记忆，不再读写设置；如需彻底清除记录请点「清除记录」")
            else:
                self.set_status("已关闭记忆，不再读写设置")

    def on_autofill_changed(self):
        """切换「自动填入默认目标」。

        这个开关的状态存在 prefs.json（跟 settings.json 分开），并且**独立于
        「记住设置」**：不管有没有开记忆，切换它都会立刻写自己的那份偏好文件。
        """
        if not settings.set_pref("autofill_default_target", self.var_autofill.get()):
            self.set_status(f"保存失败：{settings.PREFS_PATH} 无法写入")
            return
        if self.var_autofill.get():
            self.set_status(f"已开启：启动时会自动填入默认目标（{self.default_dir()}）")
        else:
            self.set_status("已关闭：启动时扫描目标列表留空，需要你自己添加")

    def clear_record(self):
        """清除记录：删掉 settings.json 与 prefs.json（目录空了连目录一起删），
        并把两个开关都关掉（回到默认状态）。"""
        removed = settings.clear()
        self.var_remember.set(False)
        self.var_autofill.set(False)
        if removed:
            what = "、".join(removed)
            if os.path.isdir(settings.STORE_DIR):
                self.set_status(f"已清除记录（{what}）；{settings.STORE_DIR} 里还有其他文件，目录保留")
            else:
                self.set_status(f"已清除记录（{what}），并删除了空目录 {settings.STORE_DIR}")
        else:
            self.set_status("没有可清除的记录")

    def export_result(self):
        if self.view_mode == "lang":
            headers = ["语言", "文件数", "总行数", "空行", "注释行", "有效代码行", "代码占比"]
            name = "代码统计_按语言.csv"
        else:
            headers = ["来源", "文件路径", "语言", "总行数", "空行", "注释行", "有效代码行"]
            name = "代码统计_按文件.csv"
        self.export_csv(headers, name)
