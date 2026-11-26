"""Current operator entrypoints must link to available guides."""
import re
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = json.loads((ROOT/'docs/current-guides.json').read_text())['guides']


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
