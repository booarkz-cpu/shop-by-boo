"""docs/architecture: the set the master prompt names exists, and its generated parts are current."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/architecture"
REQUIRED = ["SYSTEM_OVERVIEW.md", "CONTEXT_MAP.md", "CONTAINER_DIAGRAM.md", "DATA_FLOW.md", "DOMAIN_BOUNDARIES.md", "API_CATALOG.md",
            "EVENT_CATALOG.md", "THREAT_MODEL.md", "DEPLOYMENT_TOPOLOGY.md"]


def test_the_named_documents_exist_and_are_not_stubs():
    for name in REQUIRED:
        text = (DOCS / name).read_text(encoding="utf-8")
        assert text.startswith("# ") and len(text) > 400, name
    assert (DOCS / "ADR").is_dir()


def test_generated_documents_are_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/generate-architecture-docs.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_decision_record_has_the_required_parts():
    records = sorted(p for p in (DOCS / "ADR").glob("0*.md") if not p.name.startswith("0000"))
    assert len(records) >= 5
    index = (DOCS / "ADR/README.md").read_text(encoding="utf-8")
    for path in records:
        text = path.read_text(encoding="utf-8")
        for part in ("- Дата: 20", "- Статус: ", "## Контекст", "## Варианты", "## Решение", "## Последствия", "## Риски", "## Обратимость"):
            assert part in text, f"{path.name}: {part}"
        assert f"]({path.name})" in index, f"{path.name} is not in ADR/README.md"


def test_every_compose_service_is_described():
    import yaml

    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    text = (DOCS / "CONTAINER_DIAGRAM.md").read_text(encoding="utf-8")
    assert all(f"| `{name}` |" in text for name in services)
