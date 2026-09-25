#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""端口进程查看：按端口范围或整机列出本机网络连接，并定位到对应进程。"""

import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import os

from share.ui_common import ToolTab


# 常见端口用途备注，用于表格的“备注”列
COMMON_PORTS = {
    20: "FTP-数据", 21: "FTP-控制", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 67: "DHCP-服务", 68: "DHCP-客户端", 69: "TFTP",
    80: "HTTP", 110: "POP3", 123: "NTP", 135: "RPC", 137: "NetBIOS-名称",
    138: "NetBIOS-数据报", 139: "NetBIOS-会话", 143: "IMAP", 161: "SNMP",
    162: "SNMP-Trap", 389: "LDAP", 443: "HTTPS", 445: "SMB", 465: "SMTPS",
    514: "Syslog", 587: "SMTP-提交", 636: "LDAPS", 873: "Rsync",
    993: "IMAPS", 995: "POP3S", 1080: "SOCKS", 1194: "OpenVPN",
    1433: "SQL Server", 1521: "Oracle", 1723: "PPTP", 2049: "NFS",
    2375: "Docker", 2376: "Docker-TLS", 3000: "Node/Web 开发",
    3306: "MySQL", 3389: "远程桌面", 5000: "Flask/开发", 5173: "Vite",
    5432: "PostgreSQL", 5601: "Kibana", 5672: "RabbitMQ", 5900: "VNC",
    5984: "CouchDB", 6379: "Redis", 7001: "WebLogic", 8000: "HTTP-备用",
    8080: "HTTP-代理", 8081: "HTTP-备用", 8443: "HTTPS-备用",
    8888: "Jupyter", 9000: "PHP-FPM", 9090: "Prometheus",
    9200: "Elasticsearch", 9300: "Elasticsearch-集群",
    11211: "Memcached", 27017: "MongoDB", 61616: "ActiveMQ",
}

PORT_HEADINGS = (
    ("proto", "协议", 55),
    ("family", "地址族", 70),
    ("local", "本地地址", 150),
    ("local_port", "本地端口", 80),
    ("remote", "远程地址", 175),
    ("status", "状态", 90),
    ("pid", "PID", 65),
    ("proc_name", "进程名", 160),
    ("tip", "备注", 130),
)

PORT_CSV_HEADERS = ["协议", "地址族", "本地地址", "本地端口", "远程地址",
                    "状态", "PID", "进程名", "备注"]


