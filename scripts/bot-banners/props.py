"""Flat sticker props for the bot banners (drawn around (0,0) in a ~240px box)."""
import math

O = "#3a2413"        # outline
FUR = "#f39a3d"
CREAM = "#fff4e2"
DARK = "#2b1a10"


def S(w=6):
    return f'stroke="{O}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'


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
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.45
        ang = -math.pi / 2 + i * math.pi / 5
        pts.append(f"{cx + rad * math.cos(ang):.1f} {cy + rad * math.sin(ang):.1f}")
    return "M" + " L".join(pts) + " Z"


