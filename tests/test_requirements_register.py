"""The requirements register (docs/REQUIREMENTS_MASTER_REGISTER.md) is built from the owner's master prompt.
A requirement cannot be dropped or reworded silently, and a PASS cannot stand without evidence."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
FILES = ['scripts/audit/requirements_register.py', 'docs/prompts/MASTER_PROMPT_V6.md', 'docs/requirements/status.json',
         'docs/requirements/register.json', 'docs/REQUIREMENTS_MASTER_REGISTER.md', 'docs/REQUIREMENTS_CHANGELOG.md']


def copy(tmp_path: Path) -> Path:
    for name in FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    return tmp_path


def run(root: Path, *args: str):
    return subprocess.run([sys.executable, str(root / FILES[0]), *args], text=True, capture_output=True)


def test_the_committed_register_matches_the_prompt_and_the_statuses():
    result = run(ROOT, '--check')
    assert result.returncode == 0, result.stderr
    entries = json.loads((ROOT / 'docs/requirements/register.json').read_text())
    assert len(entries) == len({entry['id'] for entry in entries}) >= 653
    assert all(entry['lines'][0] <= entry['lines'][1] for entry in entries)


def test_a_requirement_removed_from_the_prompt_is_refused(tmp_path):
    root = copy(tmp_path)
    prompt = root / 'docs/prompts/MASTER_PROMPT_V6.md'
    text = prompt.read_text()
    line = 'Ни одна кнопка не должна быть декоративной или фиктивной.'
    assert line in text
    prompt.write_text(text.replace(line, '', 1))
    assert run(root, '--check').returncode == 1
    result = run(root)  # rewriting does not help either: a requirement cannot disappear
    assert result.returncode == 1 and 'пропали' in result.stderr


def test_a_pass_without_evidence_or_with_a_missing_file_is_refused(tmp_path):
    root = copy(tmp_path)
    status = root / 'docs/requirements/status.json'
    data = json.loads(status.read_text())
    data['REQ-GOV-0001'] = {'status': 'PASS', 'evidence': []}
    status.write_text(json.dumps(data))
    assert 'без доказательства' in run(root, '--check').stderr
    data['REQ-GOV-0001'] = {'status': 'PASS', 'evidence': ['docs/NO_SUCH_FILE.md']}
    status.write_text(json.dumps(data))
    assert 'доказательство не найдено' in run(root, '--check').stderr
    data['REQ-GOV-0001'] = {'status': 'BLOCKED_EXTERNAL', 'evidence': []}
    status.write_text(json.dumps(data))
    assert 'нужно примечание' in run(root, '--check').stderr


def test_the_payment_inventory_matches_the_code_and_names_what_is_missing():
    script = ROOT / 'scripts/audit/check_payment_provider_registry.py'
    result = subprocess.run([sys.executable, str(script), '--check'], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    text = (ROOT / 'docs/PAYMENT_PROVIDER_INVENTORY.md').read_text()
    # A gateway of the checkout queue is listed as implemented; one the code does not have is never shown as working.
    assert '| YooKassa | `yookassa` | `IMPLEMENTED` |' in text
    assert '| Heleket | `heleket` | — | **Нет в коде** |' in text
    assert 'настоящими деньгами не проверена ни для одной кассы' in text


def test_spelling_requirement_is_added_without_changing_the_legacy_653_entries():
    import hashlib

    entries = json.loads((ROOT / 'docs/requirements/register.json').read_text())
    legacy = [entry for entry in entries if entry['lines'][1] <= 2499]
    serialized = json.dumps(legacy, ensure_ascii=False, indent=1) + '\n'
    assert len(legacy) == 653
    assert hashlib.sha256(serialized.encode()).hexdigest() == 'bc5acb91ac449d994313958ec80d5e8fb8251e43f0d55a89a484e0e2708d9b46'
    spelling = next(entry for entry in entries if entry['id'] == 'REQ-UI-0011')
    source = (ROOT / 'docs/prompts/MASTER_PROMPT_V6.md').read_text().splitlines()
    first, last = spelling['lines']
    requirement = '\n'.join(source[first-1:last])
    assert spelling['path'] == 'Часть IV → 41. Орфография во всех продуктах и документации'
    assert 'орфографических ошибок' in requirement and 'RU/EN/UK' in requirement
    assert hashlib.sha256(requirement.encode()).hexdigest()[:12] == spelling['sha']


def test_tabular_changelog_requirement_preserves_all_prior_654_requirements():
    import hashlib

    entries = json.loads((ROOT / 'docs/requirements/register.json').read_text())
    legacy = [entry for entry in entries if entry['lines'][1] <= 2503]
    assert len(legacy) == 654
    assert hashlib.sha256((json.dumps(legacy, ensure_ascii=False, indent=1) + '\n').encode()).hexdigest() == 'f6ba5f4d80f709d8566dbff4b0e4f4450c6828774b5151e9b2b1bb8b190b6806'
    source = (ROOT / 'docs/prompts/MASTER_PROMPT_V6.md').read_text()
    prior_source = ''.join(source.splitlines(keepends=True)[:2503])
    assert hashlib.sha256(prior_source.encode()).hexdigest() == '78ff6abc6cacbc7e6ab0b13c2cd79a6e40f4ebbe6b6b38c58a411f7beb5c540e'
    entry = next(item for item in entries if item['id'] == 'REQ-DOC-0038')
    first, last = entry['lines']
    text = '\n'.join(source.splitlines()[first-1:last])
    assert 'каждого нового релиза' in entry['path']
    assert 'всех изменений' in text and 'табличном виде' in text
    assert 'грамматических' in text and 'орфографических' in text
    assert hashlib.sha256(text.encode()).hexdigest()[:12] == entry['sha']
