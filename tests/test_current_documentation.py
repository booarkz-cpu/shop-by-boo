"""Current operator entrypoints must link to available guides."""
import re
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = json.loads((ROOT/'docs/current-guides.json').read_text())['guides']


@pytest.mark.parametrize("filename", [
    "README.md", "README.en.md", "README.uk.md",
    "docs/wiki/ru/Backup.md", "docs/wiki/en/Backup.md", "docs/wiki/uk/Backup.md",
])
def test_recovery_entrypoints_match_the_cli_bundle(filename):
    guide = (ROOT / filename).read_text(encoding="utf-8")
    assert not re.search(r"\bpsql\b[^\n]*<\s*\S*backup\.sql\b", guide), filename
    assert ".vpb" in guide and "BACKUP_CURRENT.md" in guide


@pytest.mark.parametrize("record_type", ["wrong_digest", "other_backup", "correct"])
def test_backup_guide_checks_the_selected_archive_before_decryption(tmp_path, record_type):
    import hashlib
    import subprocess

    guide = (ROOT / "docs/ru/BACKUP_CURRENT.md").read_text(encoding="utf-8")
    example, = [block for block in re.findall(r"```bash\n(.*?)\n```", guide, re.S)
                if "backup_bundle.py decrypt" in block]
    bundle = tmp_path / "shop-TIMESTAMP-RANDOM.vpb"
    bundle.write_bytes(b"damaged copy")
    record = f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n"
    if record_type == "wrong_digest":
        record = f"{'0' * 64}  {bundle.name}\n"
    elif record_type == "other_backup":
        other = tmp_path / "shop-other.vpb"
        other.write_bytes(b"previous backup")
        record = f"{hashlib.sha256(other.read_bytes()).hexdigest()}  {other.name}\n"
    bundle.with_suffix(".vpb.sha256").write_text(record)
    example = example.replace("/var/backups/vpn-shop", str(tmp_path))
    installation = tmp_path / "missing-installation"
    example = example.replace("/opt/vpn-shop", str(installation))
    result = subprocess.run(["bash", "-x", "-c", example], input="", capture_output=True, text=True)
    assert result.returncode != 0
    assert "sha256sum" in result.stderr
    assert (f"cd {installation}" in result.stderr) == (record_type == "correct")


@pytest.mark.parametrize('filename',GUIDES)
def test_current_guide_links_exist(filename):
    path = ROOT / filename
    for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if re.match(r'^[a-zA-Z]+:',target) or target.startswith('#'):
            continue
        link = target.split('#',1)[0]
        assert (path.parent/link).exists(), f'{filename}: missing link {target}'


def test_generated_api_catalogue_matches_application():
    import importlib.util
    spec=importlib.util.spec_from_file_location('api_docs', ROOT/'scripts/generate-api-docs.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert (ROOT/'docs/API_ENDPOINTS.md').read_text()==module.render()


def test_external_links_in_acceptance_evidence_are_checked_separately_from_source_quotes(tmp_path):
    import runpy
    import shutil

    docs = tmp_path / "docs"
    docs.mkdir()
    checker = tmp_path / "scripts" / "check-external-links.py"
    checker.parent.mkdir()
    shutil.copyfile(ROOT / "scripts/check-external-links.py", checker)
    register = docs / "AUTONOMOUS_ACCEPTANCE_CHECKLIST.md"
    register.write_text(
        "Guide https://guide.invalid/intro\n"
        "| REQ-MIG-0009 | original \\| https://old.invalid/client https://shared.invalid/ref "
        "| migration | see [evidence](https://records.invalid/proof) |\n", encoding="utf-8")
    (docs / "operator.md").write_text("https://shared.invalid/ref\n", encoding="utf-8")

    links = runpy.run_path(str(checker))["collect"]("")
    assert set(links) == {"https://guide.invalid/intro", "https://records.invalid/proof", "https://shared.invalid/ref"}
    assert links["https://records.invalid/proof"] == [str(register.relative_to(tmp_path))]
    assert links["https://shared.invalid/ref"] == [str((docs / "operator.md").relative_to(tmp_path))]


def test_mobile_guide_uses_platform_specific_happ_sources():
    text = (ROOT / "docs/ru/MOBILE_GUIDE.md").read_text(encoding="utf-8")
    assert "[Happ для Android](https://github.com/Happ-proxy/happ-android)" in text
    assert "[Happ для iOS](https://github.com/Happ-proxy/happ-ios)" in text



@pytest.mark.parametrize("bad_configuration", [True, False], ids=["invalid-proxy", "no-http-response"])
def test_external_link_check_requires_a_working_http_transport(tmp_path, bad_configuration):
    import os
    import shutil
    import socket
    import subprocess
    import sys

    script = tmp_path / "scripts" / "check-external-links.py"
    script.parent.mkdir()
    shutil.copyfile(ROOT / "scripts/check-external-links.py", script)
    (tmp_path / "README.md").write_text("[Guide](https://guide.invalid/)", encoding="utf-8")
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        scheme = "invalid-proxy" if bad_configuration else "http"
        proxy = f"{scheme}://127.0.0.1:{unused_port.getsockname()[1]}"
        env = {k: v for k, v in os.environ.items() if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
        result = subprocess.run(
            [sys.executable, str(script), "--retries", "1", "--timeout", "1"],
            env={**env, "HTTPS_PROXY": proxy}, capture_output=True, text=True, timeout=15,
        )
    assert result.returncode == 2, result.stdout + result.stderr
    expected = "HTTP client setup failed" if bad_configuration else "No HTTP response"
    assert expected in result.stderr
    assert "BROKEN" not in result.stdout


@pytest.mark.parametrize('filename',GUIDES)
def test_current_guides_do_not_reference_invented_prerelease_tags(filename):
    manifest=json.loads((ROOT/'release-manifest.template.json').read_text())
    version=re.escape(manifest['version'])
    assert not re.search(r'v?'+version+r'-(?:alpha|beta|rc)\.\d+', (ROOT/filename).read_text()), filename

def test_project_map_lists_a_new_file_before_it_is_staged():
    """The map must know about a file that exists but is not ``git add``-ed yet.

    The generator used plain ``git ls-files``, which lists only the index. A file created and mapped in one
    step — the normal order while writing a release — was therefore absent from the map, the map then
    differed from the tree as soon as the file was staged, and CI failed on ``--check`` for a reason that
    had nothing to do with the content of any document. This broke the release pipeline twice, so the
    behaviour is pinned here instead of being left to the order of two commands.
    """
    import importlib.util
    import subprocess

    generator = ROOT / 'scripts/generate-project-map.py'
    assert '--others' in generator.read_text(encoding='utf-8'), "the generator must list untracked files too"

    spec = importlib.util.spec_from_file_location('project_map', generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    probe = ROOT / 'docs' / 'PROBE_UNTRACKED_DO_NOT_COMMIT.md'
    probe.write_text('probe', encoding='utf-8')
    try:
        staged = subprocess.run(['git', 'ls-files', '--', str(probe)], cwd=ROOT, capture_output=True, text=True)
        assert staged.stdout.strip() == '', "the probe must be untracked for this test to mean anything"
        rendered = module.render()
    finally:
        probe.unlink()
    assert 'PROBE_UNTRACKED_DO_NOT_COMMIT.md' in rendered, "an untracked file is part of the map"
