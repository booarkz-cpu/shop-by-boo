#!/usr/bin/env python3
"""Render the default banners of the bot and the Mini App: corgi Lusi on a sunny terrace.

Style follows the brand artwork (source/corgi-lusi-original.png): the painted corgi Lusi,
a soft sunny background, a white brush-stroke label "Корги Люси · Свободный Гав!", a yellow
brush ribbon with the section title in a hand-lettered font, sticker props with a white
outline, a speech bubble, hearts and paw prints.

Inputs (prepared once by scripts/bot-banners/prepare.py from the original artwork):
  source/lusi-cutout.png  — the corgi without background and lettering
  source/background.jpg   — the same scene without the corgi and lettering, blurred
Output: backend/app/assets/bot_banners/<key>.jpg (1280x640) and the copies the Mini App
bundles in cabinet/public/assets/banners/.

    python3 scripts/bot-banners/render.py            # all banners
    python3 scripts/bot-banners/render.py start buy  # selected ones
    python3 scripts/bot-banners/render.py --svg      # also keep the SVG sources

Fonts: Balsamiq Sans Bold (SIL OFL, fonts/). Needs Python Playwright with Chromium.
"""
import base64
import math
import pathlib
import random
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from props import prop  # noqa: E402

OUT = ROOT / "backend/app/assets/bot_banners"
MINIAPP = ROOT / "cabinet/public/assets/banners"
W, H = 1280, 640
INK = "#1b1d2a"
YELLOW = "#ffc83d"
YELLOW_LIGHT = "#ffe27a"

# key: (title on the ribbon, speech bubble, prop, prop accent)
SECTIONS = {
    "start": ("Добро пожаловать!", "Гав-гав!", "stars", "#ffc24b"),
    "menu": ("Меню", "Выбирай!", "menu", "#8ab4ff"),
    "buy": ("Тарифы", "Выгодно!", "plans", "#ffd166"),
    "subscription": ("Подписка", "Под защитой!", "shield", "#4ade80"),
    "promo": ("Промокод", "Скидка!", "coupon", "#ff6bcb"),
    "account": ("Мой кабинет", "Это ты!", "idcard", "#60a5fa"),
    "balance": ("Кошелёк", "Звяк-звяк!", "wallet", "#34d399"),
    "payments": ("Платежи", "Всё учтено!", "receipt", "#a78bfa"),
    "gifts": ("Подарки", "Сюрприз!", "gift", "#ff7a7a"),
    "referral": ("Пригласи друзей", "Вместе веселее!", "friends", "#fb7185"),
    "support": ("Поддержка", "Помогу!", "chat", "#38bdf8"),
    "devices": ("Устройства", "Везде со мной!", "devices", "#22d3ee"),
    "surveys": ("Опросы", "Твоё мнение?", "clipboard", "#facc15"),
    "home": ("Главная", "Привет!", "house", "#4ade80"),
    "topup": ("Пополнение баланса", "СБП, карта, Stars", "topup", "#34d399"),
    "trial": ("Пробный период", "Попробуй!", "hourglass", "#a3e635"),
    "connection": ("Подключение", "За минуту!", "qr", "#2dd4bf"),
    "servers": ("Серверы", "Весь мир!", "globe", "#60a5fa"),
    "info": ("Информация", "Всё честно!", "book", "#c084fc"),
}


