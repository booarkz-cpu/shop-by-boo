from main_source import main_source
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MAIN=main_source()
MODELS=(ROOT/'backend/app/models.py').read_text()
SEC=(ROOT/'backend/app/security.py').read_text()
MAN=(ROOT/'release-manifest.template.json').read_text()
# Menu labels live in the section map since v28.10.0.
ADMIN=(ROOT/'admin/src/main.tsx').read_text()+(ROOT/'admin/src/passkeys.tsx').read_text()+(ROOT/'admin/src/sections.ts').read_text()


def test_v41_feature_pack_contract():
    import app.models as models
    from app.security import PERMISSIONS
    from app_contract import missing_paths
    for name in ['FeatureFlag','PaymentProviderHealth','SecurityIncidentEvent','BackupVerification','WebAuthnCredential']:
        assert hasattr(models, name), name
    assert not missing_paths('/api/admin/v41/analytics','/api/admin/v41/diagnostics','/api/admin/v41/incidents','/api/admin/v41/providers',
                             '/api/admin/v41/crm/users','/api/admin/v41/features','/api/admin/v41/passkeys')
    assert '0021_v43_hardening_docs' in MAN
    assert '43.1.0-production' in MAN
    assert 'feature_flags.manage' in PERMISSIONS['admin']
    for label in ['Операции','Аналитика','Инциденты','Провайдеры','Клиенты','Функции','Ключи доступа']:
        assert label in ADMIN
