#!/usr/bin/env python3
"""Render the default Telegram bot banners: cartoon corgi Lusi + a readable section title.

Each banner is an SVG scene (1280x640) rendered by Chromium (Playwright) and saved as JPEG
into backend/app/assets/bot_banners/<key>.jpg. The bot uses these files when the
administrator has not uploaded an own image for the section.

    python3 scripts/bot-banners/render.py            # all banners
    python3 scripts/bot-banners/render.py start buy  # selected ones
    python3 scripts/bot-banners/render.py --svg      # also keep SVG sources next to the JPEGs

Titles and colours live in SECTIONS below; the font is Rubik Black (SIL OFL, fonts/).
"""
import base64
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "backend/app/assets/bot_banners"
W, H, BAND = 1280, 640, 472

O = "#3a2413"        # outline
FUR = "#f39a3d"
FUR_D = "#d9782a"
CREAM = "#fff4e2"
PINK = "#f7a1a0"
DARK = "#2b1a10"

# key: (title, accent, prop, pose)
SECTIONS = {
    "start": ("ДОБРО ПОЖАЛОВАТЬ", "#ffc24b", "stars", "wave"),
    "menu": ("МЕНЮ", "#8ab4ff", "menu", "sit"),
    "buy": ("ТАРИФЫ", "#ffd166", "plans", "sit"),
    "subscription": ("ПОДПИСКА", "#4ade80", "shield", "sit"),
    "promo": ("ПРОМОКОД", "#ff6bcb", "coupon", "sit"),
    "account": ("МОЙ КАБИНЕТ", "#60a5fa", "idcard", "sit"),
    "balance": ("КОШЕЛЁК", "#34d399", "wallet", "sit"),
    "payments": ("ПЛАТЕЖИ", "#a78bfa", "receipt", "sit"),
    "gifts": ("ПОДАРКИ", "#ff7a7a", "gift", "sit"),
    "referral": ("ПРИГЛАСИ ДРУЗЕЙ", "#fb7185", "friends", "wave"),
    "support": ("ПОДДЕРЖКА", "#38bdf8", "chat", "headset"),
    "devices": ("УСТРОЙСТВА", "#22d3ee", "devices", "sit"),
    "surveys": ("ОПРОСЫ", "#facc15", "clipboard", "sit"),
    # Mini App sections
    "home": ("ГЛАВНАЯ", "#39ff88", "house", "wave"),
    "topup": ("ПОПОЛНЕНИЕ БАЛАНСА", "#39ff88", "topup", "sit"),
    "trial": ("ПРОБНЫЙ ПЕРИОД", "#a3e635", "hourglass", "sit"),
    "connection": ("ПОДКЛЮЧЕНИЕ", "#2dd4bf", "qr", "sit"),
    "servers": ("СЕРВЕРЫ", "#60a5fa", "globe", "sit"),
    "info": ("ИНФОРМАЦИЯ", "#c084fc", "book", "sit"),
}


def S(w=6):
    return f'stroke="{O}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'


