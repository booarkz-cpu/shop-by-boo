"""Stage 19, C2: scripts/restore.sh puts a copy from scripts/backup.sh into an EMPTY installation and refuses
everything else (a changed copy, a running shop, a database with data). Docker is replaced by a fake that logs
commands; the copy itself is a real encrypted bundle. The full drill on real containers is scripts/ci/dr-drill.sh."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest
from test_backup_bundle import bundle, SECRET

ROOT = Path(__file__).parents[1]

FAKE_DOCKER = '''import os,subprocess,sys
args=sys.argv[1:]
with open(os.environ['COMMAND_LOG'],'a') as log:log.write(' '.join(args)+'\\n')
if 'config' in args:print('db\\nbackend\\nsupport_db\\nsupport_pro\\nvolume_init')
elif 'ps' in args:print(os.environ.get('RUNNING','').replace(',','\\n'))
elif 'psql' in args:print(os.environ.get('TABLES','0'))
elif '/project/scripts/backup_bundle.py' in args:
    raise SystemExit(subprocess.run([sys.executable,os.environ['ENCRYPT_SCRIPT'],args[-1]],env=os.environ).returncode)
elif 'pg_restore' in args or 'tar' in args:
    data=sys.stdin.buffer.read()
    with open(os.environ['COMMAND_LOG'],'a') as log:log.write(f'  stdin {len(data)} bytes\\n')
'''


def gz(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name); info.size = len(data); archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def make_copy(folder: Path, env_text: str = 'APP_SECRET=shop-test-secret\n', tamper_manifest=False) -> Path:
    parts = {'shop.dump': b'shop-dump', 'support.dump': b'support-dump', 'media.tar.gz': gz({'banner.png': b'png'}),
             'app-packages.tar.gz': gz({'app.apk': b'apk'}), 'support-uploads.tar.gz': gz({'a.txt': b'a'}),
             'environment.tar.gz': gz({'.env': env_text.encode()})}
    files = {name: hashlib.sha256(data).hexdigest() for name, data in parts.items()}
    if tamper_manifest:
        files['shop.dump'] = '0' * 64
    plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode='w') as archive:
        for name, data in {**parts, 'backup-manifest.json': json.dumps({'format': 1, 'source_version': '21.5.1', 'files': files}).encode()}.items():
            info = tarfile.TarInfo('./' + name); info.size = len(data); archive.addfile(info, io.BytesIO(data))
    sealed = io.BytesIO(); bundle.encrypt(io.BytesIO(plain.getvalue()), sealed, SECRET)
    path = folder / 'shop-20261106T000000Z-test.vpb'
    path.write_bytes(sealed.getvalue())
    (folder / (path.name + '.sha256')).write_text(f'{hashlib.sha256(sealed.getvalue()).hexdigest()}  {path.name}\n')
    return path


@pytest.fixture
def install(tmp_path):
    app = tmp_path / 'app'; app.mkdir()
    (app / '.env').write_text('APP_SECRET=shop-test-secret\n')
    (app / 'release-manifest.template.json').write_text('{"version":"21.5.1"}')
    copies = tmp_path / 'copies'; copies.mkdir()
    fake = tmp_path / 'bin'; fake.mkdir()
    (fake / 'docker').write_text('#!' + sys.executable + '\n' + FAKE_DOCKER); (fake / 'docker').chmod(0o755)
    env = {**os.environ, 'APP_DIR': str(app), 'PATH': f'{fake}:{os.environ["PATH"]}', 'BACKUP_BUNDLE_PASSWORD': SECRET.decode(),
           'COMMAND_LOG': str(tmp_path / 'commands.log'), 'ENCRYPT_SCRIPT': str(ROOT / 'scripts/backup_bundle.py')}
    return app, copies, env


def restore(env, path):
    return subprocess.run(['bash', str(ROOT / 'scripts/restore.sh'), str(path)], env=env, text=True, capture_output=True)


def log(env) -> str:
    return Path(env['COMMAND_LOG']).read_text() if Path(env['COMMAND_LOG']).exists() else ''


def test_a_copy_is_restored_into_an_empty_installation(install):
    app, copies, env = install
    result = restore(env, make_copy(copies))
    assert result.returncode == 0, result.stdout + result.stderr
    commands = log(env)
    assert 'exec -T db pg_restore --no-owner --no-privileges --exit-on-error -U vpnshop -d vpnshop' in commands
    assert 'exec -T support_db pg_restore --no-owner --no-privileges --exit-on-error -U support -d support' in commands
    for target in ('/data/media', '/data/app-packages', '/data/uploads'):
        assert f'-xzf - -C {target}' in commands
    # Files go in after volume_init gives the volumes to the service user.
    assert commands.index('run --rm --no-deps volume_init') < commands.index('-C /data/media')
    assert 'Secrets match this installation' in result.stdout
    saved = next(copies.glob('restored-env-*'))
    assert saved.stat().st_mode & 0o777 == 0o700 and (saved / '.env').read_text() == 'APP_SECRET=shop-test-secret\n'
    assert 'shop-test-secret' not in result.stdout + result.stderr


def test_different_secrets_are_named_but_never_printed(install):
    app, copies, env = install
    result = restore(env, make_copy(copies, env_text='APP_SECRET=the-old-secret\nYOOKASSA_SECRET_KEY=old-key\n'))
    assert result.returncode == 0, result.stderr
    assert 'WARNING: secrets of the copy differ' in result.stdout and 'APP_SECRET' in result.stdout and 'YOOKASSA_SECRET_KEY' in result.stdout
    assert 'the-old-secret' not in result.stdout + result.stderr and 'old-key' not in result.stdout + result.stderr


def test_a_changed_copy_is_refused_before_anything_is_touched(install):
    app, copies, env = install
    path = make_copy(copies)
    data = bytearray(path.read_bytes()); data[100] ^= 1; path.write_bytes(bytes(data))
    result = restore(env, path)
    assert result.returncode == 3 and 'does not match its SHA256' in result.stderr
    assert 'pg_restore' not in log(env)


def test_a_file_that_does_not_match_the_manifest_is_refused(install):
    app, copies, env = install
    result = restore(env, make_copy(copies, tamper_manifest=True))
    assert result.returncode != 0 and 'shop.dump does not match the manifest' in result.stderr
    assert 'pg_restore --no-owner' not in log(env)


def test_a_wrong_password_is_refused(install):
    app, copies, env = install
    path = make_copy(copies); env['BACKUP_BUNDLE_PASSWORD'] = 'not-the-right-password'
    result = restore(env, path)
    assert result.returncode == 3 and 'could not decrypt' in result.stderr
    assert 'pg_restore --no-owner' not in log(env)


@pytest.mark.parametrize('service', ['backend', 'worker', 'bot', 'support_pro', 'support_worker'])
def test_a_running_shop_is_never_overwritten(install, service):
    app, copies, env = install
    env['RUNNING'] = f'db,{service}'
    result = restore(env, make_copy(copies))
    assert result.returncode == 4 and f'{service} is running' in result.stderr
    assert 'pg_restore' not in log(env)


def test_a_database_with_data_is_never_overwritten(install):
    app, copies, env = install
    env['TABLES'] = '162'
    result = restore(env, make_copy(copies))
    assert result.returncode == 5 and 'not empty' in result.stderr
    assert 'pg_restore' not in log(env) and 'backup_bundle.py' not in log(env)
