"""Layout stage 5: backend/ and support-pro/ live in services/. What an installed server relies on stays: the file its
updater reads the version from, the place of the Support Pro secrets, the names of the Docker services."""
import importlib.util
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "backend/app/main.py"
REAL = ROOT / "services/backend/app/main.py"


def version_as_an_older_updater_reads_it(path: Path) -> str:
    """scripts/github_release_fetch.py of the releases before stage 5, word for word."""
    text = path.read_text(encoding="utf-8")
    marker = 'APP_VERSION = "'
    start = text.index(marker) + len(marker)
    return text[start:text.index('"', start)]


def fetcher():
    spec = importlib.util.spec_from_file_location("github_release_fetch", ROOT / "scripts/github_release_fetch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_older_updater_still_takes_this_release_for_a_shop_release():
    # scripts/update.sh before stage 5: [[ -f "$UPDATE_STAGE/backend/app/main.py" ]] || «not a shop release»
    assert STUB.is_file()
    version = version_as_an_older_updater_reads_it(STUB)
    assert version == version_as_an_older_updater_reads_it(REAL), "the old path reports the version of the real application"
    # … and its manifest check: «Distribution manifest does not match the API version»
    manifest = json.loads((ROOT / "release-manifest.template.json").read_text(encoding="utf-8"))
    assert manifest["version"] == version
    assert "MAIN_PY_ASSEMBLED_FROM_PARTS" not in STUB.read_text(encoding="utf-8")


def test_the_file_at_the_old_path_is_not_an_application():
    text = STUB.read_text(encoding="utf-8")
    code = [line for line in text.split('"""')[-1].splitlines() if line.strip()]
    assert code == [f'APP_VERSION = "{version_as_an_older_updater_reads_it(STUB)}"'], "only the version: nothing to import or run"
    tracked = subprocess.run(["git", "ls-files", "backend", "support-pro"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert sorted(tracked) == ["backend/app/main.py", "support-pro/README.txt"], tracked


def test_the_new_updater_reads_both_layouts(tmp_path):
    module = fetcher()
    assert module.current_version(ROOT) == version_as_an_older_updater_reads_it(REAL)
    old = tmp_path / "installed-before-stage-5"
    (old / "backend/app").mkdir(parents=True)
    (old / "backend/app/main.py").write_text('import os\nAPP_VERSION = "21.4.0"\n')
    assert module.current_version(old) == "21.4.0"          # a server restored from an older snapshot
    assert module.api_dir(old) == old / "backend/app"
    new = tmp_path / "release"
    for folder, version in (("backend/app", "21.5.1"), ("services/backend/app", "21.5.1")):
        (new / folder).mkdir(parents=True)
        (new / folder / "main.py").write_text(f'APP_VERSION = "{version}"\n')
    assert module.api_dir(new) == new / "services/backend/app", "the real application wins over the file at the old path"
    assert module.api_dir(tmp_path / "empty") is None


def test_update_script_accepts_a_release_of_either_layout():
    text = (ROOT / "scripts/update.sh").read_text()
    assert '"$UPDATE_STAGE/services/backend/app/main.py"' in text and '"$UPDATE_STAGE/backend/app/main.py"' in text


def test_support_pro_secrets_stay_where_installed_servers_have_them():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert compose.count("env_file: ./support-pro/.env") == 3 and "services/support-pro/.env\n" not in compose
    assert "} > support-pro/.env" in (ROOT / "infrastructure/deployment/install-vps.sh").read_text()
    assert 'APP_DIR / "support-pro" / ".env"' in (ROOT / "scripts/auto_update.py").read_text()
    assert "root/'support-pro/.env'" in (ROOT / "scripts/configure-support-bridge.py").read_text()
    assert (ROOT / "support-pro/README.txt").is_file(), "the folder exists in a release: the installer writes the .env into it"
    assert (ROOT / "services/support-pro/.env.example").is_file()


def test_docker_builds_from_the_new_folders_and_keeps_the_service_names():
    names = set()
    for name in ("docker-compose.yml", "docker-compose.test.yml", "docker-compose.integration.yml", "services/support-pro/docker-compose.yml"):
        path = ROOT / name
        text = path.read_text()
        assert not re.search(r"context: \./(backend|support-pro)\b", text), name
        for context in re.findall(r"^\s*context:\s+(\./\S+)", text, re.M):
            assert (path.parent / context).is_dir(), f"{name}: {context}"
        names |= set(re.findall(r"^  ([a-z_]+):\n(?:    .*\n)*?    (?:build|image|extends):", text, re.M))
    for service in ("backend", "worker", "bot", "support_migrate", "support_pro", "support_worker"):
        assert service in names, f"{service} is what update scripts, Caddy and the panel call it"
    assert len(re.findall(r"context: \./services/backend\b", (ROOT / "docker-compose.yml").read_text())) >= 4


def test_nothing_live_points_at_the_old_folders():
    listed = subprocess.run(["git", "ls-files", ".github/workflows", "scripts", "tests", "infrastructure", "*.yml", "*.sh", "*.toml"],
                            cwd=ROOT, capture_output=True, text=True).stdout.split()
    old = re.compile(r"(?<![A-Za-z0-9_/.-])(?<!services/)(backend/(app|alembic|requirements|Dockerfile|scripts|worker\.py|entrypoint)|support-pro/(app|alembic|requirements|tests|nginx|scripts))")
    allowed = {"tests/test_layout_stage5.py", "scripts/github_release_fetch.py", "scripts/update.sh", "scripts/check-current-docs.py"}
    bad = []
    for rel in listed:
        path = ROOT / rel
        if rel in allowed or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        bad += [f"{rel}: {m.group(0)}" for m in old.finditer(text)]
    assert not bad, bad[:20]
