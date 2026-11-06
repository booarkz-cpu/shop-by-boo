from main_source import main_source
import ast
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
MAIN = main_source()
BOT = (ROOT / "backend/app/bot.py").read_text()
class V15ProductionTests(unittest.TestCase):
    def test_no_known_runtime_bugs(self):
        self.assertNotIn("LOGIN_BUCKET.setdefault(key", MAIN)
        self.assertNotIn("if payload.item_type==\"url\": validate_public_url(payload.action,allow_empty=False)\n    await db.delete(x)", MAIN)

    def test_python_sources_parse(self):
        for p in (ROOT / "backend/app").glob("*.py"):
            ast.parse(p.read_text())
    # test_security_contracts_v15 and test_promo_usage_is_reserved_then_consumed_safely: replaced by the behaviour tests
    # tests/test_behaviour_csrf.py and tests/test_behaviour_promo_consume.py (C1, stage 19).
    def test_broadcast_atomic(self):
        self.assertIn('FOR UPDATE SKIP LOCKED', BOT)
    def test_https_urls(self):
        self.assertIn('Only absolute HTTPS URLs are allowed', MAIN); self.assertIn('parsed.scheme != "https"', MAIN)
    def test_mfa_recovery_and_payment_verification(self):
        # Recovery codes: behaviour in tests/test_behaviour_mfa_recovery.py (C1, stage 19).
        self.assertIn("with_for_update()", MAIN)
        # Payment verification: behaviour in tests/test_behaviour_payments_yookassa.py and test_v44_5_18 (verify_succeeded).
    def test_frontends_cookie_auth(self):
        for p in (ROOT / "admin/src/main.tsx", ROOT / "cabinet/src/main.tsx"):
            s=p.read_text(); self.assertNotIn('localStorage.setItem("user_token"',s); self.assertNotIn('localStorage.setItem("rw_admin_token"',s); self.assertIn('credentials:"include"',s)
if __name__=='__main__': unittest.main()
