#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""代码成分表与屎山指数的引擎：单遍扫描 + 成分汇总 + 指数评分。

三层数据来源，共用同一套评分公式：
  1. 内置启发式（默认，全语言可用）：每个文件**只打开一次**，一趟同时算出
     行成分（总/空/注释/代码）与全部健康指标（缩进、分支、TODO、重复行）。
     绝不为了健康指标再读第二遍文件 —— 这是"性能"的来源。
  2. 精确层（可选，需 pip install lizard）：函数级圈复杂度 / 最大嵌套 / 超长函数，
     把"分支泥潭""嵌套深渊"升级为真实指标，并解锁"函数臃肿"。
  3. 外部引擎（可选，scc / tokei）：沿用 share.loc_engine 的适配，失败即明确报错。

行成分口径与 share.loc_engine.count_file_light **完全一致**（同一个 loc_langs 注释
语法表、同样的"行首即注释符才算注释行、行尾注释算代码行"），所以本页的数字可以
和「代码行数统计」页逐语言交叉校验。
"""

import json
import os
import shutil
import subprocess
import time

from . import health_rules, health_texts
from . import loc_engine, loc_langs
from .ignore_rules import read_error_reason

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 引擎 id（页面下拉框与 settings 语义无关，只在本页内存里用）
ENGINE_LABELS = {
    "builtin": "内置启发式（快）",
    "builtin_precise": "内置 + 精确·lizard（慢）",
    "scc": "scc（外部）",
    "tokei": "tokei（外部·仅成分）",
}


# ==================== 单文件扫描（单遍 IO） ====================
def _indent_width(line):
    """行首空白折算成空格数（制表符按 health_rules.TAB_WIDTH 计）。"""
    width = 0
    for ch in line:
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += health_rules.TAB_WIDTH
        else:
            break
    return width


def _indent_unit(widths, steps):
    """每文件自适应缩进单位：取**上台阶幅度**里最常见的那个，夹到 2–8。

    为什么不用"最小正缩进"：实测本仓库的 Python 文件里混着对齐用的 2/5/9/19 空格
    （续行对齐），最小正缩进会取到 2，于是一个 47 空格的续行被算成 23 级 —— 荒谬。
    而"从上一行进入更深一层时增加了几个空格"是缩进单位最稳的观测：块进一级就是
    一个单位。只采集 1–8 的台阶，对齐线那种一次跳 30 格的天然被排除。
    """
    low, high = health_rules.INDENT_UNIT_RANGE
    unit = None
    if steps:
        counts = {}
        for step in steps:
            counts[step] = counts.get(step, 0) + 1
        # 出现最多者优先；并列取较小的那个（4 空格文件不会因为对齐线被判成 2）
        unit = max(counts.items(), key=lambda item: (item[1], -item[0]))[0]
    if not unit:
        positive = [w for w in widths if w > 0]
        unit = min(positive) if positive else health_rules.INDENT_UNIT_FALLBACK
    return max(low, min(high, unit))


def scan_file(path):
    """单遍扫描一个文件，同时产出「行成分」与「健康指标」。

    返回 dict：
      path, language,
      total, blank, comment, code,
      max_indent, avg_indent,     # 缩进级数（只对编程语言计，其余为 0）
      branch_hits,                # 分支关键字命中数（只统计代码行）
      todo_count,                 # TODO/FIXME/… 命中数
      dup_lines,                  # 归一化后重复出现的"像代码"的行数
      max_line_len

    读不了（被占用 / 无权限）抛 loc_engine.ReadError，由页面归入失败清单可重试。
    """
    language, line_prefixes, block_pairs = loc_langs.get_spec(path)
    patterns = health_rules.branch_patterns_for(language)
    # 嵌套与重复只对编程语言计：标记/数据文件的缩进是排版、重复行是数据本身
    count_nesting = health_rules.is_code_language(language)
    count_dup = language not in health_rules.DUP_EXCLUDED_LANGS

    total = blank = comment = code = 0
    branch_hits = todo_count = 0
    max_line_len = 0
    indent_widths = []
    indent_steps = []
    prev_width = 0
    seen = {}

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            in_block = None
            for line in f:
                total += 1
                if len(line) > max_line_len:
                    max_line_len = len(line)
                s = line.strip()

                if not s:
                    blank += 1
                    continue

                todo_count += health_rules.count_todos(s)

                # 归一化行供"复制粘贴"维度用；太短或不像代码的行不算
                if count_dup:
                    key = " ".join(s.split())
                    if (len(key) >= health_rules.DUP_MIN_LINE_CHARS
                            and any(ch.isalpha() for ch in key)):
                        seen[key] = seen.get(key, 0) + 1

                if count_nesting:
                    width = _indent_width(line)
                    indent_widths.append(width)
                    step = width - prev_width
                    if 0 < step <= health_rules.INDENT_STEP_MAX:
                        indent_steps.append(step)
                    prev_width = width

                # ---- 注释判定：与 loc_engine.count_file_light 逐条对齐 ----
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
                if patterns:
                    for pattern in patterns:
                        branch_hits += len(pattern.findall(s))
    except OSError as exc:
        raise loc_engine.ReadError(path, read_error_reason(exc, path), str(exc))

    unit = _indent_unit(indent_widths, indent_steps)
    levels = [w // unit for w in indent_widths]
    max_indent = max(levels) if levels else 0
    avg_indent = round(sum(levels) / len(levels), 1) if levels else 0.0
    dup_lines = sum(count for count in seen.values() if count > 1)

    return {
        "path": path,
        "language": language,
        "total": total,
        "blank": blank,
        "comment": comment,
        "code": code,
        "max_indent": max_indent,
        "avg_indent": avg_indent,
        "branch_hits": branch_hits,
        "todo_count": todo_count,
        "dup_lines": dup_lines,
        "max_line_len": max_line_len,
    }


# ==================== 成分表汇总（直接复用 loc_engine，不重复实现） ====================
def build_profile(rows):
    """把逐文件结果汇总成成分表：总量 + 按语言分组（均为 loc_engine 原口径）。"""
    return loc_engine.summarize(rows)


# ==================== 未识别扩展名（供"下一轮补表"用） ====================
UNKNOWN_EXT_LABEL = "(无扩展名)"


def unknown_extensions(rows, limit=10):
    """被当成「纯文本」、且确实不在已知表里的扩展名（含无扩展名），按文件数排序。

    返回 {"top": [(扩展名, 文件数), ...], "kinds": 种类数, "files": 文件总数}。

    这条提示的用途是"告诉我们下一轮该往 loc_langs 补什么"，所以必须把
    **"我们没认出来"** 与 **"本来就是纯文本"**（.txt / .log / .lock …）分开，
    否则每个项目都会报出一堆 .txt，提示就没人看了。
    """
    counts = {}
    for row in rows:
        if row.get("language") != loc_langs.PLAIN_TEXT_LANG:
            continue                      # 已识别的语言（含外部分类）不算未识别
        name = os.path.basename(row.get("path") or "").lower()
        if not name:
            continue
        ext = os.path.splitext(name)[1]
        if ext and ext in loc_langs.PLAIN_TEXT_EXT:
            continue                      # 本来就是纯文本，不是漏认
        if not ext and name in loc_langs.FILENAMES:
            continue                      # 特殊文件名表已覆盖
        key = ext or UNKNOWN_EXT_LABEL
        counts[key] = counts.get(key, 0) + 1

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "top": ordered[:limit],
        "kinds": len(ordered),
        "files": sum(counts.values()),
    }


def unknown_summary(data, limit=3):
    """把 unknown_extensions 的结果压成一句话（没东西时返回空串，供界面判断）。"""
    if not data or not data.get("files"):
        return ""
    shown = data["top"][:limit]
    items = "、".join(f"{ext}×{count}" if count > 1 else ext for ext, count in shown)
    suffix = f" 等 {data['kinds']} 种" if data["kinds"] > len(shown) else ""
    return f"未识别 {data['files']} 个文件（{items}{suffix}）"


# ==================== 精确层（可选：lizard） ====================
def lizard_available():
    try:
        import lizard  # noqa: F401
        return True
    except ImportError:
        return False


def lizard_metrics(path):
    """用 lizard 取一个文件的函数级指标；不可用/解析失败返回 None（由调用方标注）。

    取不到的字段不编造：max_nesting_depth 在老版本 lizard 上可能不存在，
    此时该子项为 None，"嵌套深渊"维度会退回启发式。
    """
    try:
        from lizard import analyze_file
    except ImportError:
        return None
    try:
        info = analyze_file(path)
    except Exception:
        return None

    functions = list(getattr(info, "function_list", None) or [])
    if not functions:
        return None

    ccns = [getattr(fn, "cyclomatic_complexity", None) or 1 for fn in functions]
    nlocs = [getattr(fn, "nloc", None) or 0 for fn in functions]
    nests = [getattr(fn, "max_nesting_depth", None) for fn in functions]
    nests = [n for n in nests if isinstance(n, (int, float))]
    long_funcs = sum(1 for n in nlocs if n > health_rules.LONG_FUNC_LINES)

    count = len(functions)
    return {
        "functions": count,
        "avg_ccn": round(sum(ccns) / count, 3),
        "max_ccn": max(ccns),
        "max_nesting": max(nests) if nests else None,
        "long_func_ratio": round(long_funcs * 100.0 / count, 2),
    }


def aggregate_precise(metrics_list):
    """把逐文件的 lizard 指标合成项目级精确指标；一条都没有则返回 None。"""
    usable = [m for m in metrics_list if m]
    if not usable:
        return None
    total_funcs = sum(m["functions"] for m in usable)
    avg_ccn = sum(m["avg_ccn"] * m["functions"] for m in usable) / total_funcs
    nests = [m["max_nesting"] for m in usable if m.get("max_nesting") is not None]
    long_funcs = sum(m["long_func_ratio"] * m["functions"] / 100.0 for m in usable)
    return {
        "functions": total_funcs,
        "avg_ccn": round(avg_ccn, 3),
        "max_ccn": max(m["max_ccn"] for m in usable),
        "max_nesting": max(nests) if nests else None,
        "long_func_ratio": round(long_funcs * 100.0 / total_funcs, 2),
    }


# ==================== 外部引擎（可选：scc / tokei） ====================
def detect_optional():
    """探测可选依赖与外部工具，供页面显示"已装/未装"。"""
    return {
        "lizard": lizard_available(),
        "scc": shutil.which("scc"),
        "tokei": shutil.which("tokei"),
    }


def _scc_complexity(root, exe):
    """再问一次 scc 要逐文件 Complexity，合成"复杂度/代码行"（与启发式同量纲）。

    loc_engine 的适配只取行数字段，这里补读复杂度字段；不改动 loc_engine，
    只用同一条命令再跑一次（scc 亚秒级，代价可接受）。
    """
    try:
        proc = subprocess.run([exe, "--format", "json", "--by-file", root], cwd=root,
                              capture_output=True, timeout=loc_engine.EXTERNAL_TIMEOUT,
                              creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise loc_engine.EngineError(f"读取 scc 复杂度失败：{exc}")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "ignore").strip()[:300]
        raise loc_engine.EngineError(f"scc 退出码 {proc.returncode}：{err}")
    try:
        data = json.loads(proc.stdout.decode("utf-8", "ignore"))
    except ValueError as exc:
        raise loc_engine.EngineError(f"scc 输出不是合法 JSON：{exc}")
    if not isinstance(data, list):
        raise loc_engine.EngineError("scc 输出不是数组，无法解析复杂度")

    complexity = 0.0
    code = 0.0
    for item in data:
        if not isinstance(item, dict):
            continue
        lowered = {str(k).lower(): v for k, v in item.items()}
        try:
            complexity += float(lowered.get("complexity") or 0)
            code += float(lowered.get("code") or 0)
        except (TypeError, ValueError):
            continue
    if code <= 0 or complexity <= 0:
        return {}
    return {"branch_per_code": complexity / code}


def scan_external(engine, root):
    """跑外部引擎，返回 (rows, extra, note)。

    外部引擎不认本页的缩进/重复/待办指标，因此这些维度自动退出评分；
    scc 额外提供复杂度，可多算一个"分支泥潭"维度。
    """
    started = time.perf_counter()
    if engine == "scc":
        exe = shutil.which("scc")
        if not exe:
            raise loc_engine.EngineError("scc 未安装或不在 PATH 上")
        result = loc_engine.count_with_scc(root, exe)
        extra = _scc_complexity(root, exe)
        note = f"scc：{len(result['files'])} 个文件，耗时 {time.perf_counter() - started:.2f} 秒"
    elif engine == "tokei":
        exe = shutil.which("tokei")
        if not exe:
            raise loc_engine.EngineError("tokei 未安装或不在 PATH 上")
        result = loc_engine.count_with_tokei(root, exe)
        extra = {}
        note = f"tokei：{len(result['files'])} 个文件（仅成分表），耗时 {time.perf_counter() - started:.2f} 秒"
    else:
        raise loc_engine.EngineError(f"{engine} 不支持外部调用")

    rows = []
    for row in result["files"]:
        item = dict(row)
        item["rel"] = _relative(item["path"], root)
        rows.append(item)
    return rows, extra, note


def _relative(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


# ==================== 屎山指数 ====================
def _percentile(values, ratio):
    """取分位（向上取整到存在的那个样本）。空集合返回 None。"""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * ratio))
    return float(ordered[index])


def _tally(rows):
    """把逐文件结果压成项目级原始指标；字段整批缺失时该项为 None（维度退出）。"""
    stats = {
        "files": len(rows),
        "total": sum(r.get("total", 0) for r in rows),
        "blank": sum(r.get("blank", 0) for r in rows),
        "comment": sum(r.get("comment", 0) for r in rows),
        "code": sum(r.get("code", 0) for r in rows),
    }
    stats["non_blank"] = stats["total"] - stats["blank"]
    stats["giant"] = sum(1 for r in rows
                         if r.get("total", 0) > health_rules.GIANT_FILE_LINES)

    def sum_field(name):
        if not any(name in r for r in rows):
            return None
        return sum(r.get(name, 0) for r in rows)

    stats["branch_hits"] = sum_field("branch_hits")
    stats["todo_count"] = sum_field("todo_count")
    stats["dup_lines"] = sum_field("dup_lines")
    # 嵌套取"编程语言文件各自最大缩进"的 90 分位，而不是全体最大值：
    # 最大值会被单个 JSX/长表达式文件钉死（实测一个文件 18 级就让整维恒为 100），
    # 分位仍然如实反映"这个代码库普遍有多深"。
    stats["max_indent"] = _percentile(
        [r["max_indent"] for r in rows
         if isinstance(r.get("max_indent"), (int, float))
         and health_rules.is_code_language(r.get("language", ""))],
        health_rules.NESTING_PERCENTILE)
    return stats


def _raw_metric(key, stats, extra):
    """各维度的原始指标；取不到返回 None。"""
    if key == "bloat":
        return stats["giant"] * 100.0 / stats["files"] if stats["files"] else None
    if key == "comment":
        return stats["comment"] * 100.0 / stats["non_blank"] if stats["non_blank"] else None
    if key == "branch":
        if extra.get("branch_per_code") is not None:
            return extra["branch_per_code"]
        if stats["branch_hits"] is None or not stats["code"]:
            return None
        return stats["branch_hits"] * 1.0 / stats["code"]
    if key == "nesting":
        return stats["max_indent"]
    if key == "dup":
        if stats["dup_lines"] is None or not stats["non_blank"]:
            return None
        return stats["dup_lines"] * 100.0 / stats["non_blank"]
    if key == "todo":
        if stats["todo_count"] is None or not stats["total"]:
            return None
        return stats["todo_count"] * 1000.0 / stats["total"]
    return None


def build_index(rows, extra=None, precise=None, snark=False):
    """算出屎山指数（0–100，越高越烂）与逐维度明细。

    extra   外部引擎补充的指标（如 scc 的 {"branch_per_code": x}）
    precise 精确层聚合结果（aggregate_precise 的返回值）；为 None 则第 7 维退出
    snark   是否取毒舌文案（只影响点评文字，不影响分数）

    未取到数据的维度自动退出：总分 = Σ(子分×权重) / Σ(权重)，因此三种数据完备度
    共用一条公式，无需为缺维度写特例。
    """
    extra = extra or {}
    stats = _tally(rows)
    dimensions = []
    weighted_sum = 0.0
    weight_total = 0.0

    for spec in health_rules.DIMENSIONS:
        key = spec["key"]
        if spec.get("only_precise") and not precise:
            continue

        unit = spec["unit"]
        curve = spec["curve"]

        if key == "funcs":
            raw = precise.get("long_func_ratio")
        elif key == "branch" and precise and precise.get("avg_ccn") is not None:
            raw = precise["avg_ccn"]
            unit = spec.get("unit_precise", unit)
            curve = spec.get("curve_precise", curve)
        elif key == "nesting" and precise and precise.get("max_nesting") is not None:
            raw = precise["max_nesting"]
            unit = spec.get("unit_precise", unit)
            curve = spec.get("curve_precise", curve)
        else:
            raw = _raw_metric(key, stats, extra)

        if raw is None:
            continue

        sub = health_rules.normalize(curve, raw)
        weight = spec["weight"]
        weighted_sum += sub * weight
        weight_total += weight
        dimensions.append({
            "key": key,
            "name": spec["name"],
            "unit": unit,
            "desc": spec["desc"],
            "raw": raw,
            "raw_text": health_rules.RAW_FORMAT.get(key, "{:.2f}").format(raw),
            "normalized": round(sub, 1),
            "weight": weight,
            "weighted": round(sub * weight / 100.0, 2),
            "note": health_texts.dim_note(key, health_rules.sub_band(sub), snark=snark),
        })

    score = int(round(weighted_sum / weight_total)) if weight_total else 0
    score = max(0, min(100, score))
    grade = health_rules.grade_for(score)
    return {
        "score": score,
        "grade": grade,
        "grade_short": health_texts.grade_short(grade["name"], snark=snark),
        "overall": health_texts.overall_note(grade["name"], snark=snark, pick=stats["files"]),
        "dimensions": dimensions,
        "stats": stats,
    }


def score_single(row):
    """单个文件的屎山分：用与项目级完全同一套曲线，但不建明细/文案（要跑几万次）。

    只取这一行的指标，因此"体量肥胖"退化为"这个文件是否超过 1000 行"、
    "分支泥潭"用这个文件自身的密度 —— 这正是"按文件"视图想看到的信号。
    """
    stats = _tally([row])
    weighted_sum = 0.0
    weight_total = 0.0
    for spec in health_rules.DIMENSIONS:
        if spec.get("only_precise"):
            continue
        raw = _raw_metric(spec["key"], stats, {})
        if raw is None:
            continue
        weighted_sum += health_rules.normalize(spec["curve"], raw) * spec["weight"]
        weight_total += spec["weight"]
    score = int(round(weighted_sum / weight_total)) if weight_total else 0
    score = max(0, min(100, score))
    return score, health_rules.grade_for(score)