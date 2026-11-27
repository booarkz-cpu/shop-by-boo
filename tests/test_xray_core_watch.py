"""v28.101.0 (N11): «Xray core watch» — the pinned AndroidLibXrayLite commit, the client's next version and the note."""
import importlib.util
import shutil
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
    text, version = watch.bump_android(gradle, 1)
    assert version == "1.6.1" and "versionCode = 161" in text and 'versionName = "1.6.1"' in text
    notes = "# Client\n\nintro\n\n## Версия 1.6.0 — x\n"
    out = watch.note(notes, "1.6.1", "v26.1.18", "b" * 40)
    assert out.index("## Версия 1.6.1") < out.index("## Версия 1.6.0") and "b" * 40 in out
    assert "требуют подтверждения успешным CI" in out
    assert "до завершения проверок результат не подтверждён" in out
    assert "проверено сборкой AAR" not in out
    assert "проверено" not in out


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


@pytest.fixture
def watch_checkout(tmp_path):
    for path in (Path(watch.__file__), watch.AAR, watch.GRADLE, watch.NOTES, watch.NOTICES, watch.SHOP, watch.ADMIN,
                 *watch.IOS, *(ROOT / name for name in watch.READMES), ROOT / "MOBILE.md",
                 ROOT / "scripts/audit/check_release_changelog.py", ROOT / "CHANGELOG.md", ROOT / ".gitignore",
                 ROOT / "scripts/generate-project-map.py", ROOT / "release-manifest.template.json"):
        destination = tmp_path / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    (tmp_path / "docs/releases").mkdir(parents=True)
    (tmp_path / "docs/PROJECT_FILE_MAP.md").touch()
    return tmp_path


def test_write_updates_exact_android_notice_and_bumps_client_once(watch_checkout):
    root = watch_checkout
    script = root / Path(watch.__file__).relative_to(ROOT)
    aar, gradle, notes, notices = [root / p.relative_to(ROOT) for p in (watch.AAR, watch.GRADLE, watch.NOTES, watch.NOTICES)]
    current = watch.current_commit(aar.read_text())
    new = "f" * 40 if current != "f" * 40 else "e" * 40
    command = [sys.executable, str(script), "--tag", "v99.12.17", "--commit", new, "--write"]
    previous_notices = notices.read_text()
    previous_notes = notes.read_text()
    expected_gradle, version = watch.bump_android(gradle.read_text(), 1)
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert watch.current_commit(aar.read_text()) == new and gradle.read_text() == expected_gradle
    assert "v99.12.17" in notes.read_text() and f"Версия {version}" in notes.read_text()
    assert notes.read_text().endswith(previous_notes[previous_notes.index("\n## "):])
    notice_lines = notices.read_text().splitlines()
    old_lines = previous_notices.splitlines()
    changed = [(a, b) for a, b in zip(old_lines, notice_lines, strict=True) if a != b]
    assert len(changed) == 1
    assert current in changed[0][0] and f"тег `v99.12.17`, ревизия `{new}`" in changed[0][1]

    files = (aar, gradle, notes, notices)
    snapshot = [p.read_bytes() for p in files]
    again = subprocess.run(command, capture_output=True, text=True)
    assert again.returncode == 0 and again.stdout.strip() == "up-to-date"
    assert [p.read_bytes() for p in files] == snapshot


