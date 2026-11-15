import importlib.util
from pathlib import Path
import pytest
p=Path(__file__).resolve().parents[1]/'scripts/configure-support-bridge.py'
spec=importlib.util.spec_from_file_location('bridge_config',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_pair_config_preserves_settings_and_key_on_repeat(tmp_path):
    (tmp_path/'support-pro').mkdir();(tmp_path/'.env').write_text('APP_SECRET=existing\n# keep me\n')
    (tmp_path/'support-pro/.env').write_text('SESSION_SECRET=existing-support\n')
    module.configure(tmp_path,'https://api.example.com','support-main',True)
    assert 'SUPPORT_BRIDGE_TOKEN' not in (tmp_path/'.env').read_text()
    module.configure(tmp_path,'https://api.example.com','support-main')
    a=module.read_values(tmp_path/'.env');b=module.read_values(tmp_path/'support-pro/.env')
    assert a['SUPPORT_BRIDGE_TOKEN']==b['SHOP_BRIDGE_TOKEN'] and len(a['SUPPORT_BRIDGE_TOKEN'])==64
    assert a['APP_SECRET']=='existing' and b['SESSION_SECRET']=='existing-support'
    module.configure(tmp_path,'https://api.example.com','support-main')
    assert module.read_values(tmp_path/'.env')['SUPPORT_BRIDGE_TOKEN']==a['SUPPORT_BRIDGE_TOKEN']
    assert (tmp_path/'.env').stat().st_mode&0o777==0o600
    with pytest.raises(ValueError):module.configure(tmp_path,'https://other.example.com','support-main')
    with pytest.raises(ValueError):module.configure(tmp_path,'https://api.example.com','another-instance')
    assert module.read_values(tmp_path/'.env')==a
