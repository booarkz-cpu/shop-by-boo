"""v28.62.0 (stage 6): docs/ru/new/RBAC.md describes the roles and permissions exactly as the code grants them."""
import re
from pathlib import Path

from app.security import PERMISSION_LABELS, PERMISSIONS

DOC = Path(__file__).resolve().parents[1] / "docs/ru/new/RBAC.md"


def test_permission_table_matches_the_code():
    text = DOC.read_text()
    roles = list(PERMISSIONS)
    header = next(line for line in text.splitlines() if line.startswith("| Право | Что даёт |"))
    assert [c.strip() for c in header.strip("|").split("|")][2:] == roles
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\| `([a-z0-9_.]+)` \| (.+?) \| ((?:[✓·] \| )*[✓·]) \|$", line)
        if m:
            rows[m.group(1)] = (m.group(2), m.group(3).split(" | "))
    assert set(rows) == set(PERMISSION_LABELS)
    for key, (label, marks) in rows.items():
        assert label == PERMISSION_LABELS[key], key
        assert marks == ["✓" if key in PERMISSIONS[r] else "·" for r in roles], key


def test_role_sizes_match_the_code():
    text = DOC.read_text()
    for role, perms in PERMISSIONS.items():
        assert f"| `{role}` | {len(perms)} |" in text, role
