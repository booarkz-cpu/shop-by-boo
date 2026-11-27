"""v28.76.0 (stage 17): every section of the admin panel has a screenshot, and the README shows only files that exist.

The set is rebuilt by ``apps/lucy-admin/web/scripts/screenshots-catalog.mjs`` (Playwright on the browser fixture with demo data);
numbers of existing sections are kept, new sections get the next numbers."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots/admin_panel"


def tabs() -> list[str]:
    """Sections of the side menu (SECTION_GROUPS); EXTRA_SECTIONS are reached from other screens."""
    text = (ROOT / "apps/lucy-admin/web/src/sections.ts").read_text()
    menu = text[text.index("export const SECTION_GROUPS"):text.index("export const EXTRA_SECTIONS")]
    return re.findall(r'\{tab: "([A-Za-z0-9]+)"', menu)


def test_every_admin_section_has_a_screenshot():
    files = {m.group(1): name for name in (p.name for p in SHOTS.glob("*.png"))
             if (m := re.match(r"^\d{2,3}_([A-Za-z0-9]+)\.png$", name))}
    missing = [t for t in tabs() if t not in files]
    assert not missing, f"no screenshot for sections {missing}: run apps/lucy-admin/web/scripts/screenshots-catalog.mjs"
    numbers = [name.split("_", 1)[0] for name in files.values()]
    assert len(numbers) == len(set(numbers)), "two screenshots share a number"


def test_readme_images_exist():
    for doc in ("README.md", "README.en.md", "README.uk.md", "screenshots/README.md"):
        path = ROOT / doc
        source = path.read_text()
        refs = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", source)
        refs += re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', source)
        for ref in refs:
            if not ref.startswith(("https://", "http://")):
                assert (path.parent / ref).is_file(), f"{doc}: {ref} is missing"


def test_regenerating_gallery_preserves_the_landing_page(tmp_path):
    import json
    import shutil
    import subprocess
    import sys

    script = Path("scripts/screenshots/readme_admin.py")
    gallery = Path("screenshots/README.md")
    for path in (script, gallery, Path("README.md")):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, tmp_path / path)
    shot = "02_dashboard.png"
    index = tmp_path / "index.json"
    index.write_text(json.dumps([{"group": "Магазин", "label": "Обзор", "description": "Сводка", "file": shot}]))
    before = (tmp_path / gallery).read_text()
    subprocess.run([sys.executable, str(tmp_path / script), str(index)], check=True)
    after = (tmp_path / gallery).read_text()
    start, end = "#### Админ-панель\n", "#### Личный кабинет пользователя\n"
    assert after.split(start)[0] == before.split(start)[0]
    assert after.split(end)[1] == before.split(end)[1]
    assert f"![Обзор](admin_panel/{shot})" in after and (SHOTS / shot).is_file()
    assert (tmp_path / "README.md").read_bytes() == (ROOT / "README.md").read_bytes()
