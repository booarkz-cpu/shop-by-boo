#!/usr/bin/env python3
"""Render the default banners of the bot and the Mini App from the corgi Lusi sticker sheets.

Sources: source/stickers/sheet-*.jpg — four sheets of corgi Lusi stickers (white rounded cards
with a dark-brown caption on top, 2x2 and 3x3 grids). Each banner takes one sticker: the card
is cut out of its sheet without the caption, placed on the right as a slightly tilted white
card with a soft shadow, and the section title is set on the left in the same condensed bold
lettering (Roboto Condensed 800, SIL OFL, fonts/). Every section has its own sticker.

Output: backend/app/assets/bot_banners/<key>.jpg (1280x640) and the copies the Mini App bundles
in cabinet/public/assets/banners/; with --extras also docs/img/hero.jpg (README cover) and
docs/img/bot-banners-all.jpg (all banners on one sheet).

    python3 scripts/bot-banners/render.py              # all banners
    python3 scripts/bot-banners/render.py start buy    # selected ones
    python3 scripts/bot-banners/render.py --extras     # banners + README cover and sheet
    python3 scripts/bot-banners/render.py --stickers   # only dump the cut stickers to /tmp

Needs Pillow, NumPy and Python Playwright with Chromium.
"""
import base64
import io
import pathlib
import shutil
import sys

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STICKERS = HERE / "source/stickers"
OUT = ROOT / "backend/app/assets/bot_banners"
MINIAPP = ROOT / "cabinet/public/assets/banners"
DOCS = ROOT / "docs/img"
W, H = 1280, 640
INK = "#3a2416"

# sheet → (approximate card origins x, y; card width, height; caption share of the card height;
#          side inset share; bottom inset share). Sheet 3 cards have a thin frame with paws.
SHEETS = {
    "sheet-1-account.jpg": ((76, 1043), (57, 1040), 928, 956, 0.0, 0.035, 0.035),
    "sheet-2-service.jpg": ((78, 733, 1360), (60, 724, 1392), 615, 640, 0.17, 0.045, 0.035),
    "sheet-3-ops.jpg": ((40, 704, 1367), (48, 707, 1368), 642, 643, 0.18, 0.07, 0.105),
    "sheet-4-shop.jpg": ((78, 731, 1362), (60, 724, 1393), 615, 640, 0.17, 0.045, 0.035),
}
# sticker name → (sheet, index in reading order). The "privacy" sticker carries a "VPN"
# shield and is deliberately not used.
CATALOG = {
    "gift": ("sheet-1-account.jpg", 0), "rules": ("sheet-1-account.jpg", 1),
    "login": ("sheet-1-account.jpg", 2), "cabinet": ("sheet-1-account.jpg", 3),
    "support": ("sheet-2-service.jpg", 0), "search": ("sheet-2-service.jpg", 1), "error404": ("sheet-2-service.jpg", 2),
    "settings": ("sheet-2-service.jpg", 3), "delivery": ("sheet-2-service.jpg", 4), "waiting": ("sheet-2-service.jpg", 5),
    "success": ("sheet-2-service.jpg", 6), "holiday": ("sheet-2-service.jpg", 7), "goodbye": ("sheet-2-service.jpg", 8),
    "security": ("sheet-3-ops.jpg", 0), "telegram": ("sheet-3-ops.jpg", 1), "balancing": ("sheet-3-ops.jpg", 2),
    "deploy": ("sheet-3-ops.jpg", 3), "bugs": ("sheet-3-ops.jpg", 4), "backup": ("sheet-3-ops.jpg", 5),
    "metrics": ("sheet-3-ops.jpg", 6), "api": ("sheet-3-ops.jpg", 7), "maintenance": ("sheet-3-ops.jpg", 8),
    "chatbot": ("sheet-4-shop.jpg", 0), "miniapp": ("sheet-4-shop.jpg", 1), "renewal": ("sheet-4-shop.jpg", 2),
    "access": ("sheet-4-shop.jpg", 3), "vip": ("sheet-4-shop.jpg", 4), "location": ("sheet-4-shop.jpg", 6),
    "speed": ("sheet-4-shop.jpg", 7), "payment": ("sheet-4-shop.jpg", 8),
}