def corgi(pose: str, accent: str) -> str:
    """Corgi Lusi, head centre at (0,0); ears reach y=-210, body continues below y=300."""
    ear = (f'<path d="M-92 -38 C-122 -110 -126 -172 -106 -204 C-96 -216 -80 -212 -70 -200 C-40 -162 -16 -122 -6 -96 Z" fill="{FUR}" {S()}/>'
           f'<path d="M-86 -56 C-104 -110 -108 -158 -98 -184 C-76 -158 -52 -126 -36 -100 Z" fill="{PINK}"/>')
    tuft = (f'<path d="M-137 14 L-153 26 L-138 36 L-150 52 L-128 56 L-134 70 L-112 72" fill="{FUR}" {S(5)}/>')
    body = (f'<path d="M-112 78 C-142 150 -152 230 -152 320 L152 320 C152 230 142 150 112 78 Z" fill="{FUR}" {S()}/>'
            f'<path d="M-70 96 C-40 122 40 122 70 96 C96 160 92 240 74 320 L-74 320 C-92 240 -96 160 -70 96 Z" fill="{CREAM}"/>'
            f'<path d="M-118 150 C-128 200 -132 250 -132 320" fill="none" stroke="{FUR_D}" stroke-width="5" opacity=".6"/>'
            f'<path d="M118 150 C128 200 132 250 132 320" fill="none" stroke="{FUR_D}" stroke-width="5" opacity=".6"/>')
    scarf = (f'<path d="M-102 90 C-52 126 52 126 102 90 L98 114 C52 150 -52 150 -98 114 Z" fill="{accent}" {S(5)}/>'
             f'<path d="M-34 128 L34 128 L0 178 Z" fill="{accent}" {S(5)}/>'
             f'<circle cx="0" cy="150" r="15" fill="#ffd54a" {S(4)}/>'
             f'<text x="0" y="157" text-anchor="middle" font-family="Banner" font-size="18" fill="{O}">L</text>')
    head = (f'<path d="M-140 8 C-146 -72 -86 -122 0 -122 C86 -122 146 -72 140 8 C138 72 80 112 0 114 C-80 112 -138 72 -140 8 Z" fill="{FUR}" {S()}/>'
            f'<path d="M-15 -120 C-6 -123 6 -123 15 -120 L22 -32 C60 -22 100 8 104 50 C100 92 56 113 0 114 C-56 113 -100 92 -104 50 C-100 8 -60 -22 -22 -32 Z" fill="{CREAM}"/>'
            f'<path d="M-140 8 C-146 -72 -86 -122 0 -122 C86 -122 146 -72 140 8 C138 72 80 112 0 114 C-80 112 -138 72 -140 8 Z" fill="none" {S()}/>'
            f'<ellipse cx="-56" cy="-64" rx="13" ry="7" transform="rotate(-18 -56 -64)" fill="{CREAM}"/>'
            f'<ellipse cx="56" cy="-64" rx="13" ry="7" transform="rotate(18 56 -64)" fill="{CREAM}"/>')
    eyes = ''.join(
        f'<ellipse cx="{x}" cy="-18" rx="21" ry="26" fill="{DARK}"/>'
        f'<circle cx="{x + 7}" cy="-28" r="8" fill="#fff"/><circle cx="{x - 6}" cy="-6" r="3.5" fill="#fff"/>'
        for x in (-52, 52))
    face = (eyes +
            f'<ellipse cx="-84" cy="32" rx="20" ry="11" fill="#ff8fa3" opacity=".6"/>'
            f'<ellipse cx="84" cy="32" rx="20" ry="11" fill="#ff8fa3" opacity=".6"/>'
            f'<path d="M-21 18 C-10 9 10 9 21 18 C23 32 9 41 0 43 C-9 41 -23 32 -21 18 Z" fill="{DARK}"/>'
            f'<ellipse cx="-6" cy="19" rx="7" ry="3.5" fill="#fff" opacity=".7"/>'
            f'<path d="M-11 58 C-13 84 13 84 11 58 Z" fill="#ff7b8a" {S(4)}/><path d="M0 62 L0 74" stroke="#d9505f" stroke-width="3"/>'
            f'<path d="M0 43 L0 53 M-26 50 C-17 65 -4 63 0 53 C4 63 17 65 26 50" fill="none" {S(5)}/>')
    paw = lambda x, y: (f'<ellipse cx="{x}" cy="{y}" rx="38" ry="30" fill="{CREAM}" {S(5)}/>'
                        f'<path d="M{x - 12} {y - 26} L{x - 12} {y - 12} M{x + 12} {y - 26} L{x + 12} {y - 12}" {S(4)}/>')
    parts = [ear, f'<g transform="scale(-1 1)">{ear}</g>', body, tuft, f'<g transform="scale(-1 1)">{tuft}</g>', head, face, scarf]
    if pose == "wave":
        parts.append(f'<path d="M98 118 C142 88 170 40 176 2 L232 22 C220 74 176 136 124 176 Z" fill="{FUR}" {S()}/>')
        parts.append(f'<ellipse cx="206" cy="4" rx="36" ry="30" transform="rotate(-20 206 4)" fill="{CREAM}" {S(5)}/>')
        parts.append(f'<path d="M248 -40 C262 -30 268 -16 268 0 M268 -70 C290 -52 300 -28 298 0" fill="none" stroke="{accent}" stroke-width="7" stroke-linecap="round"/>')
        parts.append(paw(-56, 220))
    else:
        parts.append(paw(-58, 220) + paw(58, 220))
    if pose == "headset":
        parts.insert(5, '')
        parts.append(f'<path d="M-128 -20 C-128 -150 128 -150 128 -20" fill="none" stroke="{O}" stroke-width="16" stroke-linecap="round"/>'
                     f'<path d="M-128 -20 C-128 -150 128 -150 128 -20" fill="none" stroke="#5b6b8c" stroke-width="9" stroke-linecap="round"/>'
                     f'<rect x="-160" y="-46" width="42" height="74" rx="18" fill="{accent}" {S(5)}/>'
                     f'<rect x="118" y="-46" width="42" height="74" rx="18" fill="{accent}" {S(5)}/>'
                     f'<path d="M-140 26 C-140 80 -90 96 -40 92" fill="none" stroke="{O}" stroke-width="8" stroke-linecap="round"/>'
                     f'<circle cx="-36" cy="92" r="11" fill="#5b6b8c" {S(4)}/>')
    return "".join(parts)


