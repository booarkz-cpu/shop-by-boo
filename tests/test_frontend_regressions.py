"""v28.58.0: regressions in the admin panel and cabinet sources that the TypeScript compiler does not catch.

* BUG-H1/H2: both API clients read answers through ``readJsonBody`` (apps/user-cabinet/src/http-json.ts, unit-tested by
  vitest in apps/user-cabinet/src/http-json.test.tsx); the old ``try { d = await r.json() } catch {}`` must not come back.
* BUG-H3: «Документы» had a second copy of ``banner`` nested in ``edit``.
* The admin image copies single files of the cabinet; a shared file it imports but does not copy breaks the
  Docker build only, so every import from ../../cabinet/src must have its COPY line."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWALLOW = re.compile(r"try\s*\{\s*d\s*=\s*await\s+r\.json\(\)\s*;?\s*\}\s*catch\s*\{\s*\}")


def test_api_clients_do_not_swallow_non_json_answers():
    for path in ("apps/lucy-admin/web/src/main.tsx", "apps/user-cabinet/src/main.tsx"):
        source = (ROOT / path).read_text()
        assert not SWALLOW.search(source), path
        assert "readJsonBody(r, path)" in source.replace(",path", ", path"), path


def test_documents_editor_defines_banner_once():
    source = (ROOT / "apps/lucy-admin/web/src/documents.tsx").read_text()
    assert source.count("async function banner(") == 1


def test_admin_image_copies_every_shared_cabinet_file():
    imported = set()
    for file in (ROOT / "apps/lucy-admin/web/src").rglob("*.ts*"):
        for name in re.findall(r"""from\s+["']\.\./(?:\.\./)+apps/user-cabinet/src/([\w./-]+)["']""", file.read_text()):
            imported.add(name)
    dockerfile = (ROOT / "apps/lucy-admin/web/Dockerfile").read_text()
    assert imported, "admin shares components with the cabinet"
    for name in sorted(imported):
        candidates = [f"apps/user-cabinet/src/{name}{ext}" for ext in ("", ".ts", ".tsx")]
        assert any(f"COPY {c} " in dockerfile for c in candidates), f"apps/lucy-admin/web/Dockerfile does not copy {name}"
