"""v28.90.0 (stage 20, N2): the project's licence and the notices of what came from elsewhere stay complete.

* LICENSE and mobile/LICENSE are the same text (the apps' sources carry the licence too);
* every project the code names as its source — «after owner/repo», «(owner/repo, MIT)», «MIT, (c) …» — is listed in
  THIRD_PARTY_NOTICES.md, so a new borrowing cannot slip in without its notice;
* README and the notices name the same edition of the licence as LICENSE."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "backend/app", ROOT / "apps/lucy-admin/web/src", ROOT / "apps/user-cabinet/src", ROOT / "scripts", ROOT / "mobile", ROOT / "apps", ROOT / "packages"]
REPO = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_.-]+/[A-Za-z0-9][A-Za-z0-9_.-]+)\s*(?:\(|,)\s*MIT\b")
AFTER = re.compile(r"\b[Aa]fter ([A-Za-z0-9][A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?) \(MIT")


def borrowed() -> set[str]:
    out = set()
    for base in SOURCES:
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".kt", ".swift", ".sh", ".cjs"} or "node_modules" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            out |= {m.lower() for m in REPO.findall(text)} | {m.lower() for m in AFTER.findall(text)}
    return out


def test_licence_copies_are_identical_and_edition_is_consistent():
    licence = (ROOT / "LICENSE").read_text()
    assert licence == (ROOT / "mobile/LICENSE").read_text()
    edition = re.search(r"Source License (\d+\.\d+)", licence).group(1)
    for doc in ("README.md", "THIRD_PARTY_NOTICES.md"):
        assert f"Source License {edition}" in (ROOT / doc).read_text(), doc
    assert "только идеи" in licence and "Commons Clause" in licence and "AGPL-3.0" in licence


def test_every_borrowed_project_has_a_notice():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text().lower()
    found = borrowed()
    assert found, "the scan finds the known borrowings"
    missing = sorted(name for name in found if name.split("/")[-1] not in notices)
    assert not missing, f"no THIRD_PARTY_NOTICES.md entry for: {missing}"
