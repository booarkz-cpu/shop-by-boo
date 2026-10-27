from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = main_source()


def section(start_marker, end_marker):
    start = MAIN.index(start_marker)
    end = MAIN.index(end_marker, start)
    return MAIN[start:end]


def test_admin_login_rate_limit_uses_real_client_ip_behind_proxy():
    s = section('@app.post("/api/admin/auth/login")', '@app.post("/api/admin/auth/mfa/setup")')
    assert 'client_ip=_client_ip(request)' in s
    assert 'client_ip=request.client.host' not in s


def test_refund_reconciler_revokes_and_claws_back_referral_reward():
    s = section('async def refund_revoke_scheduler():', 'async def auto_renew_scheduler():')
    assert '_safe_revoke_for_refunded_payment' in s
    assert '_reverse_referral_reward_for_refund' in s


def test_refund_paths_reverse_referral_reward_once():
    # The reversal happens once per reward: test_referral_program.py («full refund reverses all levels once»).
    execute = section('@app.post("/api/admin/refunds/{refund_id}/execute")', '@app.post("/api/admin/refunds/{refund_id}/retry-revoke")')
    reconcile = section('@app.post("/api/admin/refunds/{refund_id}/reconcile")', '@app.get("/api/admin/v41/referrals")')
    assert '_reverse_referral_reward_for_refund(edb,pp,admin.email)' in execute
    assert '_reverse_referral_reward_for_refund(db,p,admin.email)' in reconcile


# v28.30.0: remote-user recovery is tested by behaviour in tests/test_money_review.py (test_a_purchase_found_by_username_adds_all_paid_days).
