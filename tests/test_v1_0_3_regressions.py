from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=(ROOT/'release-manifest.template.json').read_text()


def test_release_is_v1_0_3_realise():
    assert '"version": "2.0.0-realise"' in MANIFEST


@pytest.mark.asyncio
async def test_lock_renewal_task_self_cleans_registry(monkeypatch):
    import asyncio

    from app import main as shop

    class Lost:
        async def eval(self, *a):
            return 0  # the lease belongs to someone else now
    monkeypatch.setattr(shop, "redis_client", Lost())
    real_sleep = asyncio.sleep

    async def fast(seconds):
        await real_sleep(0)
    monkeypatch.setattr(shop.asyncio, "sleep", fast)
    task = asyncio.create_task(shop._renew_redis_lock("lock:x", "tok-1", 3))
    shop._LOCK_RENEW_TASKS["tok-1"] = task
    await asyncio.wait_for(task, 1)
    assert "tok-1" not in shop._LOCK_RENEW_TASKS, "a renewal that lost its lease removes itself"
