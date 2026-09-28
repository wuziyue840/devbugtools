#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""代码成分表 / 屎山指数的口径表。

本文件是**唯一**的阈值、权重、等级与配色来源：页面与引擎都从这里取，
不允许在别处硬编码阈值或色值（与项目既有的"主题集中"风格一致）。

屎山指数 0–100，**越高越烂**：每个维度先由原始指标经分段线性曲线归一化到
0–100 的子分，再按权重加权平均。未取到数据的维度**自动退出**，权重按剩余
维度重新归一 —— 这使"内置启发式 / 精确层 / 外部引擎"三种数据完备度用同一套
公式，不需要为缺维度写特例。
"""

import re

# ==================== 卡片配色（Canvas 与 HTML 导出的唯一取色处） ====================
PALETTE = {
    "paper": "#fbf8f1",      # 卡片底：暖纸色
    "panel": "#ffffff",      # 内容块底
    "ink": "#3d3529",        # 主文字：墨色
    "ink_soft": "#8a7a68",   # 次要文字
    "border": "#e2d9c6",     # 描边：暖灰
    "primary": "#2f6fd0",    # 品牌蓝
    "amber": "#c9a227",      # 点缀琥珀
    "red": "#c0392b",        # 朱红
    "green": "#2e7d5b",      # 墨绿
    "track": "#efe8d9",      # 占比条底槽
}

# 语言色块：尽量贴近各语言官方色，取不到就按 FALLBACK_COLORS 轮转
LANG_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Vue": "#41b883",
    "Svelte": "#ff3e00", "Astro": "#ff5d01", "Rust": "#dea584",
    "Python": "#3572a5", "CSS": "#563d7c", "SCSS": "#c6538c",
    "Sass": "#a53b70", "Less": "#1d365d", "Stylus": "#ff6347",
    "HTML": "#e34c26", "XML": "#0060ac", "XAML": "#0060ac",
    "SVG": "#ff9900", "Markdown": "#083fa1", "MDX": "#083fa1",
    "JSON": "#5b5b5b", "JSONC": "#5b5b5b", "JSON5": "#5b5b5b",
    "YAML": "#cb171e", "TOML": "#9c4221", "INI": "#6c6c6c",
    "Shell": "#89e051", "PowerShell": "#012456", "Batch": "#c1f12e",
    "C": "#555555", "C/C++ 头文件": "#6a6a6a", "C++": "#f34b7d",
    "C#": "#178600", "Java": "#b07219", "Kotlin": "#a97bff",
    "Swift": "#f05138", "Go": "#00add8", "Dart": "#00b4ab",
    "Scala": "#c22d40", "PHP": "#4f5d95", "Ruby": "#701516",
    "Perl": "#0298c3", "R": "#198ce7", "Lua": "#000080",
    "Groovy": "#4298b8", "Objective-C": "#438eff", "SQL": "#e38c00",
    "Protocol Buffers": "#9c6b3f", "GraphQL": "#e10098",
    "Dockerfile": "#384d54", "Makefile": "#427819", "TeX": "#3d6117",
    "Vim Script": "#199f4b", "Jupyter Notebook": "#da5b0b",
    "纯文本": "#9e9e9e", "Lock 文件": "#8d8d8d",
}
FALLBACK_COLORS = ("#2f6fd0", "#c9a227", "#2e7d5b", "#c0392b",
                   "#7b5ea7", "#0f8a8a", "#b5651d", "#4a6fa5")

# 行成分三段颜色（成分表里到处用它，务必与图例一致）
LINE_COLORS = {
    "code": "#2f6fd0",
    "comment": "#2e7d5b",
    "blank": "#d8cfbc",
}


def lang_color(name):
    """按语言名取色块色；没登记过就按名字稳定地轮转到一个兜底色。"""
    if name in LANG_COLORS:
        return LANG_COLORS[name]
    return FALLBACK_COLORS[sum(ord(ch) for ch in str(name)) % len(FALLBACK_COLORS)]


# ==================== 分支关键字（复杂度维度的启发式代理） ====================
# 只取词边界匹配、只认最没有歧义的那批关键字：宁可少算，也不要把
# "shift" 里的 if、"class" 里的 case 算进去。`?` 单独不取（三元 / 可空类型会误伤）。
_C_STYLE = (
    re.compile(r"\bif\b"), re.compile(r"\bfor\b"), re.compile(r"\bwhile\b"),
    re.compile(r"\bcase\b"), re.compile(r"\bcatch\b"), re.compile(r"&&"),
    re.compile(r"\|\|"), re.compile(r"\?\?"),
)
_WORDY = (
    re.compile(r"\bif\b"), re.compile(r"\belif\b"), re.compile(r"\belseif\b"),
    re.compile(r"\bfor\b"), re.compile(r"\bwhile\b"), re.compile(r"\bexcept\b"),
    re.compile(r"\brescue\b"), re.compile(r"\bcase\b"), re.compile(r"\bwhen\b"),
    re.compile(r"\band\b"), re.compile(r"\bor\b"),
)
_SQL = (
    re.compile(r"\bcase\b"), re.compile(r"\bwhen\b"), re.compile(r"\bif\b"),
    re.compile(r"\band\b"), re.compile(r"\bor\b"),
)
_BATCH = (
    re.compile(r"\bif\b"), re.compile(r"\belse\b"), re.compile(r"\bfor\b"),
    re.compile(r"\bgoto\b"),
)

_C_STYLE_LANGS = {
    "C", "C/C++ 头文件", "C++", "C#", "Java", "Kotlin", "Swift", "Go",
    "Rust", "Dart", "Scala", "PHP", "Objective-C", "Groovy", "Vue",
    "Astro", "Svelte", "JavaScript", "TypeScript", "Less", "SCSS",
    "Stylus", "JSONC", "JSON5", "Protocol Buffers",
}
_WORDY_LANGS = {"Python", "Ruby", "Perl", "Shell", "PowerShell", "Lua", "R"}

BRANCH_BY_LANG = {lang: _C_STYLE for lang in _C_STYLE_LANGS}
BRANCH_BY_LANG.update({lang: _WORDY for lang in _WORDY_LANGS})
BRANCH_BY_LANG["SQL"] = _SQL
BRANCH_BY_LANG["Batch"] = _BATCH

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b", re.IGNORECASE)


def branch_patterns_for(language):
    """这个语言用哪组分支关键字；没有登记的（标记/样式/纯文本）返回空元组。"""
    return BRANCH_BY_LANG.get(language, ())


def count_todos(text):
    """这一行里出现了几个待办标记（按出现次数计，便于算"每千行有几个"）。"""
    return len(_TODO_RE.findall(text))


def is_code_language(language):
    """是不是"有控制流"的编程语言。

    嵌套深度与重复行只对这类语言计：Markdown / 纯文本 / JSON / Lock 这些
    标记与数据文件的缩进是**排版**、重复行是**数据本身的结构**，拿去当"嵌套深渊"
    和"复制粘贴"会得出荒谬的数字（实测某个 Markdown 的 85 空格缩进会被算成 42 级）。
    """
    return language in BRANCH_BY_LANG


# ==================== 体量与缩进的口径 ====================
GIANT_FILE_LINES = 1000      # 巨型文件（体量肥胖维度的主指标）
LONG_FUNC_LINES = 80         # 超长函数（精确层的函数臃肿维度）
TAB_WIDTH = 4                # 制表符按 4 空格折算
INDENT_UNIT_RANGE = (2, 8)   # 每文件自适应的缩进单位允许范围
INDENT_UNIT_FALLBACK = 4     # 文件里量不出缩进单位时的兜底
INDENT_STEP_MAX = 8          # 只把 1–8 空格的"上台阶"当成缩进，对齐线不算
NESTING_PERCENTILE = 0.90    # 嵌套维度取"各文件最大缩进"的 90 分位（见 health_engine）

# ==================== 重复行的口径 ====================
# 只算"像代码"的行：太短的行（}、)、),、</div>）天然到处重复，算进去等于把
# 结构符号当复制粘贴。要求归一化后够长且含字母。
DUP_MIN_LINE_CHARS = 12
# 这些语言的"重复行"是数据本身的结构（锁文件、配置、标记），不参与该维度
DUP_EXCLUDED_LANGS = {
    "Lock 文件", "纯文本", "JSON", "JSONC", "JSON5", "SVG", "XML", "XAML",
    "INI", "EditorConfig", "Properties", "TOML", "YAML",
}

# ==================== 维度定义（顺序即卡片与明细表的展示顺序） ====================
# curve：分段线性锚点 ((raw, sub_score), ...)，须对 raw 单调；两点之间线性插值，
#        两端各自夹紧。curve_precise / unit_precise 只在精确层（lizard）可用时启用。
DIMENSIONS = (
    {
        "key": "bloat", "name": "体量肥胖", "unit": "%", "weight": 15,
        "curve": ((0.0, 0.0), (2.0, 60.0), (8.0, 100.0)),
        "desc": "巨型文件（>1000 行）占比",
    },
    {
        "key": "comment", "name": "注释荒漠", "unit": "%", "weight": 10,
        "curve": ((15.0, 0.0), (5.0, 60.0), (0.0, 100.0)),
        "desc": "注释率（占非空行），低于 15% 起扣",
    },
    {
        "key": "branch", "name": "分支泥潭", "unit": "分支/代码行", "weight": 20,
        "curve": ((0.05, 0.0), (0.15, 60.0), (0.35, 100.0)),
        "unit_precise": "平均 CCN",
        "curve_precise": ((3.0, 0.0), (8.0, 60.0), (15.0, 100.0)),
        "desc": "每行代码的分支关键字密度；精确层改用真实圈复杂度",
    },
    {
        "key": "nesting", "name": "嵌套深渊", "unit": "级（文件 p90）", "weight": 15,
        "curve": ((4.0, 0.0), (9.0, 60.0), (16.0, 100.0)),
        "unit_precise": "函数最大嵌套",
        "curve_precise": ((3.0, 0.0), (6.0, 60.0), (10.0, 100.0)),
        "desc": "各文件最大缩进的 90 分位（按文件自身缩进单位折算）",
    },
    {
        "key": "dup", "name": "复制粘贴", "unit": "%", "weight": 15,
        "curve": ((5.0, 0.0), (15.0, 60.0), (35.0, 100.0)),
        "desc": "文件内归一化重复行占比（首版不做跨文件）",
    },
    {
        "key": "todo", "name": "待办债台", "unit": "个/千行", "weight": 10,
        "curve": ((0.5, 0.0), (3.0, 60.0), (8.0, 100.0)),
        "desc": "TODO / FIXME / HACK / XXX / BUG 密度",
    },
    {
        "key": "funcs", "name": "函数臃肿", "unit": "%", "weight": 15,
        "curve": ((0.0, 0.0), (3.0, 60.0), (10.0, 100.0)),
        "only_precise": True,
        "desc": "超长函数（>80 NLOC）占比，需精确层",
    },
)
DIMENSION_BY_KEY = {d["key"]: d for d in DIMENSIONS}

# 维度在明细表 / 文案里用的原始值格式
RAW_FORMAT = {
    "bloat": "{:.1f}%", "comment": "{:.1f}%", "branch": "{:.3f}",
    "nesting": "{:.1f}", "dup": "{:.1f}%", "todo": "{:.1f}",
    "funcs": "{:.1f}%",
}

# ==================== 等级色带 ====================
# 分数越高越烂。emoji 只给 HTML 导出用 —— Tk 的雅黑没有这些字形、又不做字体
# 回退，画在 Canvas 上会变成方框（项目里八卦盘已经踩过这个坑）。
GRADES = (
    {"max": 19, "name": "良好", "emoji": "😊", "color": "#2e7d5b"},
    {"max": 39, "name": "尚可", "emoji": "🙂", "color": "#5aa469"},
    {"max": 59, "name": "一般", "emoji": "😐", "color": "#c9a227"},
    {"max": 79, "name": "偏差", "emoji": "😫", "color": "#e07b39"},
    {"max": 100, "name": "垮掉", "emoji": "💀", "color": "#c0392b"},
)
# 等级短句（卡片上跟在等级名后面；毒舌版由 health_texts 提供）
GRADE_SHORT = {
    "良好": "结构清爽",
    "尚可": "整体健康",
    "一般": "存在技术债",
    "偏差": "维护风险高",
    "垮掉": "建议重整",
}


def grade_for(score):
    for grade in GRADES:
        if score <= grade["max"]:
            return grade
    return GRADES[-1]


def sub_band(sub_score):
    """子分落进哪个档：0 清爽 / 1 尚可 / 2 偏高 / 3 严重。文案池按这个索引取。"""
    if sub_score < 25:
        return 0
    if sub_score < 50:
        return 1
    if sub_score < 75:
        return 2
    return 3


def normalize(curve, raw):
    """把原始指标按分段线性锚点夹紧 + 插值到 0–100 子分。"""
    points = sorted(curve)
    if raw <= points[0][0]:
        return points[0][1]
    if raw >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= raw <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (raw - x0) / (x1 - x0)
    return 0.0