# banner key → (title, caption, sticker, accent colour)
SECTIONS = {
    "start": ("Добро пожаловать!", "Магазин подписок прямо в Telegram", "miniapp", "#ffb84d"),
    "menu": ("Меню", "Всё самое нужное — в пару касаний", "telegram", "#7cb7ff"),
    "buy": ("Тарифы", "Выберите подходящий срок", "vip", "#ffd166"),
    "subscription": ("Подписка", "Срок, трафик и продление", "renewal", "#7dd8a3"),
    "promo": ("Промокод", "Введите код и получите скидку", "success", "#ff8fc7"),
    "account": ("Мой кабинет", "Подписки, баланс и настройки", "cabinet", "#8fb8ff"),
    "balance": ("Кошелёк", "Баланс и история операций", "payment", "#6fd6a8"),
    "payments": ("Платежи", "Каждая оплата на виду", "metrics", "#b49cff"),
    "gifts": ("Подарки", "Подарите подписку близким", "gift", "#ff8a8a"),
    "referral": ("Пригласи друзей", "Делитесь ссылкой и получайте бонусы", "delivery", "#ff9db0"),
    "support": ("Поддержка", "Ответим и поможем", "support", "#6cc8ff"),
    "devices": ("Устройства", "Подключённые устройства под контролем", "settings", "#5fd3e6"),
    "surveys": ("Опросы", "Расскажите, что улучшить", "rules", "#ffd45c"),
    "home": ("Главная", "Подписка, акции и серверы", "security", "#7dd8a3"),
    "topup": ("Пополнение баланса", "СБП, карта и Telegram Stars", "access", "#6fd6a8"),
    "trial": ("Пробный период", "Попробуйте бесплатно", "deploy", "#b5e16b"),
    "connection": ("Подключение", "Настройка за минуту", "speed", "#5fd8c4"),
    "servers": ("Серверы", "Локации по всему миру", "location", "#7cb7ff"),
    "info": ("Информация", "Ответы, правила и документы", "search", "#c9a2ff"),
    "family": ("Семья", "Одна подписка на всю семью", "api", "#ff9db0"),
    "status": ("Состояние сервиса", "Что работает прямо сейчас", "balancing", "#7cb7ff"),
}


