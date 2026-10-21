"""Source text of the Next.js frontends for string-contract tests.

The customer cabinet and the Telegram Mini App are one application built for two
surfaces (NEXT_PUBLIC_SURFACE=miniapp), split into modules under cabinet/src.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bundle(folder: str) -> str:
    base = ROOT / folder
    files = sorted(p for p in base.rglob("*.ts*") if ".test." not in p.name and p.suffix in {".ts", ".tsx"})
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def cabinet_sources() -> str:
    return _bundle("cabinet/src")


def miniapp_sources() -> str:
    """The Mini App surface ships exactly the cabinet sources."""
    return cabinet_sources()


def cabinet_i18n() -> str:
    return (ROOT / "cabinet/src/i18n.tsx").read_text(encoding="utf-8")
