"""Stage 19, C1: two-factor recovery codes by behaviour (was: the words «recovery_codes_encrypted»,
«generate_recovery_codes», «manage_own_mfa» in the source — test_v15_production.test_mfa_recovery_and_payment_verification)."""
from app import security
from app.models import AdminUser


def test_codes_are_random_stored_encrypted_and_work_once():
    codes = security.generate_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 10 and c == c.upper() for c in codes)
    admin = AdminUser(email="a@corgi.test", password_hash="x", role="admin")
    security.set_recovery_codes(admin, codes)
    assert all(code not in admin.recovery_codes_encrypted for code in codes), "never stored in clear text"
    assert security.consume_recovery_code(admin, " " + codes[3].lower() + " ") is True   # typed loosely
    assert security.consume_recovery_code(admin, codes[3]) is False, "a code works once"
    assert security.consume_recovery_code(admin, "0000000000") is False
    assert all(security.consume_recovery_code(admin, c) for c in codes if c != codes[3])
    assert security.consume_recovery_code(admin, codes[0]) is False
    assert security.consume_recovery_code(AdminUser(email="b@corgi.test", password_hash="x", role="admin"), codes[1]) is False


def test_damaged_storage_never_lets_anyone_in():
    admin = AdminUser(email="a@corgi.test", password_hash="x", role="admin", recovery_codes_encrypted="not-encrypted-data")
    assert security.consume_recovery_code(admin, "ABCDEF1234") is False


def test_every_role_can_manage_its_own_two_factor():
    for role, perms in security.PERMISSIONS.items():
        assert "manage_own_mfa" in perms or "*" in perms, role