def prop(kind: str, a: str) -> str:
    """Section prop drawn around (0,0) in a ~240px box."""
    w = S(6)
    if kind == "stars":
        star = lambda x, y, r, c: f'<path d="{star_path(x, y, r)}" fill="{c}" {S(5)}/>'
        return star(0, -20, 70, a) + star(-95, 70, 38, "#fff3b0") + star(90, 90, 30, "#ffe08a")
    if kind == "menu":
        rows = "".join(f'<rect x="-62" y="{y}" width="124" height="22" rx="11" fill="{c}" {S(4)}/>'
                       for y, c in ((-64, a), (-16, "#dbe6ff"), (32, "#dbe6ff")))
        return f'<rect x="-100" y="-110" width="200" height="220" rx="30" fill="#24314f" {w}/>' + rows
    if kind == "plans":
        out = ""
        for i, (lbl, h, c) in enumerate((("1", 120, "#ffe9a8"), ("3", 165, "#ffd166"), ("12", 210, a))):
            x = -110 + i * 78
            out += f'<rect x="{x}" y="{100 - h}" width="68" height="{h}" rx="14" fill="{c}" {S(5)}/>'
            out += f'<text x="{x + 34}" y="{100 - h + 46}" text-anchor="middle" font-family="Banner" font-size="34" fill="{O}">{lbl}</text>'
        return out + f'<path d="{star_path(70, -150, 34)}" fill="#fff3b0" {S(5)}/>'
    if kind == "shield":
        return (f'<path d="M0 -120 L105 -80 C105 20 70 90 0 125 C-70 90 -105 20 -105 -80 Z" fill="{a}" {w}/>'
                f'<path d="M0 -92 L78 -62 C78 10 52 64 0 94 Z" fill="#fff" opacity=".25"/>'
                f'<path d="M-45 0 L-12 34 L50 -36" fill="none" stroke="#fff" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<path d="M-45 0 L-12 34 L50 -36" fill="none" stroke="{O}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" opacity=".0"/>')
    if kind == "coupon":
        return (f'<g transform="rotate(-12)"><path d="M-130 -70 H130 V-22 A22 22 0 0 0 130 22 V70 H-130 V22 A22 22 0 0 0 -130 -22 Z" fill="{a}" {w}/>'
                f'<path d="M-50 -60 V60" stroke="{O}" stroke-width="5" stroke-dasharray="12 10"/>'
                f'<text x="45" y="30" text-anchor="middle" font-family="Banner" font-size="92" fill="#fff" stroke="{O}" stroke-width="5" paint-order="stroke">%</text>'
                f'<circle cx="-90" cy="0" r="16" fill="#fff" {S(4)}/></g>')
    if kind == "idcard":
        return (f'<rect x="-130" y="-85" width="260" height="170" rx="22" fill="#eaf2ff" {w}/>'
                f'<rect x="-130" y="-85" width="260" height="44" rx="22" fill="{a}" {S(5)}/>'
                f'<circle cx="-62" cy="18" r="36" fill="{FUR}" {S(5)}/><path d="M-80 0 L-92 -30 L-66 -10 Z M-44 0 L-32 -30 L-58 -10 Z" fill="{FUR}" {S(4)}/>'
                f'<circle cx="-72" cy="14" r="5" fill="{DARK}"/><circle cx="-52" cy="14" r="5" fill="{DARK}"/>'
                f'<rect x="0" y="-8" width="100" height="16" rx="8" fill="#9fb4d8"/><rect x="0" y="22" width="76" height="16" rx="8" fill="#c7d5ec"/>')
    if kind == "wallet":
        coin = lambda x, y, r: (f'<circle cx="{x}" cy="{y}" r="{r}" fill="#ffd54a" {S(5)}/>'
                                f'<circle cx="{x}" cy="{y}" r="{r * .66:.0f}" fill="none" stroke="#e0a800" stroke-width="5"/>'
                                f'<path d="M{x} {y - r * .35:.0f} V{y + r * .35:.0f}" stroke="#e0a800" stroke-width="7" stroke-linecap="round"/>')
        return (f'<rect x="-120" y="-50" width="240" height="160" rx="26" fill="{a}" {w}/>'
                f'<path d="M-120 -10 H120" stroke="{O}" stroke-width="5" opacity=".35"/>'
                f'<rect x="50" y="10" width="86" height="56" rx="18" fill="#bff3dc" {S(5)}/><circle cx="80" cy="38" r="10" fill="{O}"/>'
                + coin(-40, -90, 40) + coin(40, -130, 32) + coin(110, -80, 26))
    if kind == "receipt":
        zig = " ".join(f"L{x} {100 if i % 2 == 0 else 120}" for i, x in enumerate(range(80, -81, -20)))
        return (f'<path d="M-90 -120 H90 V100 {zig} Z" fill="#f4f0ff" {w}/>'
                + "".join(f'<rect x="-60" y="{y}" width="{wd}" height="14" rx="7" fill="#c9bdf2"/>' for y, wd in ((-86, 120), (-56, 90), (-26, 110)))
                + f'<circle cx="40" cy="44" r="40" fill="{a}" {S(5)}/>'
                f'<path d="M20 44 L36 60 L62 30" fill="none" stroke="#fff" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>')
    if kind == "gift":
        return (f'<rect x="-110" y="-20" width="220" height="140" rx="16" fill="{a}" {w}/>'
                f'<rect x="-125" y="-62" width="250" height="52" rx="14" fill="#ff9b9b" {w}/>'
                f'<rect x="-20" y="-62" width="40" height="182" fill="#ffd54a" {S(5)}/>'
                f'<path d="M0 -62 C-30 -130 -110 -120 -80 -80 C-66 -62 -30 -62 0 -62 Z" fill="#ffd54a" {S(5)}/>'
                f'<path d="M0 -62 C30 -130 110 -120 80 -80 C66 -62 30 -62 0 -62 Z" fill="#ffd54a" {S(5)}/>')
    if kind == "friends":
        heart = lambda x, y, s, c: (f'<path transform="translate({x} {y}) scale({s})" d="M0 30 C-60 -10 -60 -60 -25 -60 C-10 -60 0 -48 0 -38 C0 -48 10 -60 25 -60 C60 -60 60 -10 0 30 Z" fill="{c}" {S(6 / s)}/>')
        return (heart(-20, 20, 2.1, a) + heart(95, -90, 0.9, "#ffc2cf")
                + f'<text x="-20" y="10" text-anchor="middle" font-family="Banner" font-size="64" fill="#fff" stroke="{O}" stroke-width="5" paint-order="stroke">+1</text>')
    if kind == "chat":
        return (f'<path d="M-120 -100 H120 A24 24 0 0 1 144 -76 V30 A24 24 0 0 1 120 54 H-20 L-70 100 L-60 54 H-120 A24 24 0 0 1 -144 30 V-76 A24 24 0 0 1 -120 -100 Z" fill="#eaf7ff" {w}/>'
                + "".join(f'<circle cx="{x}" cy="-24" r="18" fill="{a}" {S(4)}/>' for x in (-60, 0, 60)))
    if kind == "devices":
        return (f'<rect x="-150" y="-80" width="220" height="140" rx="14" fill="#1e2a44" {w}/>'
                f'<rect x="-136" y="-66" width="192" height="112" rx="6" fill="{a}" opacity=".85"/>'
                f'<path d="M-175 64 H95 L80 88 H-160 Z" fill="#9fb0cc" {w}/>'
                f'<rect x="70" y="-110" width="92" height="170" rx="18" fill="#1e2a44" {w}/>'
                f'<rect x="82" y="-92" width="68" height="128" rx="8" fill="#a5f3fc"/>'
                f'<path d="{star_path(-40, -10, 26)}" fill="#fff"/><circle cx="116" cy="46" r="6" fill="#9fb0cc"/>')
    if kind == "clipboard":
        rows = "".join(f'<rect x="-74" y="{y}" width="34" height="34" rx="8" fill="#fff" {S(4)}/>'
                       f'<path d="M-68 {y + 17} L-58 {y + 27} L-44 {y + 7}" fill="none" stroke="{O}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
                       f'<rect x="-28" y="{y + 10}" width="96" height="14" rx="7" fill="#e7d79c"/>' for y in (-60, -6, 48))
        return (f'<rect x="-105" y="-118" width="210" height="240" rx="22" fill="{a}" {w}/>'
                f'<rect x="-90" y="-90" width="180" height="198" rx="12" fill="#fffbe8"/>'
                f'<rect x="-44" y="-136" width="88" height="40" rx="12" fill="#9fb0cc" {S(5)}/>' + rows)
    if kind == "house":
        return (f'<path d="M-120 -10 L0 -120 L120 -10" fill="none" stroke="{O}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<path d="M-120 -10 L0 -120 L120 -10" fill="none" stroke="{a}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<rect x="-95" y="-20" width="190" height="135" rx="14" fill="#e9fff3" {w}/>'
                f'<rect x="-28" y="30" width="56" height="85" rx="10" fill="{a}" {S(5)}/>'
                f'<rect x="-80" y="5" width="40" height="36" rx="8" fill="#bdf7d6" {S(4)}/><rect x="40" y="5" width="40" height="36" rx="8" fill="#bdf7d6" {S(4)}/>'
                f'<path d="M0 -70 C-14 -86 -36 -76 -28 -58 L0 -34 L28 -58 C36 -76 14 -86 0 -70 Z" fill="#ff8fa3" {S(4)}/>')
    if kind == "topup":
        coin = lambda x, y, r: (f'<circle cx="{x}" cy="{y}" r="{r}" fill="#ffd54a" {S(5)}/>'
                                f'<circle cx="{x}" cy="{y}" r="{r * .66:.0f}" fill="none" stroke="#e0a800" stroke-width="5"/>')
        return (f'<rect x="-120" y="-40" width="210" height="150" rx="26" fill="#1f2b45" {w}/>'
                f'<rect x="-104" y="-24" width="178" height="40" rx="10" fill="{a}" opacity=".9"/>'
                f'<rect x="-104" y="40" width="80" height="14" rx="7" fill="#8fa3c7"/><rect x="-104" y="66" width="120" height="14" rx="7" fill="#5f7398"/>'
                + coin(90, -80, 36) + coin(30, -120, 26) +
                f'<circle cx="105" cy="70" r="44" fill="{a}" {S(6)}/>'
                f'<path d="M105 48 V92 M83 70 H127" stroke="#0b1220" stroke-width="12" stroke-linecap="round"/>')
    if kind == "hourglass":
        return (f'<rect x="-80" y="-120" width="160" height="26" rx="12" fill="{a}" {w}/>'
                f'<rect x="-80" y="94" width="160" height="26" rx="12" fill="{a}" {w}/>'
                f'<path d="M-62 -94 H62 C62 -40 14 -16 14 0 C14 16 62 40 62 94 H-62 C-62 40 -14 16 -14 0 C-14 -16 -62 -40 -62 -94 Z" fill="#effee0" {w}/>'
                f'<path d="M-40 -70 H40 C34 -44 10 -28 0 -16 C-10 -28 -34 -44 -40 -70 Z" fill="#ffd54a"/>'
                f'<path d="M-44 86 C-40 60 -14 44 0 40 C14 44 40 60 44 86 Z" fill="#ffd54a"/>'
                f'<path d="M0 -10 V36" stroke="#e0a800" stroke-width="5" stroke-dasharray="6 8"/>'
                f'<path d="{star_path(95, -90, 26)}" fill="#fff3b0" {S(4)}/>')
    if kind == "qr":
        cells = "".join(f'<rect x="{-58 + (i % 6) * 20}" y="{-58 + (i // 6) * 20}" width="16" height="16" rx="3" fill="{O}"/>'
                        for i in (2, 3, 8, 9, 14, 16, 19, 20, 21, 26, 27, 32, 33, 35))
        finder = lambda x, y: (f'<rect x="{x}" y="{y}" width="44" height="44" rx="8" fill="none" stroke="{O}" stroke-width="8"/>'
                               f'<rect x="{x + 14}" y="{y + 14}" width="16" height="16" rx="3" fill="{O}"/>')
        return (f'<rect x="-100" y="-100" width="200" height="200" rx="26" fill="#f0fffc" {w}/>'
                + finder(-80, -80) + finder(36, -80) + finder(-80, 36) + cells +
                f'<circle cx="92" cy="92" r="40" fill="{a}" {S(6)}/>'
                f'<path d="M78 80 V96 M106 80 V96 M70 96 H114 V104 C114 116 104 124 92 124 C80 124 70 116 70 104 Z" fill="#0b1220" stroke="#0b1220" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>')
    if kind == "globe":
        pin = lambda x, y, c: (f'<path d="M{x} {y + 30} C{x - 22} {y + 4} {x - 22} {y - 22} {x} {y - 22} C{x + 22} {y - 22} {x + 22} {y + 4} {x} {y + 30} Z" fill="{c}" {S(4)}/>'
                               f'<circle cx="{x}" cy="{y - 4}" r="7" fill="#fff"/>')
        return (f'<circle cx="0" cy="0" r="112" fill="#1e3a8a" {w}/>'
                f'<path d="M-70 -60 C-30 -80 0 -50 -20 -20 C-40 10 -90 0 -96 -30 Z M10 20 C50 0 90 30 70 70 C50 100 10 80 0 50 Z M30 -96 C60 -90 90 -60 80 -40 C60 -50 30 -60 30 -96 Z" fill="{a}" opacity=".85"/>'
                f'<ellipse cx="0" cy="0" rx="112" ry="40" fill="none" stroke="#9ec5ff" stroke-width="4" opacity=".6"/>'
                f'<ellipse cx="0" cy="0" rx="45" ry="112" fill="none" stroke="#9ec5ff" stroke-width="4" opacity=".6"/>'
                + pin(-40, -50, "#ff7a7a") + pin(50, 30, "#ffd54a") + pin(70, -70, "#39ff88"))
    if kind == "book":
        return (f'<path d="M0 -80 C-40 -104 -96 -104 -124 -90 V96 C-96 82 -40 82 0 106 Z" fill="#f6efff" {w}/>'
                f'<path d="M0 -80 C40 -104 96 -104 124 -90 V96 C96 82 40 82 0 106 Z" fill="#ede0ff" {w}/>'
                + "".join(f'<path d="M-100 {y} C-70 {y - 10} -40 {y - 10} -20 {y}" stroke="#c9b4f2" stroke-width="8" fill="none" stroke-linecap="round"/>' for y in (-50, -20, 10, 40))
                + f'<circle cx="62" cy="0" r="40" fill="{a}" {S(6)}/>'
                f'<circle cx="62" cy="-18" r="7" fill="#fff"/><rect x="55" y="-4" width="14" height="34" rx="7" fill="#fff"/>')
    raise KeyError(kind)