def card_box(sheet: Image.Image, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """Tighten an approximate grid cell to the white card it contains."""
    pad = 24
    box = (max(0, x - pad), max(0, y - pad), min(sheet.width, x + w + pad), min(sheet.height, y + h + pad))
    rgb = np.asarray(sheet.crop(box).convert("RGB")).astype(int)
    paper = np.asarray(sheet.convert("RGB")).astype(int)[6, 6]          # the sheet background
    beige = (np.abs(rgb - paper) <= 7).all(axis=2)

    def card_run(gap):
        # Lines that are mostly sheet background are the gaps between cards (art never is):
        # the card is the longest run of non-gap lines.
        best, start = (0, 0), None
        for i, v in enumerate(list(~gap) + [False]):
            if v and start is None:
                start = i
            elif not v and start is not None:
                best = max(best, (i - start, start))
                start = None
        return best[1], best[1] + best[0]
    c0, c1 = card_run(beige.mean(axis=0) > 0.6)
    r0, r1 = card_run(beige.mean(axis=1) > 0.6)
    return box[0] + c0, box[1] + r0, box[0] + c1, box[1] + r1


def caption_end(sheet: Image.Image, box: tuple[int, int, int, int], share: float) -> int:
    """Rows from the card top to the end of its caption (0 for a card without one)."""
    if not share:
        return 0
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    card = np.asarray(sheet.crop((x0 + round(cw * 0.06), y0, x1 - round(cw * 0.06), y0 + round(ch * 0.32))).convert("RGB")).min(axis=2)
    dark = (card < 95).mean(axis=1) > 0.008
    # Blocks of dark-ink rows separated by gaps of 4 blank rows; the caption is the first block
    # tall enough to be lettering (frame lines are a few rows high), capped at 15% of the card.
    i = round(ch * 0.02)
    while i < len(dark):
        if not dark[i]:
            i += 1
            continue
        start = end = i
        while end + 4 < len(dark) and end - start < ch * 0.15 and any(dark[end + 1:end + 5]):
            end += 1
        if end - start >= ch * 0.04:
            return end + 2
        i = end + 1
    return round(ch * share)


def sticker(name: str, outline: int = 12) -> Image.Image:
    """The whole sticker art cut out of its card (transparent background, white sticker outline).

    The white card background is removed by a flood fill from the card edge, so nothing of the
    drawing is cropped: ears, tails and props that reach into the caption area stay. The caption
    letters are separate shapes lying entirely above the caption line and are dropped; so are the
    paw prints of the card frame on sheet 3.
    """
    import cv2
    sheet_name, index = CATALOG[name]
    xs, ys, w, h, caption, side, bottom = SHEETS[sheet_name]
    sheet = Image.open(STICKERS / sheet_name).convert("RGB")
    box = card_box(sheet, xs[index % len(xs)], ys[index // len(xs)], w, h)
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    framed = sheet_name == "sheet-3-ops.jpg"
    inset = round(min(cw, ch) * (0.045 if framed else 0.04))
    crop = sheet.crop((x0 + inset, y0 + inset, x1 - inset, y1 - inset))
    rgb = np.asarray(crop).astype(np.int16)
    whiteish = ((rgb.min(axis=2) >= 238) & (rgb.max(axis=2) - rgb.min(axis=2) <= 16)).astype(np.uint8)
    # Background = white connected to the border of the card.
    n, lab = cv2.connectedComponents(whiteish, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    background = np.isin(lab, list(border)) & (whiteish == 1)
    fg = (~background).astype(np.uint8)
    line = max(0, caption_end(sheet, box, caption) - inset)
    if caption and line:
        # Art that touches the caption (an ear over a letter) joins the lettering into one shape:
        # inside the caption band the dark lettering ink is erased, coloured art stays.
        band = rgb[:line]
        ink = (band.max(axis=2) < 110) & (band.max(axis=2) - band.min(axis=2) < 60)
        ink = cv2.dilate(ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        fg[:line][ink] = 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    keep = np.zeros(n, bool)
    hh, ww = fg.shape
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 60:
            continue
        if caption and y + bh <= line + 3:
            continue                                     # caption lettering
        near_corner = (x < ww * 0.14 or x + bw > ww * 0.86) and (y < hh * 0.14 or y + bh > hh * 0.86)
        if framed and near_corner and area < 6000:
            continue                                     # paw prints of the frame
        if (bw > ww * 0.4 or bh > hh * 0.4) and area < 0.04 * bw * bh:
            continue                                     # card edge or shadow line
        touches = x <= 3 or y <= 3 or x + bw >= ww - 3 or y + bh >= hh - 3
        if touches and (min(bw, bh) <= 16 or area < 0.12 * bw * bh):
            continue                                     # pieces of the card edge
        keep[i] = True
    mask = keep[lab].astype(np.uint8) * 255
    ys_, xs_ = np.where(mask > 0)
    mask = mask[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1]
    art = np.asarray(crop)[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1]
    pad = outline + 4
    mask = np.pad(mask, pad)
    art = np.pad(art, ((pad, pad), (pad, pad), (0, 0)), constant_values=255)
    soft = cv2.GaussianBlur(mask, (0, 0), 0.8)
    edge = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (outline * 2 + 1, outline * 2 + 1)))
    edge = cv2.GaussianBlur(edge, (0, 0), 1.2)
    out = np.zeros((*mask.shape, 4), np.uint8)
    a = soft.astype(np.float32) / 255
    out[..., :3] = (art * a[..., None] + 255 * (1 - a[..., None])).astype(np.uint8)
    out[..., 3] = np.maximum(edge, soft)
    return Image.fromarray(out, "RGBA")


def data_uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    if img.mode == "RGBA":
        img.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def font_face() -> str:
    faces = []
    for name, rng in (("roboto-condensed-cyrillic-800-normal.woff2", "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116"),
                      ("roboto-condensed-latin-800-normal.woff2", "U+0000-00FF,U+2000-206F,U+20AC,U+20BD")):
        b64 = base64.b64encode((HERE / "fonts" / name).read_bytes()).decode()
        faces.append(f"@font-face{{font-family:Lusi;font-weight:800;src:url(data:font/woff2;base64,{b64}) format('woff2');unicode-range:{rng}}}")
    return "".join(faces)


PAW = ('<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg"><g fill="currentColor"><ellipse cx="20" cy="27" rx="9" ry="8"/>'
       '<ellipse cx="9" cy="16" rx="4" ry="5"/><ellipse cx="16" cy="9" rx="4" ry="5"/><ellipse cx="24" cy="9" rx="4" ry="5"/>'
       '<ellipse cx="31" cy="16" rx="4" ry="5"/></g></svg>')
SPARK = '<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M20 0C22 14 26 18 40 20 26 22 22 26 20 40 18 26 14 22 0 20 14 18 18 14 20 0Z"/></svg>'

BASE_CSS = """
*{box-sizing:border-box;margin:0}
body{width:%dpx;height:%dpx;overflow:hidden;font-family:Lusi,'Roboto Condensed',sans-serif;color:%s;
 background:radial-gradient(circle at 78%% 50%%,var(--glow) 0,transparent 48%%),linear-gradient(135deg,#fbf6ef 0%%,#f3e9dd 100%%)}
.paw{position:absolute;width:var(--s);height:var(--s);color:#8a5a3a;opacity:.13;transform:rotate(var(--r))}
.spark{position:absolute;width:var(--s);height:var(--s);color:var(--c);transform:rotate(var(--r))}
.brand{position:absolute;left:64px;top:56px;display:flex;align-items:center;gap:12px;font-size:30px;letter-spacing:.02em;color:#8a5a3a}
.brand i{display:block;width:34px;height:34px;color:#e08a2c}
.sticker{position:absolute;display:block;filter:drop-shadow(0 16px 22px rgba(84,46,16,.24)) drop-shadow(0 3px 5px rgba(84,46,16,.12))}
""" % (W, H, INK)


def decor(seed: int, accent: str, area=(0, 0, W, H)) -> str:
    rnd = np.random.default_rng(seed)
    out = []
    for _ in range(9):
        x, y = rnd.integers(area[0], area[2]), rnd.integers(area[1], area[3])
        out.append(f'<div class="paw" style="left:{x}px;top:{y}px;--s:{rnd.integers(26, 46)}px;--r:{rnd.integers(-40, 40)}deg">{PAW}</div>')
    for x, y, s, c in ((rnd.integers(470, 620), rnd.integers(60, 150), 34, accent), (rnd.integers(40, 300), rnd.integers(470, 580), 26, "#ffc83d"),
                       (rnd.integers(1150, 1230), rnd.integers(40, 120), 30, "#ffc83d")):
        out.append(f'<div class="spark" style="left:{x}px;top:{y}px;--s:{s}px;--c:{c};--r:{rnd.integers(-20, 20)}deg">{SPARK}</div>')
    return "".join(out)


def banner_html(key: str) -> str:
    title, caption, name, accent = SECTIONS[key]
    art = sticker(name)
    # The whole sticker fits into the right half: scaled down, never cropped.
    scale = min(580 / art.width, 560 / art.height)
    aw, ah = round(art.width * scale), round(art.height * scale)
    size = 112 if len(title) <= 9 else 96 if len(title) <= 13 else 80
    seed = sum(map(ord, key))
    tilt = (-3, -2, 2, 3)[seed % 4]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{font_face()}{BASE_CSS}
:root{{--glow:{accent}55}}
.title{{position:absolute;left:64px;top:50%;transform:translateY(-58%);width:540px;font-size:{size}px;line-height:.98;font-weight:800;
 text-transform:uppercase;letter-spacing:.005em;text-shadow:0 3px 0 #fff}}
.caption{{position:absolute;left:64px;bottom:74px;max-width:560px;font-size:31px;line-height:1.15;padding:14px 24px;border-radius:999px;
 background:#fff;color:#5b3a24;box-shadow:0 8px 20px rgba(84,46,16,.12);border:3px solid {accent}}}
.bar{{position:absolute;left:64px;top:118px;width:120px;height:10px;border-radius:5px;background:{accent}}}
</style></head><body>
{decor(seed, accent)}
<div class="brand"><i>{PAW}</i>Корги Люси</div><div class="bar"></div>
<div class="title" id="title">{title}</div>
<div class="caption">{caption}</div>
<img class="sticker" src="{data_uri(art)}" width="{aw}" height="{ah}" style="left:{930 - aw // 2}px;top:{(H - ah) // 2}px;transform:rotate({tilt}deg)">
</body></html>"""


def hero_html() -> str:
    names = ("miniapp", "support", "vip", "location")
    cards = []
    for i, name in enumerate(names):
        art = sticker(name)
        h = 300 if i in (1, 2) else 270
        w = round(art.width * h / art.height)
        x = 575 + i * 222
        y = (640 - h) // 2 + (-34, 26, -20, 30)[i]
        cards.append(f'<img class="sticker" src="{data_uri(art)}" width="{w}" height="{h}" '
                     f'style="left:{x}px;top:{y}px;z-index:{(1, 3, 2, 1)[i]};transform:rotate({(-6, 3, -3, 6)[i]}deg)">')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{font_face()}{BASE_CSS.replace(f'width:{W}px', 'width:1600px')}
:root{{--glow:#ffc37a66}}
.title{{position:absolute;left:72px;top:170px;font-size:124px;line-height:.95;font-weight:800;text-transform:uppercase;text-shadow:0 4px 0 #fff}}
.sub{{position:absolute;left:76px;top:420px;width:470px;font-size:36px;line-height:1.2;color:#5b3a24}}
</style></head><body style="width:1600px">
{decor(7, "#ff9f43", (0, 0, 1600, 640))}
<div class="brand"><i>{PAW}</i>Корги Люси</div>
<div class="title">Корги<br>Люси</div>
<div class="sub">Магазин подписок: бот в&nbsp;Telegram, Mini&nbsp;App, личный кабинет и&nbsp;админ-панель</div>
{''.join(cards)}
</body></html>"""


def main(argv):
    from playwright.sync_api import sync_playwright
    flags = {a for a in argv if a.startswith("--")}
    if "--stickers" in flags:
        out = pathlib.Path("/tmp/lusi-stickers")
        out.mkdir(exist_ok=True)
        for name in CATALOG:
            sticker(name).save(out / f"{name}.png")
        print("stickers in", out)
        return
    keys = [a for a in argv if not a.startswith("--")] or list(SECTIONS)
    OUT.mkdir(parents=True, exist_ok=True)
    MINIAPP.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        for key in keys:
            page.set_content(banner_html(key))
            page.wait_for_function("document.fonts.ready.then(() => [...document.images].every(i => i.complete))")
            # Long titles shrink until they fit in two lines next to the card.
            page.evaluate("""() => { const t = document.getElementById('title'); let s = parseFloat(getComputedStyle(t).fontSize);
              while ((t.scrollWidth > t.clientWidth || t.getBoundingClientRect().height > 2.05 * s) && s > 48) { s -= 4; t.style.fontSize = s + 'px'; } }""")
            png = page.screenshot(type="png")
            target = OUT / f"{key}.jpg"
            Image.open(io.BytesIO(png)).convert("RGB").save(target, "JPEG", quality=86, optimize=True, progressive=True)
            shutil.copyfile(target, MINIAPP / f"{key}.jpg")
            print("saved", target.relative_to(ROOT))
        if "--extras" in flags:
            page.set_viewport_size({"width": 1600, "height": 640})
            page.set_content(hero_html())
            page.wait_for_function("document.fonts.ready.then(() => [...document.images].every(i => i.complete))")
            Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB").save(DOCS / "hero.jpg", "JPEG", quality=86, optimize=True)
            print("saved docs/img/hero.jpg")
        browser.close()
    if "--extras" in flags:
        tiles = [Image.open(OUT / f"{k}.jpg").resize((640, 320), Image.LANCZOS) for k in SECTIONS]
        cols = 3
        sheet = Image.new("RGB", (cols * 640 + (cols + 1) * 16, ((len(tiles) + cols - 1) // cols) * 336 + 16), "#f3e9dd")
        for i, t in enumerate(tiles):
            sheet.paste(t, (16 + (i % cols) * 656, 16 + (i // cols) * 336))
        sheet.save(DOCS / "bot-banners-all.jpg", "JPEG", quality=84, optimize=True)
        print("saved docs/img/bot-banners-all.jpg")


if __name__ == "__main__":
    main(sys.argv[1:])