def data_uri(path: pathlib.Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def font_face() -> str:
    faces = []
    for name, rng in (("balsamiq-sans-cyrillic-700-normal.woff2", "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116"),
                      ("balsamiq-sans-latin-700-normal.woff2", "U+0000-00FF,U+2000-206F,U+20AC,U+20BD")):
        faces.append(f"@font-face{{font-family:Hand;font-weight:700;src:url({data_uri(HERE / 'fonts' / name, 'font/woff2')}) format('woff2');unicode-range:{rng}}}")
    return "".join(faces)


def brush(x: float, y: float, w: float, h: float, fill: str, seed: int, streaks: str = "") -> str:
    """A painted brush stroke: wobbly long edges, ragged bristle ends, dry streaks."""
    rnd = random.Random(seed)
    top, bottom = [], []
    steps = 14
    for i in range(steps + 1):
        px = x + w * i / steps
        top.append((px, y + rnd.uniform(-h * .06, h * .06)))
        bottom.append((px, y + h + rnd.uniform(-h * .06, h * .06)))
    def end(xe, direction):
        pts = []
        for j in range(7):
            py = y + h * (j + .5) / 7
            reach = rnd.uniform(h * .18, h * .4) if j % 2 == 0 else rnd.uniform(0, h * .1)
            pts.append((xe + direction * reach, py))
        return pts
    right = end(x + w, 1)
    left = end(x, -1)[::-1]
    pts = top + right + bottom[::-1] + left
    d = smooth(pts)
    out = f'<path d="{d}" fill="{fill}"/>'
    if streaks:
        for _ in range(5):
            sy = y + rnd.uniform(h * .1, h * .9)
            sx = x + w - rnd.uniform(0, w * .3)
            out += f'<path d="M{sx:.0f} {sy:.0f} l{rnd.uniform(h*.4, h*.9):.0f} {rnd.uniform(-6, 6):.0f}" stroke="{streaks}" stroke-width="{rnd.uniform(3, 7):.0f}" stroke-linecap="round" opacity=".85"/>'
            sx = x + rnd.uniform(0, w * .3)
            out += f'<path d="M{sx:.0f} {sy:.0f} l{-rnd.uniform(h*.3, h*.8):.0f} {rnd.uniform(-6, 6):.0f}" stroke="{streaks}" stroke-width="{rnd.uniform(3, 6):.0f}" stroke-linecap="round" opacity=".8"/>'
    return out


def smooth(pts) -> str:
    """Closed Catmull-Rom spline through the points: soft, painted-looking edges."""
    n = len(pts)
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d + " Z"


def paw(cx: float, cy: float, r: float, color: str, rot: float = 0, sticker: bool = False) -> str:
    toes = "".join(f'<ellipse cx="{dx * r:.1f}" cy="{dy * r:.1f}" rx="{r * .26:.1f}" ry="{r * .32:.1f}" transform="rotate({a} {dx * r:.1f} {dy * r:.1f})"/>'
                   for dx, dy, a in ((-.62, -.42, -20), (-.22, -.78, -6), (.22, -.78, 6), (.62, -.42, 20)))
    shape = f'<g fill="{color}">{toes}<path d="M0 {-.18 * r:.1f} C{.55 * r:.1f} {-.18 * r:.1f} {.72 * r:.1f} {.45 * r:.1f} {.42 * r:.1f} {.62 * r:.1f} C{.2 * r:.1f} {.74 * r:.1f} {-.2 * r:.1f} {.74 * r:.1f} {-.42 * r:.1f} {.62 * r:.1f} C{-.72 * r:.1f} {.45 * r:.1f} {-.55 * r:.1f} {-.18 * r:.1f} 0 {-.18 * r:.1f} Z"/></g>'
    filt = ' filter="url(#sticker)"' if sticker else ""
    return f'<g transform="translate({cx} {cy}) rotate({rot})"{filt}>{shape}</g>'


def heart(cx: float, cy: float, s: float, color: str, rot: float = 0) -> str:
    return (f'<path transform="translate({cx} {cy}) rotate({rot}) scale({s})" d="M0 12 C-22 -2 -22 -20 -9 -20 C-4 -20 0 -16 0 -12 C0 -16 4 -20 9 -20 C22 -20 22 -2 0 12 Z" '
            f'fill="none" stroke="{color}" stroke-width="{3.2 / s:.2f}" stroke-linejoin="round"/>')


def rays(cx: float, cy: float, color: str, start: float, count: int = 4, r1: float = 26, r2: float = 46) -> str:
    out = ""
    for i in range(count):
        a = math.radians(start + i * 22)
        out += (f'<path d="M{cx + r1 * math.cos(a):.0f} {cy + r1 * math.sin(a):.0f} L{cx + r2 * math.cos(a):.0f} {cy + r2 * math.sin(a):.0f}" '
                f'stroke="{color}" stroke-width="7" stroke-linecap="round"/>')
    return out


def scene(key: str) -> str:
    title, bubble, kind, accent = SECTIONS[key]
    seed = sum(map(ord, key))
    bg = data_uri(HERE / "source/background.jpg", "image/jpeg")
    lusi = data_uri(HERE / "source/lusi-cutout.png", "image/png")
    # Corgi: 760x733 cutout, paws rest on the ribbon.
    cw = 560
    ch = round(cw * 733 / 760)
    cx, cy = 680, 556 - ch
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
  <style>{font_face()} text{{font-family:Hand;font-weight:700}}</style>
  <filter id="sticker" x="-30%" y="-30%" width="160%" height="160%">
    <feMorphology in="SourceAlpha" operator="dilate" radius="7" result="grow"/>
    <feFlood flood-color="#ffffff"/><feComposite in2="grow" operator="in" result="edge"/>
    <feGaussianBlur in="grow" stdDeviation="6" result="blur"/><feOffset in="blur" dy="7" result="drop"/>
    <feFlood flood-color="#3b2208" flood-opacity=".35"/><feComposite in2="drop" operator="in" result="shadow"/>
    <feMerge><feMergeNode in="shadow"/><feMergeNode in="edge"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="8" stdDeviation="9" flood-color="#5a3200" flood-opacity=".35"/></filter>
  <filter id="lift" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#3b2208" flood-opacity=".35"/></filter>
  <radialGradient id="sun" cx=".18" cy=".1" r=".7"><stop offset="0" stop-color="#fff7d6" stop-opacity=".75"/><stop offset="1" stop-color="#fff7d6" stop-opacity="0"/></radialGradient>
  <linearGradient id="warm" x1="0" y1="0" x2="0" y2="1"><stop offset=".55" stop-color="#ffb347" stop-opacity="0"/><stop offset="1" stop-color="#ff9a1f" stop-opacity=".28"/></linearGradient>
  <linearGradient id="ribbon" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{YELLOW_LIGHT}"/><stop offset=".5" stop-color="{YELLOW}"/><stop offset="1" stop-color="#f6ae19"/></linearGradient>
</defs>
<image href="{bg}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice"/>
<rect width="{W}" height="{H}" fill="url(#sun)"/><rect width="{W}" height="{H}" fill="url(#warm)"/>

<!-- brand label -->
<g filter="url(#soft)">
  {brush(48, 34, 380, 92, "#ffffff", seed, streaks="#ffffff")}
  <text x="238" y="98" text-anchor="middle" font-size="62" fill="{INK}" transform="rotate(-2 238 80)">Корги Люси</text>
  {brush(96, 118, 290, 46, YELLOW, seed + 1)}
  <text x="241" y="152" text-anchor="middle" font-size="31" fill="{INK}" transform="rotate(-2 241 140)">Свободный Гав!</text>
</g>
{rays(470, 70, YELLOW, -60)}{rays(30, 170, YELLOW, 150, 3)}
{paw(468, 118, 28, "#ff9f1c", 18, sticker=True)}

<!-- section prop -->
<g transform="translate(222 345) scale(.88) rotate(-4)" filter="url(#sticker)">{prop(kind, accent)}</g>

<!-- Lusi -->
<image href="{lusi}" x="{cx}" y="{cy}" width="{cw}" height="{ch}" filter="url(#lift)"/>
{heart(668, 96, 1.6, YELLOW, -12)}{heart(1228, 300, 1.3, YELLOW, 14)}{heart(470, 205, 1.0, "#ffffff", -8)}

<!-- speech bubble -->
<g id="bubble" transform="translate(505 255) rotate(-6)">
  <rect id="bubble-box" x="-110" y="-44" width="220" height="80" rx="40" fill="#ffffff" fill-opacity=".22" stroke="#ffffff" stroke-width="5"/>
  <path d="M60 30 L104 62 L76 26" fill="none" stroke="#ffffff" stroke-width="5" stroke-linejoin="round"/>
  <text id="bubble-text" x="0" y="12" text-anchor="middle" font-size="36" fill="#ffffff" stroke="#6b3d0a" stroke-width="5" paint-order="stroke" stroke-opacity=".55">{bubble}</text>
</g>

<!-- ribbon with the section title -->
<g filter="url(#soft)">
  {brush(70, 498, 1140, 122, "url(#ribbon)", seed + 7, streaks=YELLOW)}
  <text id="title" x="640" y="586" text-anchor="middle" font-size="92" fill="{INK}" transform="rotate(-1.5 640 560)">{title}</text>
</g>
{paw(66, 560, 46, INK, -18, sticker=True)}{paw(1214, 560, 46, INK, 18, sticker=True)}
{rays(1238, 470, YELLOW, 200, 3, 22, 40)}{rays(44, 470, YELLOW, -20, 3, 22, 40)}
</svg>'''


FIT = """() => {
  const fit = (id, max, min) => { const t = document.getElementById(id); let s = parseFloat(t.getAttribute('font-size'));
    while (t.getBBox().width > max && s > min) { s -= 2; t.setAttribute('font-size', s); } };
  fit('title', 1030, 44);
  const bt = document.getElementById('bubble-text'); fit("bubble-text", 230, 22);
  const w = Math.max(180, bt.getBBox().width + 56); const box = document.getElementById('bubble-box');
  box.setAttribute('x', -w / 2); box.setAttribute('width', w);
}"""


def main(argv):
    keep_svg = "--svg" in argv
    keys = [a for a in argv if not a.startswith("--")] or list(SECTIONS)
    OUT.mkdir(parents=True, exist_ok=True)
    MINIAPP.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        for key in keys:
            svg = scene(key)
            if keep_svg:
                (OUT / f"{key}.svg").write_text(svg)
            page.set_content(f'<html><body style="margin:0">{svg}</body></html>')
            page.evaluate("document.fonts.ready")
            page.wait_for_function("[...document.images].every(i => i.complete) && document.fonts.status === 'loaded'")
            page.evaluate(FIT)
            target = OUT / f"{key}.jpg"
            page.locator("svg").screenshot(path=str(target), type="jpeg", quality=86)
            shutil.copyfile(target, MINIAPP / f"{key}.jpg")
            print("rendered", key)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
