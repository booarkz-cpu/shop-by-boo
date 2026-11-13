"""«Корги Люси: клиент»: its banners are its own sections, not the shop app's (owner's screenshot of 2026-11-13:
«О приложении» showed «Информация — ответы, правила и документы»)."""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT / "mobile/android-client/app/src/main"
ASSETS = CLIENT / "assets/banners"
RENDER = ROOT / "scripts/bot-banners/render.py"


def client_sections() -> dict:
    tree = ast.parse(RENDER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CLIENT_SECTIONS":
            return ast.literal_eval(node.value)
    raise AssertionError("CLIENT_SECTIONS not found")


def used_assets() -> set:
    code = "".join(p.read_text(encoding="utf-8") for p in (CLIENT / "java").rglob("*.kt"))
    return set(re.findall(r'Banner\("([a-z0-9-]+)"', code)) | set(re.findall(r'\("(client-[a-z]+)" to \{', code))


def test_every_banner_the_client_shows_is_its_own_and_exists():
    used = used_assets()
    assert {"client-servers", "client-settings", "client-about"} <= used
    assert all(name.startswith("client-") for name in used), used
    for name in used:
        assert (ASSETS / f"{name}.jpg").is_file(), name


def test_the_shop_banners_are_gone_from_the_client():
    assert not list(ASSETS.glob("app-*.jpg"))


def test_banners_match_the_generator_and_say_what_the_section_does():
    sections = client_sections()
    assert {p.stem for p in ASSETS.glob("client-*.jpg")} == set(sections)
    assert used_assets() == set(sections)
    assert sections["client-about"][1] == "Версия, ядро Xray и обновления"
    for title, caption, _sticker, _accent in sections.values():
        assert "правила" not in caption.lower() and "документ" not in caption.lower()
