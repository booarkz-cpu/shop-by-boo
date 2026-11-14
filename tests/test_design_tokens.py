"""v28.61.0 (stage 7): the design tokens of the admin panel and the cabinet follow the brand book of the task.

Dark theme: page #090D16, cards #0F172A, blue accent (59 130 246), Inter for text and JetBrains Mono for
technical values. Both applications ship the fonts themselves (@fontsource), nothing is loaded from a CDN."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dark_tokens(css: str) -> dict[str, str]:
    # The first block whose selectors include :root and not the light theme holds the dark tokens.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    block = next(m.group(2) for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css, re.S)
                 if ":root" in m.group(1) and "light" not in m.group(1) and "--bg" in m.group(2))
    return {name: value.strip() for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def test_admin_and_cabinet_use_the_brand_palette_and_fonts():
    for path in ("apps/lucy-admin/web/src/theme.css", "apps/user-cabinet/src/style.css"):
        tokens = dark_tokens((ROOT / path).read_text())
        assert tokens["--bg"].lower() == "#090d16", path
        assert tokens["--surface"].lower() == "#0f172a", path
        assert tokens["--primary-rgb"] == "59 130 246", path
        assert tokens["--font-sans"].startswith('"Inter Variable"'), path
    assert "JetBrains Mono" in dark_tokens((ROOT / "apps/lucy-admin/web/src/theme.css").read_text())["--font-mono"]


def test_fonts_are_bundled_not_fetched():
    for app in ("admin", "cabinet"):
        deps = json.loads((ROOT / f"{app}/package.json").read_text())["dependencies"]
        assert "@fontsource-variable/inter" in deps and "@fontsource-variable/jetbrains-mono" in deps, app


def test_shared_block_states_exist_and_are_used():
    state = (ROOT / "apps/lucy-admin/web/src/components/ui/state.tsx").read_text()
    for name in ("export function LoadState", "export function EmptyState", "export function SuccessNote", "Повторить"):
        assert name in state
    users = [p.name for p in (ROOT / "apps/lucy-admin/web/src").glob("*.tsx") if "components/ui/state" in p.read_text()]
    assert len(users) >= 4, users
