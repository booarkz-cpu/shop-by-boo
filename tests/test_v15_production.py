import ast
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
BOT = (ROOT / "backend/app/bot.py").read_text()
class V15ProductionTests(unittest.TestCase):
    # The old in-memory login bucket is no longer filled anywhere (sign-in limits live in runtime_security);
    # the menu delete takes no body: tests/test_v16_v19_release.py.

    def test_python_sources_parse(self):
        for p in (ROOT / "backend/app").glob("*.py"):
            ast.parse(p.read_text())
    # test_security_contracts_v15 and test_promo_usage_is_reserved_then_consumed_safely: replaced by the behaviour tests
    # tests/test_behaviour_csrf.py and tests/test_behaviour_promo_consume.py (C1, stage 19).
    def test_broadcast_atomic(self):
        self.assertIn('FOR UPDATE SKIP LOCKED', BOT)
    def test_https_urls(self):
        from fastapi import HTTPException
        from app.content_branding_api import validate_public_url
        for bad in ("http://example.com/a", "ftp://example.com", "https://user:pw@example.com", "javascript:alert(1)", "https://localhost/"):
            with self.assertRaises(HTTPException, msg=bad):
                validate_public_url(bad)
        with self.assertRaises(HTTPException) as err:
            validate_public_url("http://example.com")
        self.assertEqual(err.exception.detail, "Only absolute HTTPS URLs are allowed")
    # Recovery codes: behaviour in tests/test_behaviour_mfa_recovery.py (C1, stage 19).
    # Payment verification: behaviour in tests/test_behaviour_payments_yookassa.py and test_v44_5_18 (verify_succeeded).
    def test_frontends_cookie_auth(self):
        for p in (ROOT / "apps/lucy-admin/web/src/main.tsx", ROOT / "apps/user-cabinet/src/main.tsx"):
            s=p.read_text(); self.assertNotIn('localStorage.setItem("user_token"',s); self.assertNotIn('localStorage.setItem("rw_admin_token"',s); self.assertIn('credentials:"include"',s)
if __name__=='__main__': unittest.main()
