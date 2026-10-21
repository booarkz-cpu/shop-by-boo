"""Source checks read the assembled shop module, admin entry, and installer."""
import base64
import os
import tempfile

# Import-time StaticFiles setup must use a writable isolated directory on CI.
_test_media = tempfile.TemporaryDirectory(prefix="vpnshop-tests-media-")
os.environ.setdefault("MEDIA_DIR", _test_media.name)
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

_read_text = Path.read_text


def _assembled_read_text(self, *args, **kwargs):
    text = _read_text(self, *args, **kwargs)
    if self.name == "main.py" and "MAIN_PY_ASSEMBLED_FROM_PARTS" in text:
        parts = self.resolve().parent / "main_src"
        chunks = [_read_text(parts / f"part-{i:02d}", encoding="utf-8") for i in range(11)]
        return "".join(chunks).replace("{{ARROW}}", chr(0x2192)).replace("{{EMDASH}}", chr(0x2014))
    if self.name == "main.tsx" and "MAIN_TSX_ASSEMBLED_FROM_PARTS" in text:
        parts = self.resolve().parent / "main_src"
        chunks = [_read_text(path, encoding="utf-8") for path in sorted(parts.glob("part-*"))]
        return "".join(chunks)
    if self.name == "install-vps.sh" and "INSTALLER_ASSEMBLED_FROM_PARTS" in text:
        parts = self.resolve().parent / "install-vps-src"
        chunks = [base64.b64decode(_read_text(path, encoding="utf-8").strip()) for path in sorted(parts.glob("part-*"))]
        return b"".join(chunks).decode("utf-8")
    return text


Path.read_text = _assembled_read_text
