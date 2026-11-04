"""v28.76.0 (stage 17): every section of the admin panel has a screenshot, and the README shows only files that exist.

The set is rebuilt by ``admin/scripts/screenshots-catalog.mjs`` (Playwright on the browser fixture with demo data);
numbers of existing sections are kept, new sections get the next numbers."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots/admin_panel"


def tabs() -> list[str]:
    """Sections of the side menu (SECTION_GROUPS); EXTRA_SECTIONS are reached from other screens."""
    text = (ROOT / "admin/src/sections.ts").read_text()
    menu = text[text.index("export const SECTION_GROUPS"):text.index("export const EXTRA_SECTIONS")]
    return re.findall(r'\{tab: "([A-Za-z0-9]+)"', menu)


def test_every_admin_section_has_a_screenshot():
    files = {m.group(1): name for name in (p.name for p in SHOTS.glob("*.png"))
             if (m := re.match(r"^\d{2,3}_([A-Za-z0-9]+)\.png$", name))}
    missing = [t for t in tabs() if t not in files]
    assert not missing, f"no screenshot for sections {missing}: run admin/scripts/screenshots-catalog.mjs"
    numbers = [name.split("_", 1)[0] for name in files.values()]
    assert len(numbers) == len(set(numbers)), "two screenshots share a number"


def test_readme_images_exist():
    for doc in ("README.md", "README.en.md", "README.uk.md"):
        path = ROOT / doc
        if not path.exists():
            continue
        for ref in re.findall(r"!\[[^\]]*\]\(((?:docs/)?screenshots/[^)\s]+)\)", path.read_text()):
            assert (ROOT / ref).is_file(), f"{doc}: {ref} is missing"
