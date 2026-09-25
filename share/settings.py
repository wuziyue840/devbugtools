#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""配置持久化：把扫描目录、排除列表、引擎等选择存到用户目录下的 settings.json。

**默认不写盘**：只有界面上的「记住设置」开关打开时才会保存。开关状态本身也存在
这个文件里，所以关掉之后下次启动仍然是关的。

为什么放用户目录而不是工具目录：打包成单文件 exe 后工具目录是临时解包目录
（退出即删），装在只读目录里也无法写入 —— 放用户目录两种情形都能用。

读取一律带类型兜底，配置文件写坏、类型写错、引擎名非法都只会退回默认值，
绝不会因为配置有问题就打不开工具。
"""

import json
import os

APP_DIR_NAME = "StarBoxTools"
SETTINGS_NAME = "settings.json"

# 合法的统计引擎（下拉框是按下标取值的，非法值会让下标越界）
ENGINES = ("builtin", "builtin_lexical", "scc", "tokei", "cloc")
VIEW_MODES = ("file", "lang")


def store_dir():
    """配置目录：Windows 用 %APPDATA%，其他平台用 XDG 配置目录或 ~/.config。

    环境变量缺失时**只在同一个用户数据树下兜底**（%~\\AppData\\Roaming），
    不会退到用户目录根部凭空建文件夹 —— 目的是"配置只有这一个已知位置"。
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_DIR_NAME)


STORE_DIR = store_dir()
SETTINGS_PATH = os.path.join(STORE_DIR, SETTINGS_NAME)
# 偏好单独一个文件：跟"扫描设置"不是一回事 —— 它记的是界面行为开关
# （比如要不要自动填入默认扫描目标），不该跟扫描参数混在一份记录里。
PREFS_NAME = "prefs.json"
PREFS_PATH = os.path.join(STORE_DIR, PREFS_NAME)

DEFAULT_PREFS = {
    "autofill_default_target": False,   # 启动时是否自动把默认目录填成扫描目标
}

DEFAULTS = {
    "remember": False,      # 是否记住设置；关闭时不读也不写
    "targets": [],          # 扫描目标：[{"path":..., "kind":"dir"|"file"}, ...]
    "scan_dir": "",         # 旧字段（单目录时代），仅用于首次迁移，见 load()
    "engine": "builtin",
    "extensions": "",
    "excludes": [],
    "lexical": False,
    "skip_blank": True,
    "skip_comment": True,
    "tracked_only": False,
    "view_mode": "file",
}

TARGET_KINDS = ("dir", "file")

BOOL_KEYS = ("remember", "lexical", "skip_blank", "skip_comment", "tracked_only")
STR_KEYS = ("scan_dir", "engine", "extensions", "view_mode")


def _as_bool(value):
    """把配置里的值当布尔解释。字符串要按语义判断，否则 bool("false") 会是 True。"""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "none", "off")
    return bool(value)


def _clean_targets(value):
    """清洗扫描目标列表：必须是 [{"path": 非空字符串, "kind": "dir"|"file"}]，顺带去重。

    写坏的项直接丢掉而不是报错 —— 配置有问题不该打不开工具。
    """
    if not isinstance(value, list):
        return []
    cleaned = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in TARGET_KINDS:
            kind = "dir"
        key = (os.path.normcase(os.path.abspath(path)), kind)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"path": path, "kind": kind})
    return cleaned


def exists():
    """是否已存在配置记录。"""
    return os.path.isfile(SETTINGS_PATH)


def load():
    """读配置，返回含全部字段的字典（文件里的值 + 类型兜底）。

    注意：这里**不判断** remember —— 调用方决定要不要把值应用到界面。
    文件不存在或读坏时返回默认值。
    """
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return data
    if not isinstance(saved, dict):
        return data

    for key in DEFAULTS:
        if key in saved:
            data[key] = saved[key]

    if not isinstance(data.get("excludes"), list):
        data["excludes"] = []
    data["excludes"] = [str(x) for x in data["excludes"] if str(x).strip()]
    data["targets"] = _clean_targets(data.get("targets"))
    for key in BOOL_KEYS:
        data[key] = _as_bool(data.get(key))
    for key in STR_KEYS:
        data[key] = str(data.get(key) or "")
    if data["engine"] not in ENGINES:
        data["engine"] = "builtin"
    if data["view_mode"] not in VIEW_MODES:
        data["view_mode"] = "file"

    # 旧字段迁移：单目录时代的记录里只有 scan_dir，这里把它变成唯一目标。
    # 只读一次，之后以 targets 为准（保存时 scan_dir 会被写回空串）。
    if not data["targets"] and data["scan_dir"] and os.path.isdir(data["scan_dir"]):
        data["targets"] = [{"path": data["scan_dir"], "kind": "dir"}]

    return data


def save(data):
    """保存配置，返回是否成功。

    失败不再静默吞掉：调用方会据此在状态栏提示，否则用户会以为记住了、
    实际上什么都没写进去（只读目录下尤其容易踩）。
    """
    payload = dict(DEFAULTS)
    payload.update({k: v for k, v in (data or {}).items() if k in DEFAULTS})
    try:
        os.makedirs(STORE_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        return False
    return True


def set_remember(flag):
    """只改 remember 标记，保留文件里已有的其他值（不覆盖、不删除）。

    文件本来就不存在时什么都不做 —— 不能因为"关闭记忆"反而凭空造出一个文件。
    """
    if not exists():
        return True
    data = load()
    data["remember"] = bool(flag)
    return save(data)


def clear():
    """删除配置记录与偏好记录，返回被删掉的文件名列表（空列表表示本来就没有）。

    删完如果目录已经空了就一并删掉目录；目录里还有别的东西则保留，
    不去动不是本工具创建的文件。
    """
    removed = []
    for path in (SETTINGS_PATH, PREFS_PATH):
        try:
            os.remove(path)
            removed.append(os.path.basename(path))
        except OSError:
            pass
    try:
        os.rmdir(STORE_DIR)
    except OSError:
        pass
    return removed


# ==================== 偏好（prefs.json，与 settings.json 分开） ====================
def load_prefs():
    """读界面偏好。文件不存在或读坏一律回默认值。"""
    data = dict(DEFAULT_PREFS)
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return data
    if not isinstance(saved, dict):
        return data
    for key in DEFAULT_PREFS:
        if key in saved:
            data[key] = saved[key]
    for key in DEFAULT_PREFS:
        data[key] = _as_bool(data.get(key))
    return data


def save_prefs(data):
    """写偏好，返回是否成功（失败要在界面上说出来）。"""
    payload = dict(DEFAULT_PREFS)
    payload.update({k: v for k, v in (data or {}).items() if k in DEFAULT_PREFS})
    try:
        os.makedirs(STORE_DIR, exist_ok=True)
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        return False
    return True


def set_pref(name, value):
    """改一个偏好项（保留其他项），返回是否成功。"""
    if name not in DEFAULT_PREFS:
        raise KeyError(name)
    data = load_prefs()
    data[name] = bool(value)
    return save_prefs(data)
