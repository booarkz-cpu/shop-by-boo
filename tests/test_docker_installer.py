"""Installer control flow with an isolated apt/keyring and fake package tools."""
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

ROOT=Path(__file__).resolve().parents[1]


def run(tmp_path,mode='new',codename='noble'):
    etc=tmp_path/'etc';(etc/'apt/sources.list.d').mkdir(parents=True)
    (etc/'os-release').write_text(f'ID=ubuntu\nVERSION_CODENAME="{codename}"\n')
    binary=tmp_path/'bin';binary.mkdir()
    for command in ('bash','install','grep','mktemp','rm','cat'):
        (binary/command).symlink_to(shutil.which(command))
    log=tmp_path/'commands.jsonl'
    stub=f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name;args=sys.argv[1:]
with Path(os.environ['TEST_LOG']).open('a') as f:f.write(json.dumps([name,*args])+'\\n')
if name=='dpkg':print('amd64')
if name=='curl':
    if os.environ['TEST_MODE']=='download_failed':sys.exit(22)
    Path(args[args.index('-o')+1]).write_text('-----BEGIN PGP PUBLIC KEY BLOCK-----\\nfixture\\n')
if name=='apt-get' and 'docker-ce' in args:
    p=Path(os.environ['TEST_BIN'])/'docker';p.write_text('#!/bin/sh\\nexit 0\\n');p.chmod(0o755)
'''
    for tool in ('apt-get','curl','systemctl','dpkg'):
        p=binary/tool;p.write_text(stub);p.chmod(0o755)
    if mode.startswith('existing'):
        p=binary/'docker'
        p.write_text('#!/bin/sh\nexit '+('1' if mode=='existing_without_compose' else '0')+'\n');p.chmod(0o755)
    script=tmp_path/'installer.sh'
    # Exercise the same package flow without requiring root or writing host /etc.
    script.write_text((ROOT/'infrastructure/deployment/install-docker.sh').read_text().replace('[[ $EUID -eq 0 ]]','true').replace('/etc',str(etc)))
    result=subprocess.run(['bash',str(script)],env={**os.environ,'PATH':str(binary),
        'TEST_LOG':str(log),'TEST_BIN':str(binary),'TEST_MODE':mode},capture_output=True,text=True)
    calls=[json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
    return result,calls,etc


def test_fresh_signed_apt_installation(tmp_path):
    result,calls,etc=run(tmp_path)
    assert result.returncode==0,result.stderr
    source=(etc/'apt/sources.list.d/docker.sources').read_text()
    assert 'https://download.docker.com/linux/ubuntu' in source and 'Suites: noble' in source and 'Signed-By:' in source
    assert any(c[0]=='apt-get' and 'docker-compose-plugin' in c for c in calls)
    assert not any('get.docker.com' in str(c) for c in calls)
    assert (etc/'apt/keyrings/docker.asc').stat().st_mode&0o777==0o644


def test_existing_engine_is_reused(tmp_path):
    result,calls,etc=run(tmp_path,'existing')
    assert result.returncode==0
    assert not any(c[0] in {'apt-get','curl'} for c in calls)


@pytest.mark.parametrize('mode,codename',[('download_failed','noble'),('new','noble bad')])
def test_failed_key_or_invalid_codename_never_installs_engine(tmp_path,mode,codename):
    result,calls,etc=run(tmp_path,mode,codename)
    assert result.returncode!=0
    assert not any('docker-ce' in c for c in calls)
    assert not (etc/'apt/sources.list.d/docker.sources').exists()


def test_existing_engine_without_compose_is_not_replaced(tmp_path):
    result,calls,etc=run(tmp_path,'existing_without_compose')
    assert result.returncode!=0 and 'will not replace a live engine' in result.stderr
    assert not any(c[0] in {'apt-get','curl'} for c in calls)
