#!/usr/bin/env python3
"""Prepare render.py inputs from the brand artwork of corgi Lusi.

    pip install rembg onnxruntime opencv-python-headless pillow
    python3 scripts/bot-banners/prepare.py [artwork.jpg|png]   # default: source/corgi-lusi-original.jpg

Writes:
  source/lusi-cutout.png  — Lusi without background and lettering (rembg u2net, largest
                            component, lettering above the ears removed by colour, small holes
                            inside the ears filled back from the artwork);
  source/background.jpg   — the scene without Lusi and lettering (OpenCV inpainting + blur),
                            cropped to 1280x640.
The lettering boxes match the original 1254x1254 artwork: title on top (y < 335), ribbon at
the bottom (y > 970), speech bubble on the left. Adjust them for a different picture.
"""
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "source/corgi-lusi-original.jpg"


def main():
    from rembg import new_session, remove
    art = Image.open(SRC).convert("RGB").resize((1254, 1254), Image.LANCZOS)
    src = np.array(art)
    cut = np.array(remove(art, session=new_session("u2net"), alpha_matting=True,
                          alpha_matting_foreground_threshold=240, alpha_matting_background_threshold=15,
                          alpha_matting_erode_size=8))
    rgb, alpha = cut[:, :, :3], cut[:, :, 3].astype(np.float32)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue, sat, val = hsv[:, :, 0] * 2, hsv[:, :, 1] / 255, hsv[:, :, 2] / 255
    yy, xx = np.mgrid[0:1254, 0:1254]
    lettering = (yy < 345) & ~(((xx >= 440) & (xx <= 660)) & ~((sat < .25) & (val > .75))
                               & ~((hue >= 36) & (hue <= 70) & (sat > .35)) & ~(val < .25))
    alpha = np.where(lettering, 0, alpha)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((alpha > 20).astype(np.uint8), 8)
    biggest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    alpha = np.where(cv2.dilate((lab == biggest).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0, alpha, 0)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((alpha <= 40).astype(np.uint8), 4)
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < 2500:
            hole = lab == k
            alpha[hole] = 255
            rgb[hole] = src[hole]
    cut[:, :, :3], cut[:, :, 3] = rgb, alpha.astype(np.uint8)
    ys, xs = np.where(cut[:, :, 3] > 10)
    Image.fromarray(cut).crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)).save(HERE / "source/lusi-cutout.png")

    mask = np.zeros((1254, 1254), np.uint8)
    mask[cut[:, :, 3] > 10] = 255
    mask = cv2.dilate(mask, np.ones((25, 25), np.uint8))
    mask[:335, :] = 255
    mask[970:, :] = 255
    mask[370:640, 40:420] = 255
    small = cv2.inpaint(cv2.resize(src, (418, 418), interpolation=cv2.INTER_AREA),
                        cv2.resize(mask, (418, 418), interpolation=cv2.INTER_NEAREST), 9, cv2.INPAINT_TELEA)
    plate = cv2.GaussianBlur(cv2.resize(small, (1254, 1254), interpolation=cv2.INTER_CUBIC), (0, 0), 14)
    Image.fromarray(plate).crop((0, 40, 1254, 667)).resize((1280, 640), Image.LANCZOS).save(HERE / "source/background.jpg", quality=90)
    print("prepared", HERE / "source")


if __name__ == "__main__":
    main()
