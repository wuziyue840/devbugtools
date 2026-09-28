#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""语言与注释语法表：扩展名 -> (语言名, 行注释前缀, 块注释对)。

覆盖主流语言（约 110 种语言 / 约 170 个扩展名 + 约 30 个特殊文件名），面向的是
"拿去分析任意项目"而不是"只认本仓库"。匹配口径与 share.loc_engine 的轻量模式一致：
只有"行首就是注释符"才算注释行，行尾注释算代码行（与 cloc 同口径），因此这里给的
前缀是按行首匹配的。

两条约定：
  1. **块注释对排在行注释前缀之前判定**（见 count_file_light）：像 Julia 的 `#=`、
     CoffeeScript 的 `###`、Nim 的 `#[` 都以行注释符开头，必须让块注释先命中。
  2. **多义扩展名按更常见的那一个取名**：`.v` 取 Verilog（不是 Coq）、`.d` 取 D
     （不是 make 依赖文件）、`.m` 取 Objective-C（不是 MATLAB）、`.s` 取汇编
     （不是 S 语言）。宁可认成"一个相近的语言"，也比认成纯文本有用。

新增语言时**务必同时**在 share/health_rules.py 里登记分支家族（或写进
NON_CODE_LANGS）—— 否则该语言在成分表页不会参与"分支/嵌套/复制"三个维度。
"""

import os


# 语言名, 行注释前缀, 块注释对
LANGS = {
    # ==================== 脚本类 ====================
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
    ".tcl":     ("Tcl",        ("#",),                     ()),
    ".awk":     ("Awk",        ("#",),                     ()),
    ".raku":    ("Raku",       ("#",),                     ()),
    ".p6":      ("Raku",       ("#",),                     ()),
    ".ex":      ("Elixir",     ("#",),                     ()),
    ".exs":     ("Elixir",     ("#",),                     ()),
    ".erl":     ("Erlang",     ("%",),                     ()),
    ".hrl":     ("Erlang",     ("%",),                     ()),
    ".jl":      ("Julia",      ("#",),                     (("#=", "=#"),)),
    ".nim":     ("Nim",        ("#",),                     (("#[", "]#"),)),
    ".nims":    ("Nim",        ("#",),                     (("#[", "]#"),)),
    ".cr":      ("Crystal",    ("#",),                     ()),
    ".coffee":  ("CoffeeScript", ("#",),                   (("###", "###"),)),
    ".rexx":    ("Rexx",       ("--",),                    (("/*", "*/"),)),
    ".lisp":    ("Lisp",       (";",),                     (("#|", "|#"),)),
    ".el":      ("Lisp",       (";",),                     (("#|", "|#"),)),
    ".scm":     ("Lisp",       (";",),                     (("#|", "|#"),)),
    ".rkt":     ("Lisp",       (";",),                     (("#|", "|#"),)),
    ".clj":     ("Clojure",    (";",),                     ()),
    ".cljs":    ("Clojure",    (";",),                     ()),
    ".cljc":    ("Clojure",    (";",),                     ()),
    ".edn":     ("Clojure",    (";",),                     ()),
    ".pro":     ("Prolog",     ("%",),                     (("/*", "*/"),)),
    # Windows 批处理：REM 需带空格以免误伤 remove 这类词
    ".bat":     ("Batch",      ("REM ", "rem ", "::"),     ()),
    ".cmd":     ("Batch",      ("REM ", "rem ", "::"),     ()),

    # ==================== JS / TS 家族 ====================
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

    # ==================== C 系 ====================
    ".c":       ("C",          ("//",),                    (("/*", "*/"),)),
    ".h":       ("C/C++ 头文件", ("//",),                  (("/*", "*/"),)),
    ".cpp":     ("C++",        ("//",),                    (("/*", "*/"),)),
    ".cc":      ("C++",        ("//",),                    (("/*", "*/"),)),
    ".cxx":     ("C++",        ("//",),                    (("/*", "*/"),)),
    ".hpp":     ("C++",        ("//",),                    (("/*", "*/"),)),
    ".hh":      ("C++",        ("//",),                    (("/*", "*/"),)),
    ".hxx":     ("C++",        ("//",),                    (("/*", "*/"),)),
    ".cs":      ("C#",         ("//",),                    (("/*", "*/"),)),
    ".java":    ("Java",       ("//",),                    (("/*", "*/"),)),
    ".kt":      ("Kotlin",     ("//",),                    (("/*", "*/"),)),
    ".kts":     ("Kotlin",     ("//",),                    (("/*", "*/"),)),
    ".swift":   ("Swift",      ("//",),                    (("/*", "*/"),)),
    ".go":      ("Go",         ("//",),                    (("/*", "*/"),)),
    ".rs":      ("Rust",       ("//",),                    (("/*", "*/"),)),
    ".dart":    ("Dart",       ("//",),                    (("/*", "*/"),)),
    ".scala":   ("Scala",      ("//",),                    (("/*", "*/"),)),
    ".php":     ("PHP",        ("//", "#"),                (("/*", "*/"),)),
    ".m":       ("Objective-C", ("//",),                   (("/*", "*/"),)),
    ".mm":      ("Objective-C++", ("//",),                 (("/*", "*/"),)),
    ".groovy":  ("Groovy",     ("//",),                    (("/*", "*/"),)),
    ".gradle":  ("Groovy",     ("//",),                    (("/*", "*/"),)),
    ".d":       ("D",          ("//",),                    (("/*", "*/"),)),
    ".zig":     ("Zig",        ("//",),                    (("/*", "*/"),)),
    ".sol":     ("Solidity",   ("//",),                    (("/*", "*/"),)),
    ".hx":      ("Haxe",       ("//",),                    (("/*", "*/"),)),
    ".vala":    ("Vala",       ("//",),                    (("/*", "*/"),)),
    ".vapi":    ("Vala",       ("//",),                    (("/*", "*/"),)),
    ".odin":    ("Odin",       ("//",),                    (("/*", "*/"),)),
    ".res":     ("ReScript",   ("//",),                    (("/*", "*/"),)),
    ".resi":    ("ReScript",   ("//",),                    (("/*", "*/"),)),
    ".gleam":   ("Gleam",      ("//",),                    ()),
    ".hs":      ("Haskell",    ("--",),                    (("{-", "-}"),)),
    ".lhs":     ("Haskell",    ("--",),                    (("{-", "-}"),)),
    ".ml":      ("OCaml",      (),                         (("(*", "*)"),)),
    ".mli":     ("OCaml",      (),                         (("(*", "*)"),)),
    ".fs":      ("F#",         ("//",),                    (("(*", "*)"),)),
    ".fsi":     ("F#",         ("//",),                    (("(*", "*)"),)),
    ".fsx":     ("F#",         ("//",),                    (("(*", "*)"),)),
    ".elm":     ("Elm",        ("--",),                    (("{-", "-}"),)),
    ".adb":     ("Ada",        ("--",),                    ()),
    ".ads":     ("Ada",        ("--",),                    ()),
    ".purs":    ("PureScript", ("--",),                    (("{-", "-}"),)),

    # ==================== 硬件 / 系统 / 构建 ====================
    ".v":       ("Verilog",    ("//",),                    (("/*", "*/"),)),
    ".vh":      ("Verilog",    ("//",),                    (("/*", "*/"),)),
    ".sv":      ("SystemVerilog", ("//",),                 (("/*", "*/"),)),
    ".svh":     ("SystemVerilog", ("//",),                 (("/*", "*/"),)),
    ".vhd":     ("VHDL",       ("--",),                    ()),
    ".vhdl":    ("VHDL",       ("--",),                    ()),
    ".asm":     ("Assembly",   (";", "#"),                 (("/*", "*/"),)),
    ".s":       ("Assembly",   (";", "#"),                 (("/*", "*/"),)),
    ".ld":      ("Linker Script", (),                      (("/*", "*/"),)),
    ".lds":     ("Linker Script", (),                      (("/*", "*/"),)),
    ".cmake":   ("CMake",      ("#",),                     ()),
    ".meson":   ("Meson",      ("#",),                     ()),
    ".bzl":     ("Starlark",   ("#",),                     ()),
    ".bazel":   ("Starlark",   ("#",),                     ()),
    ".nix":     ("Nix",        ("#",),                     (("/*", "*/"),)),
    ".tf":      ("HCL",        ("#", "//"),                (("/*", "*/"),)),
    ".tfvars":  ("HCL",        ("#", "//"),                (("/*", "*/"),)),
    ".hcl":     ("HCL",        ("#", "//"),                (("/*", "*/"),)),
    ".work":    ("Go Module",  ("//",),                    ()),

    # ==================== 科学计算 / 其他语言 ====================
    ".f":       ("Fortran",    ("!",),                     ()),
    ".for":     ("Fortran",    ("!",),                     ()),
    ".f77":     ("Fortran",    ("!",),                     ()),
    ".f90":     ("Fortran",    ("!",),                     ()),
    ".f95":     ("Fortran",    ("!",),                     ()),
    ".f03":     ("Fortran",    ("!",),                     ()),
    ".f08":     ("Fortran",    ("!",),                     ()),
    ".pas":     ("Pascal",     ("//",),                    (("(*", "*)"), ("{", "}"))),
    # `.pp` 取 Puppet（DevOps 仓库里远比 Free Pascal 常见）；Free Pascal 用 .pas
    ".pp":      ("Puppet",     ("#",),                     ()),
    ".cob":     ("COBOL",      ("*>", "*"),                ()),
    ".cbl":     ("COBOL",      ("*>", "*"),                ()),
    ".vb":      ("Visual Basic", ("'",),                   ()),
    ".vbs":     ("Visual Basic", ("'",),                   ()),

    # ==================== 标记 / 样式 ====================
    ".css":     ("CSS",        (),                         (("/*", "*/"),)),
    ".pcss":    ("PostCSS",    (),                         (("/*", "*/"),)),
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
    ".resx":    ("XML",        (),                         (("<!--", "-->"),)),
    ".csproj":  ("XML",        (),                         (("<!--", "-->"),)),
    ".props":   ("XML",        (),                         (("<!--", "-->"),)),
    ".targets": ("XML",        (),                         (("<!--", "-->"),)),
    ".md":      ("Markdown",   (),                         (("<!--", "-->"),)),
    ".markdown": ("Markdown",  (),                         (("<!--", "-->"),)),
    ".mdx":     ("MDX",        (),                         (("<!--", "-->"),)),
    ".rst":     ("reStructuredText", (),                   ()),
    ".adoc":    ("AsciiDoc",   ("//",),                    (("////", "////"),)),
    ".org":     ("Org",        ("# ",),                    ()),
    ".tex":     ("TeX",        ("%",),                     ()),
    ".bib":     ("BibTeX",     ("%",),                     ()),
    ".rmd":     ("R Markdown", (),                         (("<!--", "-->"),)),
    ".qmd":     ("Quarto",     (),                         (("<!--", "-->"),)),
    # 模板语言：脚本段与模板指令混排，行注释按各自语法给
    ".cshtml":  ("Razor",      (),                         (("<!--", "-->"), ("@*", "*@"))),
    ".razor":   ("Razor",      (),                         (("<!--", "-->"), ("@*", "*@"))),
    ".jsp":     ("JSP",        (),                         (("<!--", "-->"), ("<%--", "--%>"))),
    ".erb":     ("ERB",        (),                         (("<!--", "-->"), ("<%#", "%>"))),
    ".twig":    ("Twig",       (),                         (("{#", "#}"),)),
    ".jinja":   ("Jinja",      (),                         (("{#", "#}"),)),
    ".jinja2":  ("Jinja",      (),                         (("{#", "#}"),)),
    ".j2":      ("Jinja",      (),                         (("{#", "#}"),)),
    ".liquid":  ("Liquid",     (),                         (("{#", "#}"),)),
    ".hbs":     ("Handlebars", (),                         (("{{!--", "--}}"),)),
    ".pug":     ("Pug",        ("//-",),                   ()),
    ".jade":    ("Pug",        ("//-",),                   ()),
    ".haml":    ("Haml",       ("-#",),                    ()),
    ".mustache": ("Handlebars", (),                        (("{{!", "}}"),)),

    # ==================== 数据 / 配置（含注释的） ====================
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
    ".har":     ("JSON",       (),                         ()),
    ".ipynb":   ("Jupyter Notebook", ("#",),               ()),
    ".graphql": ("GraphQL",    ("#",),                     ()),
    ".gql":     ("GraphQL",    ("#",),                     ()),
    ".proto":   ("Protocol Buffers", ("//",),              (("/*", "*/"),)),
    ".sql":     ("SQL",        ("--",),                    (("/*", "*/"),)),
    ".psql":    ("SQL",        ("--",),                    (("/*", "*/"),)),
    ".plsql":   ("SQL",        ("--",),                    (("/*", "*/"),)),
    ".pks":     ("SQL",        ("--",),                    (("/*", "*/"),)),
    ".pkb":     ("SQL",        ("--",),                    (("/*", "*/"),)),
    ".vim":     ("Vim Script", ('"',),                     ()),
    ".reg":     ("Registry",   (";",),                     ()),
    ".http":    ("HTTP 请求",  ("#",),                     ()),
    ".rest":    ("HTTP 请求",  ("#",),                     ()),
    # 图形 / 图表描述语言
    ".puml":    ("PlantUML",   ("'",),                     (("/'", "'/"),)),
    ".plantuml": ("PlantUML",  ("'",),                     (("/'", "'/"),)),
    ".mmd":     ("Mermaid",    ("%%",),                    ()),
    ".mermaid": ("Mermaid",    ("%%",),                    ()),
    ".d2":      ("D2",         ("#",),                     ()),
}

# 按文件名（无扩展名或特殊名）识别。
# 注意：`.gitignore` 这类以点开头的文件 os.path.splitext 会说"没有扩展名"，
# 所以它们只能靠这张表认出来 —— 每次遇到新的工具链，优先往这里补一行。
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
    # 构建 / 包管理
    "cmakelists.txt": ("CMake",    ("#",), ()),
    "meson.build":  ("Meson",      ("#",), ()),
    "meson_options.txt": ("Meson", ("#",), ()),
    "justfile":     ("Just",       ("#",), ()),
    ".justfile":    ("Just",       ("#",), ()),
    "build":        ("Starlark",   ("#",), ()),
    "build.bazel":  ("Starlark",   ("#",), ()),
    "workspace":    ("Starlark",   ("#",), ()),
    "workspace.bazel": ("Starlark", ("#",), ()),
    "module.bazel": ("Starlark",   ("#",), ()),
    "bazelrc":      ("Bazel RC",   ("#",), ()),
    ".bazelrc":     ("Bazel RC",   ("#",), ()),
    "go.mod":       ("Go Module",  ("//",), ()),
    "go.work":      ("Go Module",  ("//",), ()),
    "pipfile":      ("TOML",       ("#",), ()),
    # Ruby / Groovy 生态的"无扩展名脚本"
    "jenkinsfile":  ("Groovy",     ("//",), (("/*", "*/"),)),
    "vagrantfile":  ("Ruby",       ("#",), ()),
    "gemfile":      ("Ruby",       ("#",), ()),
    "rakefile":     ("Ruby",       ("#",), ()),
    "brewfile":     ("Ruby",       ("#",), ()),
    "podfile":      ("Ruby",       ("#",), ()),
    "fastfile":     ("Ruby",       ("#",), ()),
    "appfile":      ("Ruby",       ("#",), ()),
    "berksfile":    ("Ruby",       ("#",), ()),
    "thorfile":     ("Ruby",       ("#",), ()),
    "capfile":      ("Ruby",       ("#",), ()),
    "procfile":     ("Procfile",   ("#",), ()),
    # 锁文件与各类 rc / ignore
    "yarn.lock":    ("Lock 文件",  (),     ()),
    "poetry.lock":  ("Lock 文件",  (),     ()),
    "pipfile.lock": ("Lock 文件",  (),     ()),
    "gemfile.lock": ("Lock 文件",  (),     ()),
    "bun.lockb":    ("Lock 文件",  (),     ()),
    ".gitmodules":  ("gitconfig",  ("#", ";"), ()),
    ".mailmap":     ("mailmap",    ("#",), ()),
    ".gitkeep":     ("gitkeep",    ("#",), ()),
    ".clang-format": ("YAML",      ("#",), ()),
    ".clang-tidy":  ("YAML",       ("#",), ()),
    ".prettierrc":  ("JSONC",      ("//",), (("/*", "*/"),)),
    ".eslintrc":    ("JSONC",      ("//",), (("/*", "*/"),)),
    ".babelrc":     ("JSONC",      ("//",), (("/*", "*/"),)),
    ".stylelintrc": ("JSONC",      ("//",), (("/*", "*/"),)),
    ".swcrc":       ("JSONC",      ("//",), (("/*", "*/"),)),
    ".markdownlintrc": ("JSONC",   ("//",), (("/*", "*/"),)),
    ".prettierignore": ("ignore 文件", ("#",), ()),
    ".eslintignore":   ("ignore 文件", ("#",), ()),
    ".stylelintignore": ("ignore 文件", ("#",), ()),
    ".npmignore":      ("ignore 文件", ("#",), ()),
    ".helmignore":     ("ignore 文件", ("#",), ()),
    ".ignore":         ("ignore 文件", ("#",), ()),
    ".codeowners":     ("ignore 文件", ("#",), ()),
    "codeowners":      ("ignore 文件", ("#",), ()),
    # 无扩展名的"本来就是纯文本"：登记成纯文本，免得被成分表页的
    # 「未识别扩展名」提示当成"没认出来的格式"反复报出来
    "license":      ("纯文本", (), ()),
    "licence":      ("纯文本", (), ()),
    "copying":      ("纯文本", (), ()),
    "notice":       ("纯文本", (), ()),
    "authors":      ("纯文本", (), ()),
    "contributors": ("纯文本", (), ()),
    "patents":      ("纯文本", (), ()),
    "thanks":       ("纯文本", (), ()),
    "maintainers":  ("纯文本", (), ()),
    "version":      ("纯文本", (), ()),
    "install":      ("纯文本", (), ()),
    "changelog":    ("纯文本", (), ()),
    "todo":         ("纯文本", (), ()),
    "readme":       ("纯文本", (), ()),
}

# 纯文本扩展名：能算行数，但没有注释语法（非空行一律算代码）。
# 这里放的是"**本来就是**纯文本"的类型 —— 与"我们没认出来"是两回事，
# 成分表页的「未识别扩展名」提示靠这个集合区分二者。
PLAIN_TEXT_EXT = {
    ".txt", ".text", ".log", ".csv", ".tsv",
    ".lock", ".sum", ".mod", ".map", ".diff", ".patch",
    ".tsbuildinfo", ".code-workspace", ".example", ".ignore",
    ".sha1", ".sha256", ".md5",
}

PLAIN_TEXT_LANG = "纯文本"

# 以点开头的"点文件"前缀规则（这些文件名后缀随意，逐个列举不完）
DOT_NAME_PREFIXES = (".env",)


def get_spec(path):
    """返回 (语言名, 行注释前缀, 块注释对)；未知类型按纯文本处理。"""
    name = os.path.basename(path).lower()
    if name in FILENAMES:
        return FILENAMES[name]
    for prefix in DOT_NAME_PREFIXES:
        if name.startswith(prefix):
            return ("env", ("#",), ())
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


def all_language_names():
    """表里出现过的全部语言名（含特殊文件名的取值与兜底的纯文本），供自检使用。"""
    names = {value[0] for value in LANGS.values()}
    names |= {value[0] for value in FILENAMES.values()}
    names.add("env")              # 点文件前缀规则产生的语言名
    names.add(PLAIN_TEXT_LANG)    # 未识别 / 本来就是纯文本时的兜底语言名
    return names