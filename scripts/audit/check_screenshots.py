"""Regenerate the inventory of version-controlled interface captures and store artwork."""
import argparse
import hashlib
import struct
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "docs/SCREENSHOT_COVERAGE.md"
GROUPS = (
    ("Lucy Admin Web", "screenshots/admin_panel/**/*.png", "apps/lucy-admin/web/scripts/screenshots-catalog.mjs"),
    ("Кабинет", "screenshots/storefront_user/*.png", "apps/lucy-admin/web/scripts/screenshots-catalog.mjs"),
    ("VPN Shop Android", "screenshots/mobile/android-*.png", ".github/workflows/mobile-screenshots.yml"),
    ("VPN Shop iOS", "screenshots/mobile/ios-*.png", ".github/workflows/mobile-screenshots.yml"),
    ("Lucy Admin Android", "screenshots/mobile/android-admin-*.png", ".github/workflows/mobile-screenshots.yml"),
    ("Lucy Admin iOS", "screenshots/mobile/ios-admin-*.png", ".github/workflows/mobile-screenshots.yml"),
    ("Corgi Lucy Client Android", "screenshots/client/*.png", "apps/vpn-client/android/app/src/androidTest/java/shop/corgi/client/ClientScreensTest.kt"),
    ("Telegram Mini App", "docs/img/miniapp-*.png", "scripts/screenshots/miniapp.mjs"),
    ("Превью чата бота", "docs/img/bot-*.png", "scripts/screenshots/bot_chat.py"),
    ("Карточки магазинов Android и iOS", "mobile/store/screenshots/**/*.png", "scripts/store/render.py"),
)


def render(root=ROOT):
    tracked = set(subprocess.check_output(["git", "ls-files", "-z", "--", "screenshots", "mobile/store/screenshots", "docs/img"],
                                          cwd=root).decode().split("\0"))
    rows = []
    seen = defaultdict(list)
    paths = set()
    for product, pattern, source in GROUPS:
        files = sorted(file for file in root.glob(pattern) if file.relative_to(root).as_posix() in tracked)
        if product.startswith("VPN Shop"):
            files = [file for file in files if "-admin-" not in file.name]
        if not files or not (root / source).is_file():
            raise ValueError(f"Missing evidence in {pattern} or {source}")
        sizes = Counter()
        for file in files:
            name = file.relative_to(root).as_posix()
            if name in paths:
                raise ValueError(f"Capture classified twice: {name}")
            paths.add(name)
            raw = file.read_bytes()
            if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR" or raw[-8:-4] != b"IEND":
                raise ValueError(f"Invalid PNG: {name}")
            width, height = struct.unpack(">II", raw[16:24])
            if not width or not height:
                raise ValueError(f"Zero-sized PNG: {name}")
            sizes[width, height] += 1
            seen[hashlib.sha256(raw).hexdigest()].append(name)
        dimensions = ", ".join(f"{w}×{h} ({n})" for (w, h), n in sorted(sizes.items(), key=lambda x: (-x[1], x[0])))
        rows.append(f"| {product} | {len(files)} | {dimensions} | [{source}](../{source}) |")

    lines = ["# Покрытие экранов изображениями", "",
             f"В проверяемых каталогах {len(paths)} PNG-файлов и {len(seen)} различных значений SHA-256. "
             "Таблица учитывает сохранённые изображения. Источник указывает сценарий их получения.", "",
             "| Интерфейс или материал | Файлов | Размеры в пикселях (количество) | Сценарий |",
             "| --- | ---: | --- | --- |", *rows, "", "## Одинаковые файлы", ""]
    duplicates = [sorted(group) for group in seen.values() if len(group) > 1]
    for group in sorted(duplicates):
        lines.append("- " + ", ".join(f"[{name}](../{name})" for name in group))
    if not duplicates:
        lines.append("Совпадений по SHA-256 нет.")
    lines.extend(["", "## Границы проверки", "",
        "Браузерные сценарии и мобильные сборки используют демонстрационные данные. "
        "Превью Telegram-бота смоделированы по текстам и баннерам бота. Карточки магазинов оформлены из исходных снимков.",
        "Для подтверждения оплаты, соединения VPN или запуска на физическом устройстве нужны отдельные результаты тестов. "
        "Для привязки к новой версии сохраните ссылку на запуск, ревизию сборки и результат сценария.",
        "Соответствие пунктов меню Lucy Admin Web существующим файлам проверяет [test_screenshots.py](../tests/test_screenshots.py).",
        "", "Пересчёт выполняется командой `python3 scripts/audit/check_screenshots.py`. "
        "Для проверки сохранённой таблицы используйте `python3 scripts/audit/check_screenshots.py --check`.", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = render()
    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != output:
            raise SystemExit("Screenshot inventory is stale")
    else:
        TARGET.write_text(output, encoding="utf-8")
