"""v28.76.0 (stage 17): every section of the admin panel has a screenshot, and the README shows only files that exist.

The set is rebuilt by ``apps/lucy-admin/web/scripts/screenshots-catalog.mjs`` (Playwright on the browser fixture with demo data);
numbers of existing sections are kept, new sections get the next numbers."""
import re
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

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
    for doc in ("README.md", "README.en.md", "README.uk.md"):
        path = ROOT / doc
        if not path.exists():
            continue
        for ref in re.findall(r"!\[[^\]]*\]\(((?:docs/)?screenshots/[^)\s]+)\)", path.read_text()):
            assert (ROOT / ref).is_file(), f"{doc}: {ref} is missing"


def test_inventory_counts_identical_tracked_frames_once_and_ignores_local_captures(tmp_path, monkeypatch):
    render = runpy.run_path(str(ROOT / "scripts/audit/check_screenshots.py"))["render"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    group = tmp_path / "screenshots"
    group.mkdir()
    source = ROOT / "screenshots/storefront_user/03_overview.png"
    for name in ("first.png", "copy.png", "untracked.png"):
        shutil.copyfile(source, group / name)
    scenario = tmp_path / "scenario.js"
    scenario.touch()
    subprocess.run(["git", "add", "screenshots/first.png", "screenshots/copy.png", "scenario.js"], cwd=tmp_path, check=True)
    monkeypatch.setitem(render.__globals__, "GROUPS", (("Кабинет", "screenshots/*.png", "scenario.js"),))
    output = render(tmp_path)
    assert output == render(tmp_path)
    assert "| Кабинет | 2 | 1440×900 (2) |" in output
    assert "screenshots/copy.png" in output and "screenshots/first.png" in output
    assert "untracked.png" not in output
    (group / "first.png").write_bytes(b"invalid screenshot")
    with pytest.raises(ValueError, match="Invalid PNG"):
        render(tmp_path)
