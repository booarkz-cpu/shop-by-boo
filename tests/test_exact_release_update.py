"""Production deploy must honor a stable tag and refuse preview/draft assets."""
import hashlib
import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('release_fetch_exact',Path('scripts/github_release_fetch.py'))
updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)


def setup(monkeypatch,tmp_path,payload):
    install=tmp_path/'installed';(install/'services/backend/app').mkdir(parents=True)
    (install/'services/backend/app/main.py').write_text('APP_VERSION = "20.0.29"\n')
    monkeypatch.setattr(sys,'argv',['updater',str(install),str(tmp_path/'stage')])
    fetch=__import__('unittest.mock',fromlist=['Mock']).Mock(return_value=payload)
    monkeypatch.setattr(updater,'fetch_json',fetch)
    return fetch


def test_exact_tag_fetch_and_checksum(monkeypatch,tmp_path):
    tag='v21.0.0';name='remnawave_vpn_shop_v21_0_0_full_release.zip'
    blob=io.BytesIO()
    with zipfile.ZipFile(blob,'w') as archive:archive.writestr('services/backend/app/main.py','APP_VERSION = "21.0.0"\n')
    content=blob.getvalue();checksum=f'{hashlib.sha256(content).hexdigest()}  {name}\n'.encode()
    payload={'tag_name':tag,'draft':False,'prerelease':False,'assets':[{'name':n,'browser_download_url':f'{updater.DOWNLOAD_PREFIX}{tag}/{n}'} for n in (name,name+'.sha256')]}
    fetch=setup(monkeypatch,tmp_path,payload);monkeypatch.setenv('RELEASE_TAG',tag)
    monkeypatch.setattr(updater,'download',lambda url:checksum if url.endswith('.sha256') else content)
    updater.main()
    fetch.assert_called_once_with(f'https://api.github.com/repos/{updater.REPO}/releases/tags/{tag}')
    assert updater.current_version(tmp_path/'stage')=='21.0.0'


@pytest.mark.parametrize('flags',[{'draft':True},{'prerelease':True},{'tag_name':'v21.0.1'}])
def test_draft_preview_or_mismatched_response_refused(monkeypatch,tmp_path,flags):
    setup(monkeypatch,tmp_path,{'tag_name':'v21.0.0'}|flags)
    monkeypatch.setenv('RELEASE_TAG','v21.0.0')
    with pytest.raises(SystemExit):updater.main()
    assert not (tmp_path/'stage').exists()


@pytest.mark.parametrize('tag',['main','v21.0.0-alpha.6','v21.0.0; touch /tmp/x','../latest'])
def test_invalid_tag_never_contacts_github(monkeypatch,tmp_path,tag):
    fetch=setup(monkeypatch,tmp_path,{})
    monkeypatch.setenv('RELEASE_TAG',tag)
    with pytest.raises(SystemExit):updater.main()
    fetch.assert_not_called()
