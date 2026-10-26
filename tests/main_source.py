"""Source of backend/app/main.py as one text, with the sections moved to their own modules
(v28.28.0) put back where they used to be. Source-reading tests use this so that moving a
section out of main.py does not hide it from them."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend/app"
MARKER = re.compile(r"^# ---------- .*: moved to (\w+)\.py \(imported at the end of this file\) ----------\n\n", re.M)
TAIL = "\n\n# Sections moved out of this file; imported last so they can read every name above.\n"
# Late-bound references to main's own names (``shop.fulfill``) read as before the move.
LATE = re.compile(r"(?<![\w.])shop\.(?=[A-Za-z_])")


def module_body(name: str) -> str:
    text = (APP / f"{name}.py").read_text()
    body = text.split("from . import main as shop\n\n", 1)[1]
    body = body.rsplit("\n\n__all__ = [", 1)[0]
    return LATE.sub("", body)


def main_source() -> str:
    text = (APP / "main.py").read_text()
    if TAIL in text:
        text = text.split(TAIL, 1)[0] + "\n"
    return MARKER.sub(lambda m: module_body(m.group(1)) + "\n", text)


MODULES = [m.group(1) for m in MARKER.finditer((APP / "main.py").read_text())]
