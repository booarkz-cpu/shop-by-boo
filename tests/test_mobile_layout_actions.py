"""Every action of the server-driven app layout is implemented by the customer apps (v28.131.0, «copy_masque»).

An app draws no button whose action it does not know, so a missing action is a silently missing button."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_ONLY = {"vpn_mode", "vpn_server", "split_tunnel"}       # the embedded engine exists only on Android


def _between(text: str, start: str, end: str) -> set[str]:
    i = text.index(start)
    return set(re.findall(r'"([a-z_]+)"', text[i:text.index(end, i)]))


def test_both_apps_know_every_layout_action():
    backend = (ROOT / "backend/app/mobile_layout.py").read_text(encoding="utf-8")
    actions = set(re.findall(r'^    "([a-z_]+)": "', backend[backend.index("ACTIONS: dict"):backend.index("Action = Literal")], re.M))
    android = _between((ROOT / "apps/vpn-shop/android/app/src/main/java/shop/remnawave/user/ui/AppLayout.kt").read_text(encoding="utf-8"),
                       "val KNOWN_ACTIONS", ")")
    ios = _between((ROOT / "apps/vpn-shop/ios/VpnShopUser/LayoutUI.swift").read_text(encoding="utf-8"), "let knownActions", "]")
    assert "copy_masque" in actions
    assert actions == android
    assert actions - ANDROID_ONLY == ios


def test_masque_button_is_in_the_default_layout_for_subscribers():
    from app import mobile_layout
    section = next(s for s in mobile_layout.DEFAULT_SECTIONS if s["id"] == "subscription")
    button = next(b for b in section["buttons"] if b["action"] == "copy_masque")
    assert button["audience"] == "subscribed" and button["label"]["ru"] == "Скопировать ссылку MASQUE"
