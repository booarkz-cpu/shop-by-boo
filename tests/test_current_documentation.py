"""Current operator entrypoints must link to available guides."""
import re
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = json.loads((ROOT/'docs/current-guides.json').read_text())['guides']


@pytest.mark.parametrize(("page", "locale"), [("README.md", "ru"), ("README.en.md", "en"), ("README.uk.md", "uk")])
def test_readme_has_operator_guides_for_its_language(page, locale):
    links = set(re.findall(r"\]\(([^)\s]+)\)", (ROOT / page).read_text()))
    topics = ("Admin", "Backup", "Installation", "Mobile", "Payments", "Remnawave", "Security", "Troubleshooting", "Updates")
    expected = {f"docs/wiki/{locale}/{topic}.md" for topic in topics}
    expected.update({"docs/architecture/README.md", "docs/architecture/CONTAINER_DIAGRAM.md", "docs/ru/new/TERMUX_GUIDE.md"})
    assert expected <= links, (page, sorted(expected - links))


def test_readme_main_version_column_matches_apps_and_compose():
    gradle = "android/app/build.gradle.kts"

    def android_version(product):
        text = (ROOT / "apps" / product / gradle).read_text()
        return re.search(r'^\s*versionName = "([^"]+)"', text, re.M)[1]

    shop_versions = {android_version(product) for product in ("vpn-shop", "lucy-admin")}
    for product in ("vpn-shop", "lucy-admin"):
        project, = (ROOT / "apps" / product / "ios").glob("*.xcodeproj/project.pbxproj")
        shop_versions.update(re.findall(r"MARKETING_VERSION = ([\d.]+)", project.read_text()))
    compose = (ROOT / "docker-compose.yml").read_text()
    python = re.search(r"PYTHON_BASE_IMAGE:-python:([\d.]+)-", compose)[1]
    postgres = re.search(r"POSTGRES_IMAGE:-postgres:([\d.]+)-", compose)[1]
    for filename in ("README.md", "README.en.md", "README.uk.md"):
        rows = [line.split("|")[1:-1] for line in (ROOT / filename).read_text().splitlines()
                if line.startswith("|") and line.count("|") == 4]
        suite, = [cells for cells in rows if "Lucy Admin" in cells[0] and "Android" in cells[0]]
        client, = [cells for cells in rows if "Android" in cells[0] and "iOS" not in cells[0]]
        backend, = [cells for cells in rows if "Python / PostgreSQL" in cells[0]]
        assert {suite[-1].strip()} == shop_versions, filename
        assert client[-1].strip() == android_version("vpn-client"), filename
        assert backend[-1].strip() == f"{python} / {postgres}", filename


