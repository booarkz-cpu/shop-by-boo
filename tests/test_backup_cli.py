"""The backup CLI captures both stores, stops writers and resumes after failure."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest
from test_backup_bundle import bundle, SECRET

ROOT=Path(__file__).parents[1]


@pytest.fixture
def install(tmp_path):
    app=tmp_path/'app';app.mkdir();(app/'support-pro').mkdir()
    (app/'.env').write_text('APP_SECRET=shop-test-secret\n')
    (app/'support-pro/.env').write_text('SESSION_SECRET=support-test-secret\n')
    (app/'release-manifest.template.json').write_text('{"version":"21.0.1"}')
    dest=tmp_path/'backups';fake=tmp_path/'bin';fake.mkdir()
    docker=fake/'docker'
    docker.write_text('#!'+sys.executable+'\n'+'''import io,os,subprocess,sys,tarfile
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['COMMAND_LOG'],'a') as log:log.write(' '.join(args)+'\\n')
if 'config' in args:print('db\\nbackend\\nworker\\nbot\\nsupport_db\\nsupport_pro\\nsupport_worker')
elif 'ps' in args:print('backend\\nworker\\nbot\\nsupport_pro\\nsupport_worker')
elif 'pg_dump' in args:
    if os.environ.get('FAIL_BACKUP')=='dump':raise SystemExit(1)
    sys.stdout.buffer.write(b'custom-database-dump')
elif 'pg_restore' in args:sys.stdin.buffer.read()
elif 'tar' in args:
    if os.environ.get('FAIL_BACKUP')=='files':raise SystemExit(1)
    with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
        info=tarfile.TarInfo('attachment.txt');info.size=4;archive.addfile(info,io.BytesIO(b'data'))
elif '/project/scripts/backup_bundle.py' in args:
    if os.environ.get('FAIL_BACKUP')=='encrypt':raise SystemExit(1)
    raise SystemExit(subprocess.run([sys.executable,os.environ['ENCRYPT_SCRIPT'],args[-1]],env=os.environ).returncode)
''')
    docker.chmod(0o755)
    env={**os.environ,'APP_DIR':str(app),'BACKUP_DEST':str(dest),'PATH':str(fake)+':'+os.environ['PATH'],
         'BACKUP_BUNDLE_PASSWORD':SECRET.decode(),'COMMAND_LOG':str(tmp_path/'commands.log'),'ENCRYPT_SCRIPT':str(ROOT/'scripts/backup_bundle.py')}
    return app,dest,env


def run(env):return subprocess.run(['bash',str(ROOT/'scripts/backup.sh')],env=env,text=True,capture_output=True)


def test_complete_encrypted_backup_and_authenticated_contents(install):
    app,dest,env=install;result=run(env);assert result.returncode==0,result.stderr
    saved=list(dest.glob('*.vpb'));assert len(saved)==1
    assert saved[0].stat().st_mode & 0o777==0o600
    assert 'shop-test-secret' not in result.stdout+result.stderr
    plain=io.BytesIO();bundle.decrypt(io.BytesIO(saved[0].read_bytes()),plain,SECRET)
    with tarfile.open(fileobj=io.BytesIO(plain.getvalue())) as archive:
        names={n.removeprefix('./') for n in archive.getnames()}
        assert {'shop.dump','support.dump','media.tar.gz','app-packages.tar.gz','support-uploads.tar.gz','environment.tar.gz','backup-manifest.json'}<=names
        manifest=json.load(archive.extractfile('./backup-manifest.json'))
        assert manifest['source_version']=='21.0.1'
        assert set(manifest['files'])=={'shop.dump','support.dump','media.tar.gz','app-packages.tar.gz','support-uploads.tar.gz','environment.tar.gz'}
        with tarfile.open(fileobj=archive.extractfile('./environment.tar.gz'),mode='r:gz') as secrets:
            assert secrets.extractfile('.env').read()==b'APP_SECRET=shop-test-secret\n'
    commands=Path(env['COMMAND_LOG']).read_text()
    assert commands.index('stop backend')<commands.index('pg_dump')<commands.index('start backend')<commands.index('backup_bundle.py encrypt')


@pytest.mark.parametrize('failure',['dump','files','encrypt'])
def test_failure_resumes_original_services_and_removes_partial_backup(install,failure):
    app,dest,env=install;env['FAIL_BACKUP']=failure;result=run(env)
    assert result.returncode!=0
    assert 'start backend worker bot support_pro support_worker' in Path(env['COMMAND_LOG']).read_text()
    assert not list(dest.glob('*.vpb'))
    assert (app/'.env').read_text()=='APP_SECRET=shop-test-secret\n'
