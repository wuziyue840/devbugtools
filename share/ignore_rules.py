#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""文件枚举与忽略规则。

两条枚举路径：
  1. git 模式（默认）：问 git 要文件清单（git ls-files），一次子进程就精确覆盖仓库里
     所有嵌套 .gitignore，完全不会走进构建产物目录。本仓库 29GB / 13.6 万文件里
     git 只跟踪约 1014 个文件，这是唯一能做到秒级的路径。
  2. 黑名单模式（兜底）：os.walk + 进入前剪枝。剪枝必须发生在 dirnames 上，
     事后再过滤已经晚了 —— 目录一旦被走进，几十万文件就已经枚举过了。

另外提供二进制嗅探与几道安全阀，避免把 zip/exe/png 当文本读出上百万行假代码。
"""

import errno
import os
import subprocess

# 进入前直接剪掉的目录名（小写比较），用于 walk 模式。
# 注意：这些名字是通用的构建产物/缓存目录名，只在 walk 模式下生效；
# git 模式以 git 的清单为准，不再叠加名字规则 —— 否则像本仓库里
# src/features/backup/ 这种"目录名恰好叫 backup"的源码会被误排除。
DEFAULT_BLACKLIST = (
    # 体积/文件数最大的几个（本仓库 target=26GB、node_modules≈6.4万文件、txt≈4.2万文件）
    "target", "node_modules", "txt",
    # 版本控制与产物
    ".git", "dist", "build", "out", "bin", "obj",
    ".docusaurus", ".starweb-build", ".next", ".nuxt",
    # 缓存与虚拟环境
    "__pycache__", ".venv", "venv", "env", ".tox", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".sass-cache",
    # 依赖与工具目录
    "vendor", "bower_components", "Pods", ".gradle", "coverage",
    ".idea", ".vscode", ".vs", ".history",
)

MAX_FILE_BYTES = 2 * 1024 * 1024      # 单文件上限，超过跳过
MAX_FILES = 50000                     # 文件总数上限
BINARY_SNIFF_BYTES = 8192             # 二进制嗅探读多少字节

# Windows 上不要让子进程弹出黑窗口
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# "读不了"的几种原因
READ_ERROR_REASONS = ("被占用", "无权限", "已不存在", "无法读取")
# 其中值得重试的：重试是给临时故障用的 —— "已不存在"重试也不会回来，
# 放进重试清单只会让「重试失败项」永远挂着消不掉。
RETRYABLE_REASONS = ("被占用", "无权限", "无法读取")


class FileList(object):
    """枚举结果：文件清单 + 跳过原因统计 + 失败清单。

    失败清单（failed）单独记路径，供界面的「重试失败项」只重跑这几个文件。
    """

    def __init__(self, mode, root=None):
        self.mode = mode          # "git" / "walk" / "mixed"
        self.root = root          # 单目标时的基础目录（兼容旧调用）
        self.roots = [root] if root else []
        self.modes = []           # 各个目录目标实际用的模式
        self.origins = {}         # normcase(abspath) -> 来源标签
        self.file_roots = {}      # normcase(abspath) -> 该文件所属目标（用于算相对路径）
        self.failed = []          # [(路径, 原因, 详情)]
        self.files = []
        self.skipped = {}         # 原因 -> 数量
        self.pruned_dirs = 0      # walk 模式下被剪掉的目录数
        self.truncated = False
        self.note = ""            # 给界面看的补充说明

    def skip(self, reason, count=1):
        self.skipped[reason] = self.skipped.get(reason, 0) + count

    def mark_failed(self, path, reason, detail=""):
        """记一条读不了的文件：既进失败清单（可重试），也进跳过统计。"""
        self.failed.append((path, reason, detail))
        self.skip(reason)

    def skip_summary(self):
        if not self.skipped:
            return ""
        parts = [f"{k} {v}" for k, v in sorted(self.skipped.items(), key=lambda kv: -kv[1])]
        return "、".join(parts)

    def mode_summary(self):
        """枚举方式的文字描述（只有 git / 只有 walk / 混合）。"""
        modes = set(self.modes) or {self.mode}
        if modes == {"git"}:
            return "git 清单"
        if modes == {"walk"}:
            return "黑名单遍历"
        if "git" in modes and "walk" in modes:
            return "git 清单+黑名单遍历"
        return "未枚举"

    def merge(self, other):
        """把另一个 FileList 并进来（跳过统计相加、上限取或、失败清单拼接）。"""
        self.files.extend(other.files)
        for reason, count in other.skipped.items():
            self.skip(reason, count)
        self.pruned_dirs += other.pruned_dirs
        self.truncated = self.truncated or other.truncated
        self.failed.extend(other.failed)
        if other.modes:
            self.modes.extend(other.modes)
        if other.note:
            self.note = f"{self.note}；{other.note}" if self.note else other.note


# ==================== git 路径 ====================
def run_git(args, cwd):
    """跑一条 git 命令，返回 (returncode, stdout_bytes)。失败不抛异常。"""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, b""
    return proc.returncode, proc.stdout


def find_git_root(path):
    """返回 path 所在 git 仓库的根目录，不是仓库则返回 None。"""
    if not os.path.isdir(path):
        path = os.path.dirname(path)
    code, out = run_git(["rev-parse", "--show-toplevel"], path)
    if code != 0:
        return None
    root = out.decode("utf-8", "ignore").strip()
    return root or None


def is_git_repo(path):
    return find_git_root(path) is not None


def git_files(root):
    """git 模式枚举：跟踪的文件 + 未被忽略的未跟踪文件。

    一次调用即精确尊重仓库内所有嵌套 .gitignore，不碰构建产物目录。
    """
    code, out = run_git(["ls-files", "-z", "-c", "-o", "--exclude-standard"], root)
    if code != 0:
        return None
    rels = [r for r in out.decode("utf-8", "ignore").split("\0") if r]
    return [os.path.normpath(os.path.join(root, r)) for r in rels]


def git_ignored_dirs(root):
    """git 认为被忽略的目录（最浅层），用于自动填充界面的排除列表。"""
    code, out = run_git(["ls-files", "-z", "-o", "-i", "--exclude-standard", "--directory"], root)
    if code != 0:
        return []
    entries = [e for e in out.decode("utf-8", "ignore").split("\0") if e]
    dirs = []
    for e in entries:
        rel = e.replace("/", os.sep).rstrip(os.sep)
        if not rel:
            continue
        # 只保留最浅层的：父目录已被收录就不必再列子目录
        if any(rel == d or rel.startswith(d + os.sep) for d in dirs):
            continue
        dirs.append(rel)
    return sorted(dirs)


# ==================== 排除规则 ====================
def normalize_excludes(entries, base=None):
    """把排除项分成"目录名"和"路径前缀"两类。

    含路径分隔符的条目按路径处理，相对路径以 base（扫描目录）为基准解析 ——
    界面上自动填入的 git 忽略项形如 StarTaskBook\\node_modules，是相对扫描目录的。
    """
    names = set()
    prefixes = []
    for entry in entries or ():
        entry = str(entry).strip().strip("/\\")
        if not entry:
            continue
        if "/" in entry or "\\" in entry:
            if not os.path.isabs(entry):
                entry = os.path.join(base or os.getcwd(), entry)
            prefixes.append(os.path.normcase(os.path.abspath(entry)))
        else:
            names.add(entry.lower())
    return names, prefixes


def under_prefix(path, prefixes):
    """path 是否落在某个排除路径前缀之下。"""
    if not prefixes:
        return False
    norm = os.path.normcase(os.path.abspath(path))
    for prefix in prefixes:
        if norm == prefix or norm.startswith(prefix + os.sep):
            return True
    return False


def _keep_dir(dirname, dirpath, names, prefixes):
    if dirname.lower() in names:
        return False
    if prefixes:
        full = os.path.normcase(os.path.join(dirpath, dirname))
        for p in prefixes:
            if full == p or full.startswith(p + os.sep):
                return False
    return True


def walk_files(root, exclude_names, exclude_prefixes, result=None):
    """黑名单模式枚举：进入前剪枝的 os.walk。"""
    for dirpath, dirnames, filenames in os.walk(root):
        keep = [d for d in dirnames if _keep_dir(d, dirpath, exclude_names, exclude_prefixes)]
        if result is not None and len(keep) != len(dirnames):
            result.pruned_dirs += len(dirnames) - len(keep)
        dirnames[:] = keep
        for name in filenames:
            yield os.path.normpath(os.path.join(dirpath, name))


# ==================== 可读性 / 二进制探测 ====================
def win32_open_error(path):
    """用 CreateFileW 问一次真实的 Win32 错误码，问不到就返回 None。

    为什么需要这个：Python 的 open() 走 CRT，失败时只带 errno（EACCES），
    `exc.winerror` 是 None —— 而 ERROR_SHARING_VIOLATION(32，被别的程序占用)
    与 ERROR_ACCESS_DENIED(5，权限不足) 对用户意味着完全不同的处置方式
    （去关掉占用它的程序 vs 去提权）。所以只在失败路径上额外问一次 Win32。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wt.HANDLE
        kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID,
                                        wt.DWORD, wt.DWORD, wt.HANDLE]
        # 只读打开、且不允许任何共享 —— 被占用时就会失败并给出真正的错误码
        handle = kernel32.CreateFileW(path, 0x80000000, 0, None, 3, 0, None)
        if handle in (None, 0) or handle == ctypes.c_void_p(-1).value:
            return ctypes.get_last_error() or None
        kernel32.CloseHandle(handle)
    except Exception:
        return None
    return None


