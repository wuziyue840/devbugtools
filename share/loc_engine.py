#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""代码行数统计引擎。

内置引擎（默认，离线可用）：
  - 轻量模式：按 share.loc_langs 的注释语法表逐行判定，快。
  - 词法精确模式：用 Pygments 的词法分析器判定 Token.Comment，
    能正确区分"字符串里的 # 或 //"，但明显更慢（约 1 万行/秒），故为可选项。
    Pygments 缺失时自动回退轻量模式。

外部引擎（可选，需要自行安装）：scc / tokei / cloc。
它们只能以子进程方式调用并解析 JSON，无法嵌进界面；且不认我们的排除列表与后缀筛选。
注意：这三个工具本机均未安装，解析逻辑按各自官方 JSON 结构编写，
      但未经过真机验证，因此解析失败时会明确报错并让界面回退到内置引擎。

统一结果结构：
  {"engine": str, "files": [row...], "summary": {...}, "by_language": {...},
   "elapsed": float, "note": str}
  row = {"path", "language", "total", "blank", "comment", "code"}
"""

import json
import os
import shutil
import subprocess
import time

from . import loc_langs
from .ignore_rules import read_error_reason

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXTERNAL_TIMEOUT = 300

ENGINE_LABELS = {
    "builtin": "内置（快）",
    "builtin_lexical": "内置·词法精确（慢）",
    "scc": "scc（外部）",
    "tokei": "tokei（外部）",
    "cloc": "cloc（外部）",
}


class EngineError(Exception):
    """引擎层面的问题：外部引擎不可用、输出无法解析、词法模式不可用。"""


class ReadError(Exception):
    """这个文件本身读不了（被占用 / 无权限 / 已不存在）。

    必须与 EngineError 分开：EngineError 会触发"词法回退到轻量"，
    而回退会重新打开同一个文件 —— 对一个被锁的文件重试只会再失败一次，
    还把一个可处理的错误变成未捕获的。
    """

    def __init__(self, path, reason, detail=""):
        super().__init__(detail or f"{reason}：{path}")
        self.path = path
        self.reason = reason
        self.detail = detail


# ==================== 内置引擎 ====================
def count_file_light(path):
    """轻量逐行统计。行首即注释符才算注释行，行尾注释算代码行（同 cloc 口径）。"""
    lang, line_prefixes, block_pairs = loc_langs.get_spec(path)
    total = blank = comment = code = 0
    in_block = None      # 当前所处的块注释结束标记

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                total += 1
                s = line.strip()
                if not s:
                    blank += 1
                    continue
                if in_block is not None:
                    comment += 1
                    if in_block in s:
                        in_block = None
                    continue
                opened = False
                for start, end in block_pairs:
                    if s.startswith(start):
                        comment += 1
                        if end not in s[len(start):]:
                            in_block = end
                        opened = True
                        break
                if opened:
                    continue
                if any(s.startswith(p) for p in line_prefixes):
                    comment += 1
                    continue
                code += 1
    except OSError as exc:
        # 读不了就如实说是读不了 —— 以前这里没有 try，异常会一路漏到界面把统计卡死
        raise ReadError(path, read_error_reason(exc, path), str(exc))

    return {"path": path, "language": lang, "total": total,
            "blank": blank, "comment": comment, "code": code}


def pygments_available():
    try:
        import pygments  # noqa: F401
        return True
    except ImportError:
        return False


def count_file_lexical(path):
    """词法级统计：按每行是否含 Comment token 判定，能识别字符串内的注释符。

    Pygments 不可用或无对应 lexer 时抛 EngineError，由调用方回退轻量模式。
    """
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_for_filename
        from pygments.token import Comment, Whitespace
        from pygments.util import ClassNotFound
    except ImportError:
        raise EngineError("未安装 Pygments，无法使用词法精确模式")

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError as exc:
        # 抛 ReadError 而不是 EngineError：调用方看到 ReadError 就知道
        # "这个文件读不了"，不会再去拿同一个文件做词法回退重试
        raise ReadError(path, read_error_reason(exc, path), str(exc))

    try:
        lexer = get_lexer_for_filename(path, text)
    except ClassNotFound:
        # 没有对应词法器就退回轻量逻辑，保证不中断整批统计
        return count_file_light(path)

    lines = text.splitlines()
    n = len(lines)
    has_text = [False] * n
    has_comment = [False] * n
    has_code = [False] * n

    lineno = 0
    for tok_type, value in lex(text, lexer):
        parts = value.split("\n")
        is_comment = tok_type in Comment
        is_space = tok_type in Whitespace
        for offset, part in enumerate(parts):
            idx = lineno + offset
            if idx < n and part.strip():
                has_text[idx] = True
                if is_comment:
                    has_comment[idx] = True
                elif not is_space:
                    has_code[idx] = True
        lineno += len(parts) - 1

    blank = comment = code = 0
    for i in range(n):
        if not has_text[i]:
            blank += 1
        elif has_comment[i] and not has_code[i]:
            comment += 1
        else:
            code += 1

    return {"path": path, "language": loc_langs.language_of(path), "total": n,
            "blank": blank, "comment": comment, "code": code}


# 词法模式只对这些"有专门词法器的编程语言"生效。
# 实测反例：Pygments 的 Markdown 词法器不认 HTML 注释（<!-- -->），
# Batch 词法器不认 "::" 注释 —— 这两类用内置表反而更准。所以词法模式
# 对这些后缀直接走轻量逻辑，保证词法模式不会在某些语言上倒退。
LEXICAL_PREFERRED = {
    ".py", ".pyi", ".pyw",
    ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs",
    ".vue", ".svelte", ".astro",
    ".rs", ".go", ".cs", ".java", ".kt", ".swift", ".scala", ".dart",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".m", ".mm",
    ".php", ".rb", ".pl", ".lua",
    ".sh", ".bash", ".zsh", ".ps1", ".psm1",
    ".sql", ".css", ".less", ".scss", ".styl",
    ".json", ".jsonc", ".json5", ".yaml", ".yml", ".toml", ".ini", ".proto",
}


def count_file(path, lexical=False):
    """统计单个文件。lexical=True 时对代码语言走词法，其余仍走轻量逻辑。"""
    if lexical and os.path.splitext(path)[1].lower() in LEXICAL_PREFERRED:
        return count_file_lexical(path)
    return count_file_light(path)


# ==================== 汇总 ====================
def summarize(rows):
    """把逐文件结果汇总成总量与按语言分组。"""
    summary = {"files": len(rows), "total": 0, "blank": 0, "comment": 0, "code": 0}
    by_language = {}
    for row in rows:
        for key in ("total", "blank", "comment", "code"):
            summary[key] += row[key]
        lang = row["language"]
        entry = by_language.setdefault(
            lang, {"language": lang, "files": 0, "total": 0, "blank": 0, "comment": 0, "code": 0})
        entry["files"] += 1
        for key in ("total", "blank", "comment", "code"):
            entry[key] += row[key]
    return summary, by_language


def language_rows(by_language):
    """按有效代码行从多到少排好的语言汇总行，供表格直接使用。"""
    rows = list(by_language.values())
    for row in rows:
        row["share"] = round(row["code"] * 100.0 / row["total"], 1) if row["total"] else 0.0
    rows.sort(key=lambda r: r["code"], reverse=True)
    return rows


def count_files(files, lexical=False, progress=None):
    """一次性统计一批文件（供测试与非交互场景使用；界面走分片调用 count_file）。"""
    started = time.perf_counter()
    rows = []
    failed = []
    for index, path in enumerate(files):
        try:
            rows.append(count_file(path, lexical))
        except ReadError as exc:
            failed.append((path, exc.reason, exc.detail))   # 读不了就跳过，不让一个文件毁掉整批
        except EngineError:
            try:
                rows.append(count_file_light(path))
            except ReadError as exc:
                failed.append((path, exc.reason, exc.detail))
        if progress is not None:
            progress(index + 1, len(files))
    summary, by_language = summarize(rows)
    return {
        "engine": "builtin_lexical" if lexical else "builtin",
        "files": rows,
        "summary": summary,
        "by_language": by_language,
        "failed": failed,
        "elapsed": time.perf_counter() - started,
        "note": "",
    }


# ==================== 外部引擎 ====================
def detect_external():
    """探测 PATH 上可用的外部引擎，返回 {引擎id: 可执行文件路径}。"""
    found = {}
    for name in ("scc", "tokei", "cloc"):
        exe = shutil.which(name)
        if exe:
            found[name] = exe
    return found


def available_engines():
    """返回 {引擎id: (显示名, 是否可用, 说明)}，供界面下拉框使用。"""
    external = detect_external()
    lexical_ok = pygments_available()
    engines = {
        "builtin": (ENGINE_LABELS["builtin"], True, "标准库逐行统计，离线可用"),
        "builtin_lexical": (
            ENGINE_LABELS["builtin_lexical"], lexical_ok,
            "基于 Pygments 词法分析，能识别字符串内的注释符" if lexical_ok
            else "需要 Pygments（未安装）"),
    }
    for name in ("scc", "tokei", "cloc"):
        engines[name] = (
            ENGINE_LABELS[name], name in external,
            external.get(name) or "未安装（不在 PATH 上）")
    return engines


def _run_external(cmd, root):
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True,
                              timeout=EXTERNAL_TIMEOUT, creationflags=_NO_WINDOW)
    except FileNotFoundError:
        raise EngineError(f"找不到可执行文件：{cmd[0]}")
    except subprocess.TimeoutExpired:
        raise EngineError(f"执行超时（>{EXTERNAL_TIMEOUT}s）：{cmd[0]}")
    except OSError as exc:
        raise EngineError(f"执行失败：{exc}")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "ignore").strip()[:300]
        raise EngineError(f"{os.path.basename(cmd[0])} 退出码 {proc.returncode}：{err}")
    try:
        return json.loads(proc.stdout.decode("utf-8", "ignore"))
    except ValueError as exc:
        raise EngineError(f"输出不是合法 JSON：{exc}")


def _pick(mapping, *names):
    """按候选键名取值（忽略大小写），找不到返回 None。"""
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _external_result(engine, rows, elapsed, note=""):
    summary, by_language = summarize(rows)
    return {"engine": engine, "files": rows, "summary": summary,
            "by_language": by_language, "elapsed": elapsed, "note": note}


def count_with_scc(root, exe):
    """scc --format json --by-file：顶层是数组，逐文件字段 Lines/Code/Comment/Blank。"""
    started = time.perf_counter()
    data = _run_external([exe, "--format", "json", "--by-file", root], root)
    if not isinstance(data, list):
        raise EngineError("scc 输出不是数组，无法解析")
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        location = _pick(item, "Location", "FileName", "Name", "Path")
        if not location:
            continue
        path = location if os.path.isabs(location) else os.path.join(root, location)
        code = _to_int(_pick(item, "Code"))
        comment = _to_int(_pick(item, "Comment"))
        blank = _to_int(_pick(item, "Blank"))
        total = _to_int(_pick(item, "Lines")) or (code + comment + blank)
        rows.append({"path": os.path.normpath(path),
                     "language": _pick(item, "Language") or loc_langs.language_of(path),
                     "total": total, "blank": blank, "comment": comment, "code": code})
    if not rows:
        raise EngineError("scc 未返回任何逐文件记录")
    return _external_result("scc", rows, time.perf_counter() - started,
                            "外部引擎：不适用本页的排除列表与后缀筛选")


def count_with_tokei(root, exe):
    """tokei --output json：顶层是语言 map，reports[].name + stats{blanks,code,comments}。"""
    started = time.perf_counter()
    data = _run_external([exe, "--output", "json", root], root)
    if not isinstance(data, dict):
        raise EngineError("tokei 输出不是对象，无法解析")
    rows = []
    for lang_name, stats in data.items():
        if lang_name == "Total" or not isinstance(stats, dict):
            continue
        for report in stats.get("reports", []) or []:
            if not isinstance(report, dict):
                continue
            name = report.get("name") or report.get("path")
            if not name:
                continue
            s = report.get("stats", report)
            code = _to_int(s.get("code"))
            comment = _to_int(s.get("comments", s.get("comment")))
            blank = _to_int(s.get("blanks", s.get("blank")))
            path = name if os.path.isabs(name) else os.path.join(root, name)
            rows.append({"path": os.path.normpath(path), "language": lang_name,
                         "total": code + comment + blank,
                         "blank": blank, "comment": comment, "code": code})
    if not rows:
        raise EngineError("tokei 未返回逐文件记录（需要 --output json 且包含 reports）")
    return _external_result("tokei", rows, time.perf_counter() - started,
                            "外部引擎：不适用本页的排除列表与后缀筛选")


def count_with_cloc(root, exe):
    """cloc --json --by-file：语言/文件键下取 code/blank/comment，注意值是字符串。"""
    started = time.perf_counter()
    data = _run_external([exe, "--json", "--by-file", "--vcs=git", root], root)
    if not isinstance(data, dict):
        raise EngineError("cloc 输出不是对象，无法解析")
    rows = []
    for key, value in data.items():
        if key in ("header", "SUM") or not isinstance(value, dict):
            continue
        if "code" not in {str(k).lower() for k in value.keys()}:
            continue
        code = _to_int(_pick(value, "code"))
        comment = _to_int(_pick(value, "comment"))
        blank = _to_int(_pick(value, "blank"))
        path = key if os.path.isabs(key) else os.path.join(root, key)
        rows.append({"path": os.path.normpath(path),
                     "language": _pick(value, "language") or loc_langs.language_of(path),
                     "total": code + comment + blank,
                     "blank": blank, "comment": comment, "code": code})
    if not rows:
        raise EngineError("cloc 未返回逐文件记录")
    return _external_result("cloc", rows, time.perf_counter() - started,
                            "外部引擎：不适用本页的排除列表与后缀筛选")


EXTERNAL_RUNNERS = {
    "scc": count_with_scc,
    "tokei": count_with_tokei,
    "cloc": count_with_cloc,
}


def count_external(engine, root):
    """调用外部引擎，返回统一结果；不可用时抛 EngineError。"""
    external = detect_external()
    if engine not in external:
        raise EngineError(f"{engine} 未安装或不在 PATH 上")
    return EXTERNAL_RUNNERS[engine](root, external[engine])


def is_external(engine):
    return engine in EXTERNAL_RUNNERS