def star_path(cx, cy, r):
    import math
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.45
        ang = -math.pi / 2 + i * math.pi / 5
        pts.append(f"{cx + rad * math.cos(ang):.1f} {cy + rad * math.sin(ang):.1f}")
    return "M" + " L".join(pts) + " Z"


def font_face() -> str:
    faces = []
    for name in ("rubik-cyrillic-900-normal.woff2", "rubik-latin-900-normal.woff2"):
        data = base64.b64encode((HERE / "fonts" / name).read_bytes()).decode()
        rng = "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116" if "cyrillic" in name else "U+0000-00FF,U+2000-206F,U+20AC,U+20BD"
        faces.append(f"@font-face{{font-family:Banner;font-weight:900;src:url(data:font/woff2;base64,{data}) format('woff2');unicode-range:{rng}}}")
    return "".join(faces)


def scene(key: str) -> str:
    title, accent, kind, pose = SECTIONS[key]
    sparkles = "".join(
        f'<path d="{star_path(x, y, r)}" fill="{accent}" opacity="{op}"/>'
        for x, y, r, op in ((90, 80, 14, .7), (190, 330, 9, .5), (1180, 70, 12, .6), (1120, 380, 9, .5), (330, 60, 7, .5), (980, 40, 8, .5)))
    paws = "".join(
        f'<g transform="translate({x} {y}) rotate({r})" fill="{accent}" opacity=".13"><ellipse cx="0" cy="12" rx="22" ry="18"/>'
        f'<circle cx="-22" cy="-14" r="9"/><circle cx="-7" cy="-24" r="9"/><circle cx="9" cy="-24" r="9"/><circle cx="24" cy="-14" r="9"/></g>'
        for x, y, r in ((120, 210, -20), (260, 410, 15), (1150, 230, 20), (1010, 420, -10), (60, 400, 5)))
    prop_x, prop_y, scale = (900, 250, 1.05)
    if kind in ("stars",):
        prop_x, prop_y = 880, 230
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
  <style>{font_face()}</style>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#172038"/><stop offset="1" stop-color="#0f1528"/></linearGradient>
  <radialGradient id="glow" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{accent}" stop-opacity=".55"/><stop offset="1" stop-color="{accent}" stop-opacity="0"/></radialGradient>
  <filter id="neon" x="-20%" y="-60%" width="140%" height="220%"><feGaussianBlur stdDeviation="9" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="#000" flood-opacity=".45"/></filter>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<ellipse cx="640" cy="270" rx="430" ry="300" fill="url(#glow)"/>