def read_error_reason(exc, path=None):
    """把读写异常翻译成用户看得懂的原因：被占用 / 无权限 / 已不存在 / 无法读取。"""
    winerror = getattr(exc, "winerror", None)
    # CRT 抛的 PermissionError 没有 winerror，只能自己问一次 Win32
    if winerror is None and path and isinstance(exc, PermissionError):
        winerror = win32_open_error(path)
    if winerror == 32:
        return "被占用"          # ERROR_SHARING_VIOLATION
    if winerror == 5:
        return "无权限"          # ERROR_ACCESS_DENIED
    if winerror in (2, 3):
        return "已不存在"
    if isinstance(exc, FileNotFoundError):
        return "已不存在"
    if isinstance(exc, PermissionError):
        return "无权限"
    errno_value = getattr(exc, "errno", None)
    if errno_value in (errno.EBUSY, errno.EAGAIN, errno.ETXTBSY):
        return "被占用"
    if errno_value in (errno.EACCES, errno.EPERM):
        return "无权限"
    if errno_value == errno.ENOENT:
        return "已不存在"
    return "无法读取"


def probe_file(path, max_bytes=MAX_FILE_BYTES):
    """探测一个文件能不能统计，返回 (能否统计, 原因)。

    原因是空串表示可以统计；否则为 "文件过大" / "二进制" / "被占用" /
    "无权限" / "已不存在" / "无法读取" / "不是文件"。

    注意：打不开的文件以前被一律当成"二进制"，于是一个被别的程序占用的纯文本
    会被显示成"跳过 二进制"，完全误导。现在按系统错误分开归类。
    """
    try:
        if os.path.isdir(path):
            return False, "不是文件"      # Windows 上 open 目录会报"拒绝访问"，别误导
        if os.path.getsize(path) > max_bytes:
            return False, "文件过大"
    except OSError as exc:
        return False, read_error_reason(exc, path)

    try:
        with open(path, "rb") as f:
            chunk = f.read(BINARY_SNIFF_BYTES)
    except OSError as exc:
        return False, read_error_reason(exc, path)

    if b"\x00" in chunk:
        return False, "二进制"
    return True, ""


