from pathlib import Path

import pytest
ROOT=Path(__file__).parents[1]

def test_v37_version_and_release_metadata():
    build=(ROOT/'scripts/build-release.sh').read_text()
    assert 'remnawave_vpn_shop_v39_production.zip' in build

@pytest.mark.asyncio
async def test_remnawave_uses_shared_http_pool_and_explicit_shutdown(monkeypatch):
    from app.remnawave import RemnawaveClient
    monkeypatch.setattr(RemnawaveClient, "_shared_client", None)
    first = await RemnawaveClient._get_shared_client()
    assert await RemnawaveClient._get_shared_client() is first, "one pool for every request"
    assert first._transport._pool._max_keepalive_connections == 20
    await RemnawaveClient.close_shared_client()
    assert first.is_closed
    assert (await RemnawaveClient._get_shared_client()) is not first, "a closed pool is replaced"
    await RemnawaveClient.close_shared_client()

def test_no_current_stale_v30_labels():
    for rel in ['PRODUCTION_CHECKLIST.md','docs_API.md','deploy/install-vps.sh']:
        text=(ROOT/rel).read_text()
        assert 'V30 Production Checklist' not in text
        assert '## V30 API' not in text
        assert 'Firewall V32:' not in text
