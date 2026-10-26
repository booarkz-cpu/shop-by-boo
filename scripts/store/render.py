#!/usr/bin/env python3
"""Store artwork of the Corgi Lusi apps: icons, the Google Play feature graphic and framed screenshots.

    python3 scripts/store/render.py            # everything
    python3 scripts/store/render.py --icons    # app icons only (Android mipmaps, iOS AppIcon, store icons)

Sources: the corgi Lusi sticker sheets (scripts/bot-banners) and the demo screenshots of the apps
(screenshots/mobile/*.png, made by the «Mobile screenshots» workflow). Output:

* mobile/store/icons/icon-1024.png (App Store, RuStore), icon-512.png (Google Play);
* mobile/store/google-play/feature-graphic.png (1024x500);
* mobile/store/screenshots/{android,ios}/NN-<screen>.png — screenshots on the brand background
  with a caption: Google Play 1080x1920, App Store 6.9" 1320x2868;
* Android launcher icons (res/mipmap-*/ic_launcher*.png) of both apps and the iOS AppIcon sets.

Needs Pillow, NumPy and Python Playwright with Chromium (the same as the banner renderer).
"""
import base64
import io
import json
import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "bot-banners"))
import render as banners  # noqa: E402

STORE = ROOT / "mobile" / "store"
SHOTS = ROOT / "screenshots" / "mobile"
ORANGE, DARK = "#FF8A1F", "#0E0F14"
ADMIN_BLUE = "#3B82F6"

# screen → caption (ru, en)
CAPTIONS = [
    ("vpn", "Защита в одно касание", "Protection in one tap"),
    ("locations", "Самый быстрый сервер — автоматически", "The fastest server, automatically"),
    ("premium", "Безлимит и все локации", "Unlimited traffic, every location"),
    ("subscription", "Подписка и устройства на виду", "Your plan and devices at a glance"),
    ("giveaways", "Розыгрыши и бонусы", "Giveaways and bonuses"),
    ("support", "Поддержка, которая отвечает", "Support that answers"),
]


