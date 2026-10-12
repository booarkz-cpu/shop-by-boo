"""A successful verified login resets its attempts without disabling rate limits."""
import pytest
from app import runtime_security as security


@pytest.fixture(autouse=True)
def isolated_counters():
    security._LOCAL.clear()
    yield
    security._LOCAL.clear()


@pytest.mark.asyncio
async def test_verified_login_resets_local_attempts_only_for_itself():
    key = "login:127.0.0.1:admin@example.test"
    other = "login:127.0.0.1:other@example.test"
    for _ in range(8):
        assert await security.rate_allowed(None, key, 8, 900)
        assert await security.rate_allowed(None, other, 8, 900)
    assert not await security.rate_allowed(None, key, 8, 900)
    await security.reset_login_attempts(None, key)
    assert await security.rate_allowed(None, key, 8, 900)
    assert not await security.rate_allowed(None, other, 8, 900)


@pytest.mark.asyncio
async def test_redis_failure_still_clears_local_login_attempts():
    class UnavailableRedis:
        async def delete(self, key):
            raise ConnectionError("Unavailable")
    key = "login:127.0.0.1:admin@example.test"
    for _ in range(9):
        security.local_rate_allowed(key, 8, 900)
    await security.reset_login_attempts(UnavailableRedis(), key)
    assert security.local_rate_allowed(key, 8, 900)


@pytest.mark.asyncio
async def test_general_request_limit_cannot_be_reset_by_login_helper():
    key = "rl:127.0.0.1:/api/admin/auth/login"
    assert security.local_rate_allowed(key, 1, 900)
    with pytest.raises(ValueError):
        await security.reset_login_attempts(None, key)
    assert not security.local_rate_allowed(key, 1, 900)
