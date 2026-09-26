#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""八卦盘：点一下占卜今天适不适合写代码。

每日一签——结果用当天日期做随机种子，同一天重复点结果不变，跨天自动换。
转盘是纯 Canvas 画图（三圈爻线 + 阴阳鱼 + 指针），不写任何文件。
"""

import math
import random
import tkinter as tk
import tkinter.font as tkfont
from datetime import date
from tkinter import ttk

from share import fortune_texts

# 转盘尺寸与动画节奏
WHEEL_SIZE = 340
SPIN_TICKS = 26          # 转 26 拍，每拍延时递增，全程约 3 秒
BASE_DELAY_MS = 30
DELAY_STEP_MS = 6

# 先天八卦：(卦名, 三爻)。爻从内到外：1 实线 / 0 断线
TRIGRAMS = (
    ("乾", (1, 1, 1)),
    ("兑", (1, 1, 0)),
    ("离", (1, 0, 1)),
    ("震", (1, 0, 0)),
    ("坤", (0, 0, 0)),
    ("艮", (0, 0, 1)),
    ("坎", (0, 1, 0)),
    ("巽", (0, 1, 1)),
)

INK = "#4a3b2a"
GOLD = "#c9a227"
PAPER = "#f7f2e4"
RED = "#c0392b"


class BaguaTab(ttk.Frame):
    """八卦盘标签页：每日一签，纯本地随机，不写任何文件。"""

    def __init__(self, master):
        super().__init__(master)
        self._fonts = {}
        self._wheel_angle = 0.0
        self._after_id = None
        self._tick = 0
        self.spinning = False
        # 每日一签：同一天的种子相同，结果也就相同
        self.rng = random.Random(f"八卦盘/{date.today():%Y-%m-%d}")
        self.target_net = self.rng.choice(fortune_texts.NETWORK_FORECASTS)
        self.target_code = self.rng.choice(fortune_texts.CODE_FORECASTS)
        self.target_advice = self.rng.choice(fortune_texts.DAILY_ADVICE)
        self.build_fonts()
        self.build_ui()

    # ==================== 界面 ====================
    def build_fonts(self):
        base = tkfont.nametofont("TkDefaultFont")
        family = base.cget("family")
        size = base.cget("size")
        step = 1 if size > 0 else -1

        def make(key, delta, weight="normal"):
            self._fonts[key] = tkfont.Font(family=family, size=size + step * delta,
                                           weight=weight)

        make("title", 6, "bold")
        make("weather", 3, "bold")
        make("gua", 3, "bold")
        make("body", 0)
        make("small", -1)

    def build_ui(self):
        head = ttk.Frame(self)
        head.pack(fill=tk.X, pady=(14, 0))
        ttk.Label(head, text="八卦盘 · 今日写码运势", font=self._fonts["title"],
                  anchor="center").pack(fill=tk.X)
        ttk.Label(head, text=f"{date.today():%Y年%m月%d日} · 每日一签（今天内结果固定）",
                  font=self._fonts["small"], anchor="center").pack(fill=tk.X)

        self.wheel = tk.Canvas(self, width=WHEEL_SIZE, height=WHEEL_SIZE,
                               highlightthickness=0, background=PAPER)
        self.wheel.pack(pady=(6, 0))
        self._draw_wheel()

        self.btn = ttk.Button(self, text="开始占卜", width=14, command=self.start_divination)
        self.btn.pack(pady=8)

        cards = ttk.Frame(self)
        cards.pack(fill=tk.X, padx=20)
        self.build_card(cards, "网络风险天气", "#1677ff", "net")
        self.build_card(cards, "代码屎山天气", "#8a6d3b", "code")

        self.var_advice = tk.StringVar(value=" ")
        ttk.Label(self, textvariable=self.var_advice, font=self._fonts["weather"],
                  foreground=RED, anchor="center").pack(fill=tk.X, pady=(12, 4))

    def build_card(self, parent, title, color, key):
        card = ttk.LabelFrame(parent, text=title, padding=(12, 8))
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8)
        weather = tk.StringVar(value="——")
        text = tk.StringVar(value="点「开始占卜」，看看今天写代码的运势")
        setattr(self, f"var_{key}_weather", weather)
        setattr(self, f"var_{key}_text", text)
        ttk.Label(card, textvariable=weather, font=self._fonts["weather"],
                  foreground=color, anchor="center").pack(fill=tk.X, pady=(0, 6))
        ttk.Label(card, textvariable=text, wraplength=380, justify=tk.CENTER,
                  anchor="center").pack(fill=tk.X)

    # ==================== 八卦盘绘制 ====================
    def _draw_wheel(self):
        """按当前角度重画转盘：三圈爻线 + 阴阳鱼 + 指针 + 卦名。"""
        c = self.wheel
        c.delete("all")
        cx = cy = WHEEL_SIZE // 2
        r_rim = 150

        c.create_oval(cx - r_rim, cy - r_rim, cx + r_rim, cy + r_rim,
                      fill=PAPER, outline=GOLD, width=3)

        # 三圈爻线：内圈是初爻，外圈是上爻；实线一根、断线两截
        for ring, (radius, band) in enumerate(((62, 14), (100, 14), (138, 14))):
            for index, (_name, lines) in enumerate(TRIGRAMS):
                start = self._wheel_angle + index * 45 + 4
                bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
                if lines[ring]:
                    c.create_arc(*bbox, start=start, extent=39, style="arc",
                                 outline=INK, width=band)
                else:
                    c.create_arc(*bbox, start=start, extent=14, style="arc",
                                 outline=INK, width=band)
                    c.create_arc(*bbox, start=start + 25, extent=14, style="arc",
                                 outline=INK, width=band)

        # 阴阳鱼
        c.create_oval(cx - 46, cy - 46, cx + 46, cy + 46,
                      fill=PAPER, outline=INK, width=2)
        c.create_arc(cx - 46, cy - 46, cx + 46, cy + 46, start=90, extent=180,
                     style="pieslice", fill=INK, outline="")
        c.create_oval(cx - 36, cy - 12, cx - 10, cy + 12, fill=PAPER, outline=INK)
        c.create_oval(cx + 10, cy - 12, cx + 36, cy + 12, fill=INK, outline=INK)

        # 指针与卦名
        c.create_polygon(cx - 10, cy - r_rim - 22, cx + 10, cy - r_rim - 22,
                         cx, cy - r_rim + 2, fill=RED)
        for index, (name, _lines) in enumerate(TRIGRAMS):
            a = math.radians(self._wheel_angle + index * 45 - 90)
            x = cx + (r_rim + 20) * math.cos(a)
            y = cy + (r_rim + 20) * math.sin(a)
            c.create_text(x, y, text=name, font=self._fonts["gua"], fill=INK)

    # ==================== 占卜 ====================
    def start_divination(self):
        if self.spinning:
            return          # 转动中再点无效，防止定时器叠加
        self.spinning = True
        self._tick = 0
        self.btn.configure(state="disabled", text="占卜中…")
        self.var_advice.set(" ")
        self._spin_tick()

    def _spin_tick(self):
        self._tick += 1
        delay = BASE_DELAY_MS + self._tick * DELAY_STEP_MS
        self._wheel_angle = (self._wheel_angle + max(40 - self._tick * 2, 8)) % 360
        self._draw_wheel()

        # 转动中卡片快滚的是随机假内容；定格结果在开始占卜时就已抽定
        net = random.choice(fortune_texts.NETWORK_FORECASTS)
        code = random.choice(fortune_texts.CODE_FORECASTS)
        self.var_net_weather.set(net[0])
        self.var_net_text.set(net[1])
        self.var_code_weather.set(code[0])
        self.var_code_text.set(code[1])

        if self._tick >= SPIN_TICKS:
            self._land()
            return
        self._after_id = self.after(delay, self._spin_tick)

    def _land(self):
        self.spinning = False
        self.btn.configure(state="normal", text="再占一卦")
        for key, target in (("net", self.target_net), ("code", self.target_code)):
            getattr(self, f"var_{key}_weather").set(target[0])
            getattr(self, f"var_{key}_text").set(target[1])
        self.var_advice.set(self.target_advice)