def test_first_ssh_login_checks_server_fingerprints(tmp_path):
    import base64
    import hashlib
    import subprocess

    command = 'ssh-keygen -l -E sha256 -f "$key"'
    public_keys = "/etc/ssh/ssh_host_*_key.pub"
    example = f"for key in {public_keys}; do\n  {command}\ndone"
    for name in ("README.md", "README.en.md", "README.uk.md"):
        guide = (ROOT / name).read_text(encoding="utf-8")
        step = guide.split("ssh root@", 1)[1].split("\n### ", 1)[0]
        assert f"```bash\n{example}\n```" in step, name
        assert step.index(example) < step.index("`yes`"), name
        assert "Ctrl+C" in step, name

    expected = set()
    for key_type in ("ed25519", "ecdsa"):
        private = tmp_path / f"ssh_host_{key_type}_key"
        subprocess.run(["ssh-keygen", "-q", "-t", key_type, "-N", "", "-f", str(private)], check=True)
        public = private.with_suffix(".pub").read_text().split()[1]
        digest = hashlib.sha256(base64.b64decode(public, validate=True)).digest()
        expected.add("SHA256:" + base64.b64encode(digest).decode().rstrip("="))

    result = subprocess.run(["bash", "-eu", "-c", example.replace("/etc/ssh/", "./")],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert {line.split()[1] for line in result.stdout.splitlines()} == expected


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


@pytest.mark.parametrize("fault", ["none", "with_support", "damaged", "missing", "unlisted", "incomplete_support"])
def test_documented_backup_manifest_check(tmp_path, fault):
    import hashlib
    import io
    import subprocess
    import tarfile

    guide = (ROOT / "docs/ru/BACKUP_CURRENT.md").read_text(encoding="utf-8")
    example, = re.findall(r"```bash\n(archive=/var/tmp/shop-recovery\.[^\n]+/recovery\.tar\n.*?)\n```", guide, re.S)
    contents = {name: name.encode() for name in ("shop.dump", "media.tar.gz", "app-packages.tar.gz", "environment.tar.gz")}
    if fault in ("with_support", "incomplete_support"):
        contents["support.dump"] = b"support"
    if fault == "with_support":
        contents["support-uploads.tar.gz"] = b"uploads"
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    contents["backup-manifest.json"] = json.dumps({"format": 1, "source_version": "test-release", "files": digests}).encode()
    if fault == "damaged":
        contents["shop.dump"] += b"changed"
    elif fault == "missing":
        del contents["media.tar.gz"]
    elif fault == "unlisted":
        contents["extra.txt"] = b"missing manifest entry"
    archive = tmp_path / "recovery.tar"
    with tarfile.open(archive, "w") as bundle:
        for name, data in contents.items():
            member = tarfile.TarInfo("./" + name)
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
    script = re.sub(r"^archive=.*", 'archive="$1"', example, count=1)
    result = subprocess.run(["bash", "-c", script, "verify", str(archive)], capture_output=True, text=True)
    valid = fault in ("none", "with_support")
    assert (result.returncode == 0) == valid, result.stderr
    if valid:
        assert "runtime/API" in result.stdout and "test-release" in result.stdout


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


@pytest.mark.parametrize('language', ('ru', 'en', 'uk'))
def test_wiki_setup_matches_full_build_profile_and_installer_hostnames(language):
    guide = (ROOT / 'docs/INSTALLATION.md').read_text()
    os_row, = [line for line in guide.splitlines() if line.startswith('| ОС |')]
    resources, = [line for line in guide.splitlines() if line.startswith('| Ресурсы |')]
    systems = re.findall(r'(?:Ubuntu|Debian) [0-9.]+', os_row)
    sizing = re.search(r'(\d+) vCPU, (\d+) ГБ RAM, (\d+) ГБ', resources)
    assert len(systems) == 2 and sizing
    home = (ROOT / 'docs/wiki' / language / 'Home.md').read_text()
    server, = [row for row in home.splitlines() if row.startswith('1. **')]
    assert all(system in server for system in systems), server
    cpu, ram, disk = sizing.groups()
    assert re.search(rf'\b{cpu} vCPUs?\b', server)
    assert re.search(rf'\b{ram} (?:ГБ|GB)\b.*\b{disk} (?:ГБ|GB)\b', server)
    installer = (ROOT / 'infrastructure/deployment/install-vps.sh').read_text()
    default_hosts = re.findall(r'^prompt (?:API|ADMIN|APP|CABINET|SUPPORT_PRO)_DOMAIN "[^"]+" "([\w-]+)\.\$\{BASE_DOMAIN\}"$', installer, re.M)
    assert len(default_hosts) == 5
    domains, = [row for row in home.splitlines() if row.startswith('2. **')]
    assert set(re.findall(r'`([\w-]+)`', domains)) == set(default_hosts)


def test_guides_index_reaches_each_topic_from_the_source_requirement():
    index = (ROOT / 'docs/INDEX.md').read_text()
    targets = {p.split('#')[0] for p in re.findall(r'\]\(([^)\s]+)\)', index)}
    expected = {
        'architecture/SYSTEM_OVERVIEW.md', 'INSTALLATION.md', 'ru/new/ADMIN_PANEL_GUIDE.md',
        'ru/new/USER_CABINET_GUIDE.md', '../CONTRIBUTING.md', 'wiki/ru/Payments.md',
        'ru/new/REMNAWAVE_INSTALLATION_GUIDE.md', 'ru/new/NODE_PLUGINS.md', 'MASQUE_PANEL.md',
        'ru/MOBILE_GUIDE.md', 'ru/BACKUP_CURRENT.md', 'wiki/ru/Updates.md', 'wiki/ru/Security.md',
    }
    assert expected <= targets, sorted(expected - targets)


def test_installation_guide_prepares_all_unconditional_required_answers():
    installer = (ROOT / 'infrastructure/deployment/install-vps.sh').read_text()
    required = set(re.findall(r'^prompt_required (\w+) ', installer, re.M))
    guide = (ROOT / 'docs/INSTALLATION.md').read_text()
    setup = guide.split('## 4. Установка одной командой', 1)[1].split('\n## ', 1)[0]
    documented = set(re.findall(r'`([A-Z_]+)`', setup))
    assert required and required <= documented, sorted(required - documented)


def test_documented_contributor_lint_checks_the_shipped_services():
    import shlex

    guide = (ROOT / 'CONTRIBUTING.md').read_text()
    ci = (ROOT / '.github/workflows/ci.yml').read_text()
    ruff, = set(re.findall(r'\bpip install (ruff==[\d.]+)', ci))
    assert f'pip install {ruff}' in guide
    commands = [shlex.split(row) for row in guide.splitlines() if row.startswith('ruff check ')]
    folders = [ROOT / item for command in commands for item in command[2:] if not item.startswith('-')]
    for source in ('services/backend/app/main.py', 'services/support-pro/app/main.py'):
        assert (ROOT / source).is_file()
        assert any((ROOT / source).is_relative_to(folder) for folder in folders), source


def test_mobile_installation_guide_uses_current_downloads_and_source_projects():
    guide = (ROOT / 'docs/ru/MOBILE_GUIDE.md').read_text()
    manifest = json.loads((ROOT / 'release-manifest.template.json').read_text())
    declared_tags = re.findall(r'Актуальный дистрибутив: `(v[\d.]+)`', guide)
    assert all(tag == manifest['distribution_tag'] for tag in declared_tags), declared_tags
    links = set(re.findall(r'\]\(([^)\s]+)\)', guide))
    assert '../../README.md#скачать-мобильные-приложения' in links
    architecture = (ROOT / 'docs/architecture/SYSTEM_OVERVIEW.md').read_text()
    architecture_links = set(re.findall(r'\]\(([^)\s]+)\)', architecture))
    project_links = {'../../apps/vpn-shop', '../../apps/vpn-client/android', '../../apps/lucy-admin'}
    assert project_links <= links and project_links <= architecture_links
