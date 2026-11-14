#!/usr/bin/env python3
"""Launcher icons of the three Android apps and the iOS AppIcon sets (v28.137.0 redesign).

    python3 scripts/store/icons.py            # everything
    python3 scripts/store/icons.py --sheet    # only docs/img/app-icons-all.png (to look at)

Before, every icon was a whole sticker (confetti, a cup, the sticker's white edge) shrunk into a square: at 48 dp the corgi
was small and the launcher's mask cut the edge (owner's screenshot of 2026-11-13). Now:

* the corgi's head and one sign of the app fill the icon — client: the shield (VPN), shop app: the key (access),
  admin app: the wrench and gears;
* Android 8+ gets adaptive icons (background and foreground layers), so any launcher mask (circle, squircle, Honor/MIUI)
  cuts only the background. No monochrome layer: the silhouette of a detailed sticker is an unreadable blob, and without
  it Android 13 themed icons show the colour icon;
* the client keeps its three variants «Корги», «Ночь», «Мята» — same corgi, different background — and the picker in
  «Оформление» shows drawable-nodpi previews (painterResource cannot draw an adaptive icon).

Pure Pillow + NumPy; the sticker comes from scripts/bot-banners (``render.sticker``).
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "bot-banners"))
import render as banners  # noqa: E402

DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
# app → (sticker, crop box as fractions of the sticker's visible part: left, top, right, bottom)
ART = {
    "client": ("security", (0.0, 0.0, 1.0, 0.86)),
    "user": ("access", (0.0, 0.0, 1.0, 0.84)),
    "admin": ("settings", (0.0, 0.0, 1.0, 0.86)),
}
# background: (inner colour, outer colour, stars)
BACKGROUNDS = {
    "corgi": ("#ffb35c", "#e8650c", False),
    "night": ("#2b2f63", "#0d0f24", True),
    "mint": ("#7fe3c6", "#159b80", False),
    "admin": ("#6aa8ff", "#1d4ed8", False),
}
ADAPTIVE = 432           # 108 dp at xxxhdpi
SAFE = 0.64              # share of the 108 dp the art takes: about the 72 dp a launcher shows, the head inside the 66 dp circle
FADE = 0.16              # the bottom of the cut sticker fades out instead of ending in a straight line


def hexrgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def background(size: int, kind: str) -> Image.Image:
    inner, outer, stars = BACKGROUNDS[kind]
    a, b = np.array(hexrgb(inner), float), np.array(hexrgb(outer), float)
    y, x = np.mgrid[0:size, 0:size] / size
    t = np.clip(np.hypot(x - 0.32, y - 0.22) / 1.05, 0, 1)[..., None]
    img = Image.fromarray((a * (1 - t) + b * t).astype("uint8"), "RGB")
    if stars:
        draw = ImageDraw.Draw(img)
        rng = np.random.default_rng(7)
        for _ in range(26):
            cx, cy, r = rng.random() * size, rng.random() * size * 0.9, size * (0.004 + rng.random() * 0.007)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 244, 214))
    return img


def art(app: str) -> Image.Image:
    name, (l, t, r, b) = ART[app]
    sticker = banners.sticker(name).convert("RGBA")
    box = sticker.getchannel("A").getbbox()
    w, h = box[2] - box[0], box[3] - box[1]
    crop = sticker.crop((int(box[0] + l * w), int(box[1] + t * h), int(box[0] + r * w), int(box[1] + b * h)))
    side = max(crop.size)
    alpha = np.array(crop.getchannel("A"), float)
    rows = int(crop.height * FADE)
    alpha[-rows:] *= np.linspace(1, 0, rows)[:, None]
    crop.putalpha(Image.fromarray(alpha.astype("uint8")))
    square = Image.new("RGBA", (side, side))
    square.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2 + side // 14), crop)
    return square


def foreground(app: str, size: int = ADAPTIVE) -> Image.Image:
    layer = Image.new("RGBA", (size, size))
    inner = int(size * SAFE)
    piece = art(app).resize((inner, inner), Image.LANCZOS)
    off = (size - inner) // 2
    layer.paste(piece, (off, off), piece)
    return layer


def flat(app: str, kind: str, size: int, rounded: bool) -> Image.Image:
    """The whole icon in one picture: legacy launchers, previews, iOS, stores."""
    big = size * 2
    canvas = background(big, kind).convert("RGBA")
    # The adaptive layer is 108 dp of which a launcher shows 72 dp: the flat icon shows the same middle part.
    fg = foreground(app, int(big * 108 / 72))
    cut = (fg.width - big) // 2
    canvas = Image.alpha_composite(canvas, fg.crop((cut, cut, cut + big, cut + big)))
    if rounded:
        mask = Image.new("L", (big, big))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.23), fill=255)
        canvas.putalpha(mask)
    return canvas.resize((size, size), Image.LANCZOS)


def adaptive_xml(fg: str, bg: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
            f'    <background android:drawable="@mipmap/{bg}" />\n    <foreground android:drawable="@mipmap/{fg}" />\n'
            '</adaptive-icon>\n')


def android_dir(app: str) -> pathlib.Path:
    """v28.149.0 (docs/MONOREPO_LAYOUT.md, stage 1): the VPN client lives in apps/vpn-client/android."""
    return ROOT / ("apps/vpn-client/android" if app == "client" else f"mobile/android-{app}")


def android(app: str, variants: dict[str, str]) -> None:
    """``variants``: icon name → background kind."""
    res = android_dir(app) / "app/src/main/res"
    fg_name = "ic_launcher_fg"
    fg = foreground(app)
    anydpi = res / "mipmap-anydpi-v26"
    anydpi.mkdir(exist_ok=True)
    for density, scale in DENSITIES.items():
        folder = res / f"mipmap-{density}"
        folder.mkdir(exist_ok=True)
        side = round(108 * scale)
        fg.resize((side, side), Image.LANCZOS).save(folder / f"{fg_name}.png", optimize=True)
        for name, kind in variants.items():
            background(side, kind).save(folder / f"{name}_bg.png", optimize=True)
            flat(app, kind, round(48 * scale), rounded=True).save(folder / f"{name}.png", optimize=True)
    for name in variants:
        (anydpi / f"{name}.xml").write_text(adaptive_xml(fg_name, f"{name}_bg"))
        print("saved", (anydpi / f"{name}.xml").relative_to(ROOT))


def write_all() -> None:
    android("client", {"ic_launcher": "corgi", "ic_launcher_night": "night", "ic_launcher_mint": "mint"})
    previews = ROOT / "apps/vpn-client/android/app/src/main/res/drawable-nodpi"
    for key in ("corgi", "night", "mint"):
        flat("client", key, 168, rounded=True).save(previews / f"icon_preview_{key}.png", optimize=True)
    android("user", {"ic_launcher": "corgi"})
    android("admin", {"ic_launcher": "admin"})
    store = ROOT / "mobile/store/icons"
    flat("user", "corgi", 1024, rounded=False).convert("RGB").save(store / "icon-1024.png", optimize=True)
    flat("user", "corgi", 512, rounded=False).convert("RGB").save(store / "icon-512.png", optimize=True)
    flat("admin", "admin", 1024, rounded=False).convert("RGB").save(store / "admin-icon-1024.png", optimize=True)
    flat("client", "corgi", 512, rounded=False).convert("RGB").save(store / "client-icon-512.png", optimize=True)
    for role, app, kind in (("user", "VpnShopUser", "corgi"), ("admin", "VpnShopAdmin", "admin")):
        appicon = ROOT / f"mobile/ios-{role}/{app}/Assets.xcassets/AppIcon.appiconset"
        appicon.mkdir(parents=True, exist_ok=True)
        flat(role, kind, 1024, rounded=False).convert("RGB").save(appicon / "icon-1024.png", optimize=True)
        (appicon / "Contents.json").write_text(json.dumps({"images": [{"filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}],
                                                           "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
    print("icons written")


def sheet() -> None:
    """All icons as a launcher would show them: rounded square, circle, squircle."""
    rows = [("client", "corgi"), ("client", "night"), ("client", "mint"), ("user", "corgi"), ("admin", "admin")]
    S, pad = 192, 28
    out = Image.new("RGB", (pad + 3 * (S + pad), pad + len(rows) * (S + pad)), "#101114")
    for r, (app, kind) in enumerate(rows):
        full = flat(app, kind, S, rounded=False)
        for c, shape in enumerate(("rounded", "circle", "squircle")):
            tile = full.copy()
            mask = Image.new("L", (S, S))
            d = ImageDraw.Draw(mask)
            if shape == "circle":
                d.ellipse((0, 0, S - 1, S - 1), fill=255)
            else:
                d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * (0.23 if shape != "squircle" else 0.36)), fill=255)
            out.paste(tile.convert("RGB"), (pad + c * (S + pad), pad + r * (S + pad)), mask)
    target = ROOT / "docs/img/app-icons-all.png"
    out.save(target, optimize=True)
    print("saved", target.relative_to(ROOT))


if __name__ == "__main__":
    if "--sheet" not in sys.argv:
        write_all()
    sheet()