<ellipse cx="{prop_x}" cy="{prop_y}" rx="210" ry="190" fill="url(#glow)" opacity=".7"/>
{paws}{sparkles}
<g filter="url(#shadow)" transform="translate({prop_x} {prop_y}) scale({scale})">{prop(kind, accent)}</g>
<g filter="url(#shadow)" transform="translate(480 240) scale(.92)">{corgi(pose, accent)}</g>
<rect x="0" y="{BAND}" width="{W}" height="{H - BAND}" fill="#0a0e1a"/>
<rect x="0" y="{BAND}" width="{W}" height="6" fill="{accent}" filter="url(#neon)"/>
<text id="title" x="640" y="{BAND + 116}" text-anchor="middle" font-family="Banner" font-weight="900" font-size="112" letter-spacing="4"
  fill="{accent}" stroke="#0a0e1a" stroke-width="2" filter="url(#neon)">{title}</text>
</svg>'''


def main(argv):
    keep_svg = "--svg" in argv
    keys = [a for a in argv if not a.startswith("--")] or list(SECTIONS)
    OUT.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        for key in keys:
            svg = scene(key)
            if keep_svg:
                (OUT / f"{key}.svg").write_text(svg)
            page.set_content(f'<html><body style="margin:0;background:#000">{svg}</body></html>')
            page.evaluate("document.fonts.ready")
            # Fit long titles into the band with side margins.
            page.evaluate("""() => { const t=document.getElementById('title'); let s=112;
                while (t.getBBox().width > 1160 && s > 40) { s -= 2; t.setAttribute('font-size', s); } }""")
            page.locator("svg").screenshot(path=str(OUT / f"{key}.jpg"), type="jpeg", quality=88)
            print("rendered", key)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