def test_stale_notice_aborts_before_any_file_changes(watch_checkout):
    root = watch_checkout
    files = [root / p.relative_to(ROOT) for p in (watch.AAR, watch.GRADLE, watch.NOTES, watch.NOTICES)]
    current = watch.current_commit(files[0].read_text())
    files[3].write_text(files[3].read_text().replace(current, "0" * 40))
    snapshot = [p.read_bytes() for p in files]
    result = subprocess.run(
        [sys.executable, str(root / Path(watch.__file__).relative_to(ROOT)), "--tag", "v99.12.17", "--commit", "f" * 40, "--write"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2 and "THIRD_PARTY_NOTICES.md" in result.stderr
    assert [p.read_bytes() for p in files] == snapshot


def test_write_rolls_back_an_interrupted_install(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "ROOT", tmp_path)
    first = tmp_path / "source"
    last = tmp_path / "version"
    first.write_text("old revision")
    first.chmod(0o755)
    last.write_text("old version")
    replace = Path.replace

    def fail_last(path, target):
        if target == last:
            raise OSError("read-only destination")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_last)
    with pytest.raises(OSError, match="read-only"):
        watch.write_update({first: "new revision", last: "new version"})
    assert first.read_text() == "old revision" and first.stat().st_mode & 0o777 == 0o755
    assert last.read_text() == "old version"


def test_the_workflow_starts_the_ci_of_its_branch():
    wf = (ROOT / ".github/workflows/xray-core-watch.yml").read_text()
    assert "gh workflow run ci.yml" in wf and "gh workflow run android-client.yml" in wf
    assert "--write" in wf and "auto/xray-core-" in wf
    assert "THIRD_PARTY_NOTICES.md" in next(line for line in wf.splitlines() if line.lstrip().startswith("git add "))
    assert "gh workflow run android-vpn-e2e.yml" in wf

def test_shared_engine_version_gate_watcher_and_release_notes_in_real_git_checkout(watch_checkout):
    root = watch_checkout
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    def run(*args, check=True):
        result = subprocess.run([sys.executable, str(root / "scripts/mobile/xray-core-watch.py"), *args], cwd=root,
                                capture_output=True, text=True)
        if check:
            assert result.returncode == 0, result.stderr
        return result

    git("init", "-q", "-b", "main")
    git("config", "user.name", "CI fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-qm", "previous engine")
    base = git("rev-parse", "HEAD")
    shop = root / watch.SHOP.relative_to(ROOT)
    admin = root / watch.ADMIN.relative_to(ROOT)
    client = root / watch.GRADLE.relative_to(ROOT)
    before_family = watch.gradle_version(shop.read_text())
    before_client = watch.gradle_version(client.read_text())
    previous_client = client.read_text()
    previous_shop = shop.read_text()
    readmes = {name: (root / name).read_text() for name in watch.READMES}
    changed = "e" * 40
    command = ("--tag", "v99.9.9", "--commit", changed)
    run(*command, "--write")
    next_shop, next_client = shop.read_text(), client.read_text()
    family = watch.gradle_version(next_shop)
    client_ver = watch.gradle_version(next_client)
    assert family == watch.gradle_version(admin.read_text()) and family[1] == before_family[1] + 10
    assert client_ver[1] == before_client[1] + 1
    for project in watch.IOS:
        data = (root / project.relative_to(ROOT)).read_text()
        assert f"CURRENT_PROJECT_VERSION = {family[1]};" in data
        assert f"MARKETING_VERSION = {family[0]};" in data
        assert f"MARKETING_VERSION = {before_family[0]};" not in data
    for name, reference in readmes.items():
        for label in watch.READMES[name]:
            old = next(x for x in reference.splitlines() if x.startswith(f"| {label} |"))
            new = next(x for x in (root / name).read_text().splitlines() if x.startswith(f"| {label} |"))
            assert old.split("|")[:-2] == new.split("|")[:-2] and old != new
    run("--check-against", base)
    client.write_text(previous_client)
    assert "higher versionName and versionCode" in run("--check-against", base, check=False).stderr
    client.write_text(next_client)
    shop.write_text(previous_shop)
    assert run("--check-against", base, check=False).returncode != 0
    shop.write_text(next_shop)
    git("add", ".")
    git("commit", "-qm", "actual engine and version change")
    source = git("rev-parse", "HEAD")
    run(*command, "--release-notes")
    mobile = watch.current_mobile_tag(root)
    assert "structure OK" in watch.validate_mobile(root, mobile)
    assert "structure OK" in watch.validate_client(root, client_ver[0])
    for tag in (mobile, f"client-v{client_ver[0]}"):
        text = (root / f"docs/releases/{tag}.md").read_text()
        assert f"/commit/{source}" in text and changed in text
    docs = git("diff", "--", "CHANGELOG.md")
    run(*command, "--release-notes")
    assert git("diff", "--", "CHANGELOG.md") == docs
    git("add", "CHANGELOG.md", "docs/releases/")
    generator = [sys.executable, "scripts/generate-project-map.py"]
    subprocess.run(generator, cwd=root, check=True)
    git("add", "docs/PROJECT_FILE_MAP.md")
    subprocess.run([*generator, "--check"], cwd=root, check=True)
    staged_map = git("show", ":docs/PROJECT_FILE_MAP.md")
    assert f"docs/releases/{mobile}.md" in staged_map
    assert f"docs/releases/client-v{client_ver[0]}.md" in staged_map
