"""v28.59.0 (stage 5): docs/ru/new/DATABASE_SCHEMA.md is generated from the models and kept current."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_database_schema_document_matches_the_models():
    spec = importlib.util.spec_from_file_location("db_schema", ROOT / "scripts/generate-db-schema.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (ROOT / "docs/ru/new/DATABASE_SCHEMA.md").read_text() == module.render(), \
        "run: python scripts/generate-db-schema.py"
