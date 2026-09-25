#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""语言与注释语法表：扩展名 -> (语言名, 行注释前缀, 块注释对)。

覆盖本仓库实际出现的语言（ts/tsx/vue/rs/py/md/mdx/less/astro/cs/vb/xaml 等）。
匹配口径与 share.loc_engine 的轻量模式一致：只有"行首就是注释符"才算注释行，
行尾注释算代码行（与 cloc 同口径），因此这里给的前缀是按行首匹配的。
"""

import os


# 语言名, 行注释前缀, 块注释对
LANGS = {
    # 脚本类
    ".py":      ("Python",     ("#",),                     ()),
    ".pyi":     ("Python",     ("#",),                     ()),
    ".pyw":     ("Python",     ("#",),                     ()),
    ".rb":      ("Ruby",       ("#",),                     ()),
    ".pl":      ("Perl",       ("#",),                     ()),
    ".r":       ("R",          ("#",),                     ()),
    ".lua":     ("Lua",        ("--",),                    (("--[[", "]]"),)),
    ".sh":      ("Shell",      ("#",),                     ()),
    ".bash":    ("Shell",      ("#",),                     ()),
    ".zsh":     ("Shell",      ("#",),                     ()),
    ".ps1":     ("PowerShell", ("#",),                     (("<#", "#>"),)),
    ".psm1":    ("PowerShell", ("#",),                     (("<#", "#>"),)),
    # Windows 批处理：REM 需带空格以免误伤 remove 这类词
    ".bat":     ("Batch",      ("REM ", "rem ", "::"),     ()),
    ".cmd":     ("Batch",      ("REM ", "rem ", "::"),     ()),
    # JS / TS 家族
    ".js":      ("JavaScript", ("//",),                    (("/*", "*/"),)),
    ".jsx":     ("JavaScript", ("//",),                    (("/*", "*/"),)),
    ".mjs":     ("JavaScript", ("//",),                    (("/*", "*/"),)),
    ".cjs":     ("JavaScript", ("//",),                    (("/*", "*/"),)),
    ".ts":      ("TypeScript", ("//",),                    (("/*", "*/"),)),
    ".tsx":     ("TypeScript", ("//",),                    (("/*", "*/"),)),
    ".mts":     ("TypeScript", ("//",),                    (("/*", "*/"),)),
    ".cts":     ("TypeScript", ("//",),                    (("/*", "*/"),)),
    # 单文件组件：模板用 HTML 注释，脚本/样式用 C 系注释
    ".vue":     ("Vue",        ("//",),                    (("/*", "*/"), ("<!--", "-->"))),
    ".astro":   ("Astro",      ("//",),                    (("/*", "*/"), ("<!--", "-->"))),
    ".svelte":  ("Svelte",     ("//",),                    (("/*", "*/"), ("<!--", "-->"))),
    # C 系
    ".c":       ("C",          ("//",),                    (("/*", "*/"),)),
    ".h":       ("C/C++ 头文件", ("//",),                  (("/*", "*/"),)),
    ".cpp":     ("C++",        ("//",),                    (("/*", "*/"),)),
    ".cc":      ("C++",        ("//",),                    (("/*", "*/"),)),
    ".cxx":     ("C++",        ("//",),                    (("/*", "*/"),)),
    ".hpp":     ("C++",        ("//",),                    (("/*", "*/"),)),
    ".cs":      ("C#",         ("//",),                    (("/*", "*/"),)),
    ".java":    ("Java",       ("//",),                    (("/*", "*/"),)),
    ".kt":      ("Kotlin",     ("//",),                    (("/*", "*/"),)),
    ".swift":   ("Swift",      ("//",),                    (("/*", "*/"),)),
    ".go":      ("Go",         ("//",),                    (("/*", "*/"),)),
    ".rs":      ("Rust",       ("//",),                    (("/*", "*/"),)),
    ".dart":    ("Dart",       ("//",),                    (("/*", "*/"),)),
    ".scala":   ("Scala",      ("//",),                    (("/*", "*/"),)),
    ".php":     ("PHP",        ("//", "#"),                (("/*", "*/"),)),
    ".m":       ("Objective-C", ("//",),                   (("/*", "*/"),)),
    ".groovy":  ("Groovy",     ("//",),                    (("/*", "*/"),)),
    ".sql":     ("SQL",        ("--",),                    (("/*", "*/"),)),
    # 标记 / 样式
    ".css":     ("CSS",        (),                         (("/*", "*/"),)),
    ".less":    ("Less",       ("//",),                    (("/*", "*/"),)),
    ".scss":    ("SCSS",       ("//",),                    (("/*", "*/"),)),
    ".sass":    ("Sass",       ("//",),                    ()),
    ".styl":    ("Stylus",     ("//",),                    (("/*", "*/"),)),
    ".html":    ("HTML",       (),                         (("<!--", "-->"),)),
    ".htm":     ("HTML",       (),                         (("<!--", "-->"),)),
    ".xml":     ("XML",        (),                         (("<!--", "-->"),)),
    ".xaml":    ("XAML",       (),                         (("<!--", "-->"),)),
    ".svg":     ("SVG",        (),                         (("<!--", "-->"),)),
    ".plist":   ("XML",        (),                         (("<!--", "-->"),)),
    ".md":      ("Markdown",   (),                         (("<!--", "-->"),)),
    ".markdown": ("Markdown",  (),                         (("<!--", "-->"),)),
    ".mdx":     ("MDX",        (),                         (("<!--", "-->"),)),
    # 数据 / 配置（含注释的）
    ".toml":    ("TOML",       ("#",),                     ()),
    ".yaml":    ("YAML",       ("#",),                     ()),
    ".yml":     ("YAML",       ("#",),                     ()),
    ".ini":     ("INI",        ("#", ";"),                 ()),
    ".cfg":     ("INI",        ("#", ";"),                 ()),
    ".conf":    ("INI",        ("#", ";"),                 ()),
    ".properties": ("Properties", ("#", "!"),              ()),
    ".dockerfile": ("Dockerfile", ("#",),                  ()),
    ".editorconfig": ("EditorConfig", ("#", ";"),          ()),
    # JSON 无注释（严格 JSON），非空行一律算代码
    ".json":    ("JSON",       (),                         ()),
    ".jsonc":   ("JSONC",      ("//",),                    (("/*", "*/"),)),
    ".json5":   ("JSON5",      ("//",),                    (("/*", "*/"),)),
    ".graphql": ("GraphQL",    ("#",),                     ()),
    ".proto":   ("Protocol Buffers", ("//",),               (("/*", "*/"),)),
    ".gql":     ("GraphQL",    ("#",),                     ()),
    ".tex":     ("TeX",        ("%",),                     ()),
    ".vim":     ("Vim Script", ('"',),                     ()),
    ".ipynb":   ("Jupyter Notebook", ("#",),                ()),
}

# 按文件名（无扩展名或特殊名）识别
FILENAMES = {
    "makefile":     ("Makefile",   ("#",), ()),
    "gnumakefile":  ("Makefile",   ("#",), ()),
    "dockerfile":   ("Dockerfile", ("#",), ()),
    ".gitignore":   ("gitignore",  ("#",), ()),
    ".gitattributes": ("gitattributes", ("#",), ()),
    ".npmrc":       ("npmrc",      ("#", ";"), ()),
    ".env":         ("env",        ("#",), ()),
    ".env.local":   ("env",        ("#",), ()),
    ".dockerignore": ("dockerignore", ("#",), ()),
    "cargo.lock":   ("Lock 文件",  (),     ()),
}

# 纯文本扩展名：能算行数，但没有注释语法（非空行一律算代码）
PLAIN_TEXT_EXT = {
    ".txt", ".text", ".log", ".csv", ".tsv", ".rst", ".adoc",
    ".lock", ".sum", ".mod", ".map", ".diff", ".patch",
}

PLAIN_TEXT_LANG = "纯文本"


def get_spec(path):
    """返回 (语言名, 行注释前缀, 块注释对)；未知类型按纯文本处理。"""
    name = os.path.basename(path).lower()
    if name in FILENAMES:
        return FILENAMES[name]
    ext = os.path.splitext(name)[1]
    if ext in LANGS:
        return LANGS[ext]
    if ext in PLAIN_TEXT_EXT:
        return (PLAIN_TEXT_LANG, (), ())
    return (PLAIN_TEXT_LANG, (), ())


def language_of(path):
    return get_spec(path)[0]


def known_extensions():
    """已知的文本类扩展名合集，用于"留空=全部文本"时的预筛。"""
    return set(LANGS) | PLAIN_TEXT_EXT