def png_data(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def file_data(path: pathlib.Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def icon_html(size: int, admin: bool = False, rounded: bool = False) -> str:
    art = png_data(banners.sticker("success" if not admin else "settings"))
    bg = (f"radial-gradient(circle at 30% 20%,#ffb15c 0,{ORANGE} 45%,#e2650a 100%)" if not admin
          else f"radial-gradient(circle at 30% 20%,#60a5fa 0,{ADMIN_BLUE} 50%,#1d4ed8 100%)")
    radius = f"border-radius:{int(size * .22)}px;" if rounded else ""
    return f"""<!doctype html><html><head><style>*{{margin:0}}body{{width:{size}px;height:{size}px;overflow:hidden;background:transparent}}
.i{{width:{size}px;height:{size}px;background:{bg};{radius}display:grid;place-items:center;overflow:hidden}}
.i img{{width:{int(size * .86)}px;height:{int(size * .86)}px;object-fit:contain;filter:drop-shadow(0 {size // 60}px {size // 30}px rgba(0,0,0,.25))}}</style></head>
<body><div class="i"><img src="{art}"></div></body></html>"""


def feature_html() -> str:
    art = png_data(banners.sticker("success"))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{banners.font_face()}*{{margin:0;box-sizing:border-box}}
body{{width:1024px;height:500px;overflow:hidden;font-family:Lusi,sans-serif;color:#f5f2ee;
background:radial-gradient(circle at 78% 55%,{ORANGE}66 0,transparent 45%),linear-gradient(135deg,#17181f,#0e0f14)}}
.t{{position:absolute;left:64px;top:120px;width:560px}}.t b{{font-size:84px;line-height:.95;display:block;color:{ORANGE}}}
.t span{{display:block;margin-top:22px;font-size:34px;line-height:1.15}}
img{{position:absolute;right:40px;top:30px;height:440px;filter:drop-shadow(0 18px 30px rgba(0,0,0,.45))}}</style></head>
<body><div class="t"><b>Корги Люси</b><span>VPN в одно касание:<br>быстро, просто, без лишнего</span></div><img src="{art}"></body></html>"""


def shot_html(path: pathlib.Path, caption: str, w: int, h: int, ios: bool) -> str:
    phone_w = int(w * .78)
    radius = int(phone_w * (0.12 if ios else 0.08))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{banners.font_face()}*{{margin:0;box-sizing:border-box}}
body{{width:{w}px;height:{h}px;overflow:hidden;font-family:Lusi,sans-serif;color:#f5f2ee;display:flex;flex-direction:column;align-items:center;
background:radial-gradient(circle at 50% 0%,{ORANGE}55 0,transparent 55%),linear-gradient(180deg,#1b1c24,#0e0f14)}}
h1{{font-size:{int(w * .078)}px;line-height:1.05;text-align:center;margin:{int(h * .05)}px {int(w * .08)}px {int(h * .035)}px}}
.p{{width:{phone_w}px;border-radius:{radius}px;overflow:hidden;border:{max(6, w // 110)}px solid #2a2c36;box-shadow:0 30px 80px rgba(0,0,0,.55)}}
.p img{{width:100%;display:block}}</style></head><body><h1>{caption}</h1><div class="p"><img src="{file_data(path)}"></div></body></html>"""


def shoot(page, html: str, w: int, h: int, target: pathlib.Path, transparent: bool = False, rgb: bool = True):
    page.set_viewport_size({"width": w, "height": h})
    page.set_content(html)
    page.wait_for_function("document.fonts.ready.then(() => [...document.images].every(i => i.complete))")
    image = Image.open(io.BytesIO(page.screenshot(type="png", omit_background=transparent)))
    target.parent.mkdir(parents=True, exist_ok=True)
    (image.convert("RGB") if rgb else image).save(target, "PNG", optimize=True)
    print("saved", target.relative_to(ROOT))


ANDROID_DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def icons(page):
    shoot(page, icon_html(1024), 1024, 1024, STORE / "icons" / "icon-1024.png")
    shoot(page, icon_html(512), 512, 512, STORE / "icons" / "icon-512.png")
    shoot(page, icon_html(1024, admin=True), 1024, 1024, STORE / "icons" / "admin-icon-1024.png")
    for role, admin in (("user", False), ("admin", True)):
        res = ROOT / f"mobile/android-{role}/app/src/main/res"
        for density, px in ANDROID_DENSITIES.items():
            shoot(page, icon_html(px * 4, admin, rounded=True), px * 4, px * 4, res / f"mipmap-{density}/ic_launcher.png", transparent=True, rgb=False)
            Image.open(res / f"mipmap-{density}/ic_launcher.png").resize((px, px), Image.LANCZOS).save(res / f"mipmap-{density}/ic_launcher.png", optimize=True)
        app = "VpnShopUser" if role == "user" else "VpnShopAdmin"
        appicon = ROOT / f"mobile/ios-{role}/{app}/Assets.xcassets/AppIcon.appiconset"
        shoot(page, icon_html(1024, admin), 1024, 1024, appicon / "icon-1024.png")
        (appicon / "Contents.json").write_text(json.dumps({"images": [{"filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}],
                                                           "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
        (appicon.parent / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}, indent=2) + "\n")


def screenshots(page):
    for platform, (w, h), ios in (("android", (1080, 1920), False), ("ios", (1320, 2868), True)):
        n = 0
        for screen, ru, en in CAPTIONS:
            source = SHOTS / f"{platform}-{screen}.png"
            if not source.exists():
                print("skip (no screenshot yet)", source.relative_to(ROOT))
                continue
            n += 1
            shoot(page, shot_html(source, ru, w, h, ios), w, h, STORE / "screenshots" / platform / f"{n:02d}-{screen}.png")


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        icons(page)
        if "--icons" not in sys.argv:
            shoot(page, feature_html(), 1024, 500, STORE / "google-play" / "feature-graphic.png")
            screenshots(page)
        browser.close()


if __name__ == "__main__":
    main()