# ==================== 统一入口 ====================
def enumerate_files(root, mode="git", excludes=None, extensions=None,
                    max_bytes=MAX_FILE_BYTES, max_files=MAX_FILES, tracked_only=False):
    """枚举要统计的文件。

    root         扫描目录
    mode         "git" 走 git 清单，"walk" 走黑名单剪枝遍历
    excludes     额外排除项（目录名或路径），与内置黑名单合并（仅 walk 模式）
    extensions   后缀白名单（小写，含点）；None/空表示不过滤
    tracked_only git 模式下是否只要已跟踪文件（忽略未跟踪的新文件）
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ValueError(f"目录不存在：{root}")

    # 用户排除项：两种模式都生效（git 忽略掉的目录会被界面填进这里，因此也受其约束）
    user_names, prefixes = normalize_excludes(excludes, base=root)
    # 内置黑名单只在 walk 模式生效：git 的清单本身已经是权威答案，
    # 再叠一层名字规则只会误伤"目录名恰好叫 build/bin/backup"的源码目录
    walk_names = set(user_names) | {d.lower() for d in DEFAULT_BLACKLIST}

    result = FileList(mode, root)

    files = None
    if mode == "git":
        args = ["ls-files", "-z", "-c"] + ([] if tracked_only else ["-o", "--exclude-standard"])
        code, out = run_git(args, root)
        if code == 0:
            rels = [r for r in out.decode("utf-8", "ignore").split("\0") if r]
            files = [os.path.normpath(os.path.join(root, r)) for r in rels]
        else:
            result.note = "git 枚举失败，已降级为黑名单遍历"
            result.mode = "walk"

    if files is None:
        files = list(walk_files(root, walk_names, prefixes, result))

    # git 模式下按用户排除项过一遍（目录名匹配 + 排除路径前缀匹配）
    if result.mode == "git" and (user_names or prefixes):
        kept = []
        for path in files:
            parts = os.path.relpath(path, root).split(os.sep)[:-1]
            if any(p.lower() in user_names for p in parts) or under_prefix(path, prefixes):
                result.skip("被排除目录")
                continue
            kept.append(path)
        files = kept

    if len(files) > max_files:
        result.truncated = True
        result.skip(f"超出 {max_files} 上限", len(files) - max_files)
        files = sorted(files)[:max_files]

    # 后缀筛选
    if extensions:
        wanted = {e.lower() if e.startswith(".") else "." + e.lower() for e in extensions}
        kept = []
        for path in files:
            if os.path.splitext(path)[1].lower() in wanted:
                kept.append(path)
            else:
                result.skip("后缀不符")
        files = kept

    # 体积与可读性检查（放在最后，避免对已被筛掉的文件做 IO）
    kept = []
    for path in files:
        ok, reason = probe_file(path, max_bytes)
        if not ok:
            if reason in RETRYABLE_REASONS:
                result.mark_failed(path, reason)   # 进失败清单，可重试
            else:
                result.skip(reason)                # 含"已不存在"：只报数，不提供重试
            continue
        kept.append(path)
    result.files = kept
    result.roots = [root]
    result.modes = [result.mode]

    # 记下来源标签（单目标时就是目录名），供表格的「来源」列使用
    label = target_label(root)
    for path in result.files:
        key = os.path.normcase(path)
        result.origins[key] = label
        result.file_roots[key] = root

    return result


# ==================== 多目标 ====================
def target_label(path):
    """目标的默认来源标签：目录/文件名。"""
    return os.path.basename(os.path.normpath(path)) or os.path.abspath(path)


def unique_labels(targets):
    """给每个目标算一个唯一标签：默认取 basename，重名的目标一律改用完整路径。"""
    counts = {}
    for target in targets:
        base = target_label(target["path"]).lower()
        counts[base] = counts.get(base, 0) + 1
    labels = {}
    for target in targets:
        path = os.path.abspath(target["path"])
        base = target_label(path)
        labels[os.path.normcase(path)] = base if counts[base.lower()] == 1 else path
    return labels


def normalize_targets(paths):
    """把一串路径（目录或文件）转成 targets 结构，顺带去重与判类型。"""
    targets = []
    seen = set()
    for raw in paths or ():
        path = os.path.abspath(str(raw).strip().strip('"'))
        if not path or not os.path.exists(path):
            continue
        kind = "dir" if os.path.isdir(path) else "file"
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        targets.append({"path": path, "kind": kind})
    return targets


def enumerate_targets(targets, excludes=None, extensions=None,
                      max_bytes=MAX_FILE_BYTES, max_files=MAX_FILES, tracked_only=False):
    """枚举多个目标（目录或单文件，可混合）。

    targets: [{"path": str, "kind": "dir"|"file"}, ...]

    与单目录版本的差别：
      - 每个目录目标各自判 git / walk（一个 git 目录 + 一个非 git 目录要各自正确）
      - 排除项里形如 StarTaskBook\\node_modules 的相对路径**只对对应 root 成立**，
        所以按 root 分别解析基准
      - 显式添加的单文件不受后缀筛选与排除列表约束（你点名要统计它），
        但仍走体积上限、二进制嗅探、占用探测
      - max_files 是**全局**预算（单目录版本是按 root 各算，多目标会放大总量）
      - 按规范化绝对路径去重（目录目标与其内部的文件目标会重复）
    """
    result = FileList("mixed")
    labels = unique_labels(targets)
    seen = set()

    for target in targets:
        raw = os.path.abspath(target["path"])
        kind = target.get("kind") or ("dir" if os.path.isdir(raw) else "file")
        label = labels.get(os.path.normcase(raw), target_label(raw))
        result.roots.append(raw)

        if kind == "file":
            if not os.path.isfile(raw):
                result.skip("已不存在")
                continue
            ok, reason = probe_file(raw, max_bytes)
            if not ok:
                if reason in RETRYABLE_REASONS:
                    result.mark_failed(raw, reason)
                else:
                    result.skip(reason)
                continue
            key = os.path.normcase(raw)
            if key in seen:
                continue
            seen.add(key)
            result.files.append(raw)
            result.origins[key] = label
            result.file_roots[key] = os.path.dirname(raw)   # 单文件相对父目录，显示成文件名
            continue

        if not os.path.isdir(raw):
            result.skip("已不存在")
            continue

        sub = enumerate_files(
            raw,
            mode="git" if is_git_repo(raw) else "walk",
            excludes=excludes,
            extensions=extensions,
            max_bytes=max_bytes,
            max_files=float("inf"),      # 单目录不截断，留给下面的全局预算统一处理
            tracked_only=tracked_only,
        )
        for path in sub.files:
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            result.files.append(path)
            result.origins[key] = label
            result.file_roots[key] = sub.file_roots.get(key, raw)
        for reason_name, count in sub.skipped.items():
            result.skip(reason_name, count)
        result.pruned_dirs += sub.pruned_dirs
        result.truncated = result.truncated or sub.truncated
        result.failed.extend(sub.failed)
        if sub.modes:
            result.modes.extend(sub.modes)
        if sub.note:
            result.note = f"{result.note}；{sub.note}" if result.note else sub.note

    # 全局上限
    if len(result.files) > max_files:
        result.truncated = True
        result.skip(f"超出 {max_files} 上限", len(result.files) - max_files)
        result.files = sorted(result.files)[:max_files]

    # 整根目录都没了的情况也给个汇总说明
    if not result.files and not result.failed and not result.skipped:
        result.note = result.note or "目标里没有可统计的文件"

    return result