class PortScanTab(ToolTab):
    """端口进程查看标签页，自身即容器，塞进 Notebook 就能用。"""

    def __init__(self, master):
        super().__init__(
            master,
            initial_status="就绪：填入端口范围后点“范围查询”，或点“整机查询”列出全部连接",
        )
        self.build_ui()

    def build_ui(self):
        # ---------------- 扫描状态 ----------------
        self.var_listen_only = tk.BooleanVar()
        self.var_out_only = tk.BooleanVar(value=False)
        self.var_show_tip = tk.BooleanVar(value=True)
        # “只显示监听端口”与“仅向外连接”互斥
        self.var_listen_only.trace_add("write", self.on_listen_changed)
        self.var_out_only.trace_add("write", self.on_out_changed)

        self.scan_mode = None          # "range" 端口范围 / "all" 整机
        self.scan_total = 0            # 连接总数
        self.scan_matched = 0          # 命中条数
        self.scan_start = 1
        self.scan_end = 65535

        # ---------------- 第一行：查询条件 ----------------
        frame_ctrl = ttk.Frame(self)
        frame_ctrl.pack(fill=tk.X, padx=3, pady=(3, 3))

        ttk.Label(frame_ctrl, text="端口范围:").grid(row=0, column=0, sticky="w")
        self.entry_port_start = ttk.Entry(frame_ctrl, width=8)
        self.entry_port_start.grid(row=0, column=1, padx=3)
        self.entry_port_start.insert(0, "1")
        ttk.Label(frame_ctrl, text="-").grid(row=0, column=2)
        self.entry_port_end = ttk.Entry(frame_ctrl, width=8)
        self.entry_port_end.grid(row=0, column=3, padx=3)
        self.entry_port_end.insert(0, "65535")

        ttk.Label(frame_ctrl, text="关键字:").grid(row=0, column=4, padx=(12, 0))
        self.entry_filter = ttk.Entry(frame_ctrl, width=16)
        self.entry_filter.grid(row=0, column=5, padx=3)
        self.entry_filter.bind("<Return>", lambda event: self.apply_filter())

        self.btn_scan = ttk.Button(frame_ctrl, text="范围查询", width=9, command=self.scan_port_range)
        self.btn_scan.grid(row=0, column=6, padx=3)
        self.btn_scan_all = ttk.Button(frame_ctrl, text="整机查询", width=9, command=self.scan_all_local)
        self.btn_scan_all.grid(row=0, column=7, padx=3)
        self.btn_stop = ttk.Button(frame_ctrl, text="停止", width=7, command=self.stop_scan, state="disabled")
        self.btn_stop.grid(row=0, column=8, padx=3)

        # ---------------- 第二行：过滤与导出 ----------------
        frame_opt = ttk.Frame(self)
        frame_opt.pack(fill=tk.X, padx=3, pady=(0, 3))

        ttk.Checkbutton(frame_opt, text="只显示监听端口",
                        variable=self.var_listen_only).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(frame_opt, text="仅向外连接(本机发送)",
                        variable=self.var_out_only).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(frame_opt, text="显示端口备注", variable=self.var_show_tip,
                        command=self.refresh_table).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(frame_opt, text="清除筛选", width=9,
                   command=self.clear_filter).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(frame_opt, text="复制选中", width=9,
                   command=self.copy_selected).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(frame_opt, text="导出CSV", width=9,
                   command=lambda: self.export_csv(PORT_CSV_HEADERS, "端口连接.csv")
                   ).pack(side=tk.LEFT, padx=(0, 10))

        # ---------------- 表格 ----------------
        frame_table = ttk.Frame(self)
        frame_table.pack(fill=tk.BOTH, expand=True, padx=3, pady=(0, 3))
        self.make_table(frame_table, PORT_HEADINGS)

        # 右键菜单
        self.make_row_menu((
            ("复制该行", self.copy_selected),
            ("自适应列宽", self.autofit_columns),
            None,
            ("查看进程详情", self.show_process_detail),
            ("打开进程所在目录", self.open_process_dir),
            None,
            ("结束该进程", self.kill_process),
        ))

        # ---------------- 状态栏 ----------------
        self.make_status_bar(self)

    # ==================== 基类钩子 ====================
    def on_busy_changed(self, busy):
        state = "disabled" if busy else "normal"
        self.btn_scan.configure(state=state)
        self.btn_scan_all.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def on_row_activate(self, row):
        self.show_process_detail()

    def row_values(self, row):
        tip_on = self.var_show_tip.get()
        return (
            row["proto"],
            row["family"],
            row["local"],
            row["local_port"],
            row["remote"],
            row["status"],
            row["pid"] or "-",
            row["proc_name"],
            row["tip"] if tip_on else "",
        )

    # ==================== 过滤条件互斥 ====================
    def on_listen_changed(self, *args):
        if self.var_listen_only.get():
            self.var_out_only.set(False)

    def on_out_changed(self, *args):
        if self.var_out_only.get():
            self.var_listen_only.set(False)

    # ==================== 小工具 ====================
    @staticmethod
    def get_proc_name(pid):
        if not pid:
            return "-"
        try:
            return psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return "-"

    @staticmethod
    def port_tip(port):
        return COMMON_PORTS.get(port, "")

    @staticmethod
    def proto_name(conn):
        name = getattr(conn.type, "name", None) or str(conn.type)
        if "STREAM" in name:
            return "TCP"
        if "DGRAM" in name:
            return "UDP"
        return name

    @staticmethod
    def family_name(conn):
        name = getattr(conn.family, "name", None) or str(conn.family)
        return "IPv6" if "6" in name else "IPv4"

    # ==================== 扫描流程 ====================
    def start_scan(self, mode, start_port=None, end_port=None):
        if self.running:
            return
        try:
            conns = psutil.net_connections(kind="inet")
        except psutil.AccessDenied:
            messagebox.showerror("权限不足", "无法读取系统连接列表，请以管理员身份运行本工具。")
            return
        except Exception as exc:
            messagebox.showerror("错误", f"读取网络连接失败：{exc}")
            return

        self.scan_mode = mode
        self.scan_start = start_port if start_port is not None else 1
        self.scan_end = end_port if end_port is not None else 65535
        self.scan_total = len(conns)
        self.scan_matched = 0
        self.rows = []
        self.clear_table()

        self.set_progress(0, max(self.scan_total, 1))
        if self.scan_total == 0:
            self.set_status("未读取到任何连接记录")
            return

        self.set_status(f"扫描中... 0/{self.scan_total}")
        self.start_chunked(conns, self.handle_conn, chunk=80,
                           on_tick=self.on_scan_tick, on_done=self.on_scan_done)

    def handle_conn(self, conn):
        row = self.match_conn(conn, self.var_listen_only.get(), self.var_out_only.get())
        if row is not None:
            self.rows.append(row)
            self.scan_matched += 1

    def on_scan_tick(self, index, total):
        self.set_progress(index)
        if index < total:
            self.set_status(f"扫描中... {index}/{total}")

    def on_scan_done(self):
        self.refresh_table()
        self.set_status(f"完成：共 {self.scan_total} 条连接，命中 {self.scan_matched} 条，"
                        f"表格显示 {len(self.tree.get_children())} 条")

    def match_conn(self, conn, listen_only, out_only):
        """判断一条连接是否命中当前条件，命中则返回记录 dict，否则返回 None。"""
        if self.scan_mode == "range":
            if conn.laddr is None:
                return None
            if not (self.scan_start <= conn.laddr.port <= self.scan_end):
                return None

        if listen_only and conn.status != psutil.CONN_LISTEN:
            return None
        # Windows 下向外连接被拒绝时的 raddr 可能是空元组而非 None，两种都要排除
        raddr = conn.raddr if conn.raddr else None
        if out_only and raddr is None:
            return None

        laddr = conn.laddr
        pid = conn.pid or 0
        return {
            "proto": self.proto_name(conn),
            "family": self.family_name(conn),
            "local": f"{laddr.ip}:{laddr.port}" if laddr else "-",
            "local_port": laddr.port if laddr else -1,
            "remote": f"{raddr.ip}:{raddr.port}" if raddr else "-",
            "status": conn.status or "-",
            "pid": pid,
            "proc_name": self.get_proc_name(pid),
            "tip": self.port_tip(laddr.port) if laddr else "",
        }

    def stop_scan(self):
        if not self.stop_chunked():
            self.set_status("当前没有正在进行的扫描")
            return
        self.refresh_table()
        self.set_status(f"已停止：已检查 {self.processed}/{self.total_items} 条，"
                        f"命中 {self.scan_matched} 条")

    # ==================== 入口按钮 ====================
    def scan_port_range(self):
        try:
            start_p = int(self.entry_port_start.get().strip())
            end_p = int(self.entry_port_end.get().strip())
        except ValueError:
            messagebox.showerror("错误", "请输入数字端口")
            return
        if not (0 <= start_p <= 65535 and 0 <= end_p <= 65535):
            messagebox.showerror("错误", "端口需在 0 - 65535 之间")
            return
        if start_p > end_p:
            start_p, end_p = end_p, start_p
            self.entry_port_start.delete(0, tk.END)
            self.entry_port_start.insert(0, str(start_p))
            self.entry_port_end.delete(0, tk.END)
            self.entry_port_end.insert(0, str(end_p))
        self.start_scan("range", start_p, end_p)

    def scan_all_local(self):
        self.start_scan("all")

    # ==================== 选中行操作 ====================
    def show_process_detail(self):
        row = self.selected_row()
        if row is None:
            self.set_status("请先选择一行记录")
            return
        pid = row["pid"]
        info = [
            f"端口信息：{row['proto']} {row['local']} -> {row['remote']}  [{row['status']}]",
            f"PID：{pid or '-'}",
            f"进程名：{row['proc_name']}",
        ]
        if pid:
            try:
                proc = psutil.Process(pid)
                info.append(f"可执行文件：{proc.exe()}")
                info.append(f"工作目录：{proc.cwd()}")
                info.append(f"启动命令：{' '.join(proc.cmdline())}")
                info.append(f"运行用户：{proc.username()}")
                info.append(f"父进程 PID：{proc.ppid()}")
                info.append(f"内存占用：{proc.memory_info().rss / 1024 / 1024:.1f} MB")
                info.append(f"状态：{proc.status()}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
                info.append(f"（无法获取进程详情：{exc}）")

        win = tk.Toplevel(self)
        win.title(f"进程详情 - PID {pid or '-'}")
        win.geometry("620x320")
        win.transient(self.winfo_toplevel())
        text = tk.Text(win, wrap="word", padx=8, pady=8)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", "\n".join(info))
        text.configure(state="disabled")

    def open_process_dir(self):
        row = self.selected_row()
        if row is None:
            self.set_status("请先选择一行记录")
            return
        pid = row["pid"]
        if not pid:
            messagebox.showinfo("提示", "该连接没有对应的进程（可能是系统保留连接）")
            return
        try:
            exe = psutil.Process(pid).exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            messagebox.showerror("错误", "无法获取该进程的可执行文件路径")
            return
        folder = os.path.dirname(exe)
        try:
            if hasattr(os, "startfile"):
                os.startfile(folder)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
            self.set_status(f"已打开目录：{folder}")
        except Exception as exc:
            messagebox.showerror("错误", f"打开目录失败：{exc}")

    def kill_process(self):
        row = self.selected_row()
        if row is None:
            self.set_status("请先选择一行记录")
            return
        pid = row["pid"]
        if not pid:
            messagebox.showinfo("提示", "该连接没有对应的进程")
            return
        if pid == os.getpid():
            messagebox.showerror("错误", "不能结束本工具自身的进程")
            return
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            messagebox.showerror("错误", f"进程 {pid} 不存在或无法访问")
            return
        if not messagebox.askyesno("确认", f"确定要结束进程 {name} (PID {pid}) 吗？"):
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                if messagebox.askyesno("确认", f"进程 {name} 未在 3 秒内退出，是否强制结束？"):
                    proc.kill()
        except psutil.AccessDenied:
            messagebox.showerror("错误", "权限不足，请以管理员身份运行后重试")
            return
        except psutil.NoSuchProcess:
            pass
        except Exception as exc:
            messagebox.showerror("错误", f"结束进程失败：{exc}")
            return
        self.set_status(f"已请求结束进程 {name} (PID {pid})")
