"""v28.101.0 (N11): «Xray core watch» — the pinned AndroidLibXrayLite commit, the client's next version and the note."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("watch", ROOT / "scripts/mobile/xray-core-watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def test_the_pinned_commit_is_read_and_replaced():
    script = (ROOT / "scripts/mobile/build-xray-aar.sh").read_text()
    old = watch.current_commit(script)
    assert len(old) == 40
    new = watch.set_commit(script, "a" * 40)
    assert watch.current_commit(new) == "a" * 40 and new.count("a" * 40) == 1
    assert new.replace("a" * 40, old) == script, "nothing else changes"
    with pytest.raises(ValueError):
        watch.set_commit(script, "main; rm -rf /")


def test_the_client_gets_its_next_version_and_a_note():
    gradle = 'defaultConfig {\n        versionCode = 160\n        versionName = "1.6.0"\n'
    text, version = watch.bump_client(gradle)
    assert version == "1.6.1" and "versionCode = 161" in text and 'versionName = "1.6.1"' in text
    notes = "# Client\n\nintro\n\n## Версия 1.6.0 — x\n"
    out = watch.note(notes, "1.6.1", "v26.1.18", "b" * 40)
    assert out.index("## Версия 1.6.1") < out.index("## Версия 1.6.0") and "b" * 40 in out


def test_the_command_line(tmp_path):
    script = ROOT / "scripts/mobile/xray-core-watch.py"
    current = watch.current_commit((ROOT / "scripts/mobile/build-xray-aar.sh").read_text())
    same = subprocess.run([sys.executable, str(script), "--tag", "v1.2.3", "--commit", current], capture_output=True, text=True)
    assert same.returncode == 0 and same.stdout.strip() == "up-to-date"
    other = subprocess.run([sys.executable, str(script), "--tag", "v1.2.3", "--commit", "c" * 40], capture_output=True, text=True)
    assert other.returncode == 0 and other.stdout.startswith(f"update {current} {'c' * 40} ")
    assert watch.current_commit((ROOT / "scripts/mobile/build-xray-aar.sh").read_text()) == current, "without --write nothing changes"
    bad = subprocess.run([sys.executable, str(script), "--tag", "latest", "--commit", "c" * 40], capture_output=True, text=True)
    assert bad.returncode == 2


def test_the_workflow_starts_the_ci_of_its_branch():
    wf = (ROOT / ".github/workflows/xray-core-watch.yml").read_text()
    assert "gh workflow run ci.yml" in wf and "gh workflow run android-client.yml" in wf
    assert "--write" in wf and "auto/xray-core-" in wf
