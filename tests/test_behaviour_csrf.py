"""Stage 19, C1: the CSRF guard of cookie sessions and the client address behind the proxy, checked by running them.

Replaces test_v15_production.test_security_contracts_v15, which looked for the strings ``X-CSRF-Token``,
``rw_user``/``rw_admin`` and ``Webhook IP not allowed`` in the source. The exchange code runs in
test_behaviour_auth.test_exchange_code_is_single_use_and_short_lived; the webhook allowlist in
test_behaviour_payment_guards.test_a_notification_from_outside_the_allowlist_is_refused."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app import main as shop


def request(method="POST", path="/api/me/profile", cookies=None, headers=None, peer="198.51.100.7"):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": raw, "client": (peer, 50000), "query_string": b""})


@pytest.mark.parametrize("session", ["rw_user", "rw_admin"])
def test_a_cookie_session_needs_the_matching_header(session):
    cookies = {session: "token", "rw_csrf": "csrf-value"}
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(HTTPException) as err:
            shop._require_csrf(request(method, cookies=cookies))
        assert err.value.status_code == 403
        with pytest.raises(HTTPException):
            shop._require_csrf(request(method, cookies=cookies, headers={"X-CSRF-Token": "other"}))
        shop._require_csrf(request(method, cookies=cookies, headers={"X-CSRF-Token": "csrf-value"}))
    # Without the CSRF cookie even an empty header matches nothing.
    with pytest.raises(HTTPException):
        shop._require_csrf(request(cookies={session: "token"}, headers={"X-CSRF-Token": ""}))


def test_reads_sign_ins_webhooks_and_bearer_calls_pass():
    cookies = {"rw_user": "token", "rw_csrf": "csrf-value"}
    shop._require_csrf(request("GET", cookies=cookies))
    shop._require_csrf(request("HEAD", cookies=cookies))
    for path in ("/api/auth/telegram", "/api/auth/exchange", "/api/admin/auth/login", "/api/webhooks/yookassa"):
        shop._require_csrf(request(path=path, cookies=cookies))
    shop._require_csrf(request(headers={"Authorization": "Bearer abc"}))  # an app with a bearer token has no cookie to ride on


def test_sign_in_sets_a_readable_csrf_cookie():
    response = Response()
    csrf = shop._set_auth_cookies(response, "session-token")
    header = response.headers["set-cookie"]
    assert header.startswith(f"rw_csrf={csrf};") and "HttpOnly" not in header, "the page has to read it to send it back"
    assert csrf != shop._set_auth_cookies(Response(), "session-token"), "a new value on every sign-in"


def test_forwarded_address_is_trusted_only_from_the_proxy(monkeypatch):
    monkeypatch.setattr(shop.settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    spoofed = {"X-Forwarded-For": "203.0.113.5"}
    assert shop._client_ip(request(headers=spoofed, peer="198.51.100.7")) == "198.51.100.7", "a client cannot pick its own address"
    assert shop._client_ip(request(headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.2"}, peer="10.0.0.2")) == "203.0.113.5"
    assert shop._client_ip(request(headers={"X-Forwarded-For": "not-an-ip"}, peer="10.0.0.2")) == "10.0.0.2"
