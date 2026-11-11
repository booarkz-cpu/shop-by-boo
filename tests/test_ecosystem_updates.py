"""«Обновления → Вся экосистема»: one honest table — what updates itself from GitHub, what is switched off, what cannot."""
from datetime import datetime, timezone

from app import ecosystem_updates as eco

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
TAG = "v28.118.0"


def release(*extra):
    names = ["corgi-lusi-client.apk", "corgi-lusi-client.json", "corgi_lusi_android_user_3_5_0_release.apk",
             "corgi_lusi_android_admin_3_5_0_release.apk", "corgi_lusi_ios_user_3_5_0_unsigned.ipa",
             "corgi_lusi_ios_admin_3_5_0_unsigned.ipa", *extra]
    return {"tag_name": TAG, "assets": [{"name": n} for n in names]}


def shop(enabled=True, alive=True, **status):
    return {"available": alive, "agent_alive": alive, "setup_hint": None if alive else "sudo bash … install",
            "status": {"enabled": enabled, "time": "03:00", "installed": "v28.117.0", "latest": TAG, **status}}


def github(update=True):
    return {"current_tag": "v28.117.0", "latest": "28.118.0", "update_available": update}


def remnawave(enabled=True, geo=False, installs=None, ids=(), newer=False):
    comp = lambda v: {"latest": "2.8.0" if newer else v, "newer": newer}  # noqa: E731
    return {"settings": {"enabled": enabled, "time": "04:30", "installation_ids": list(ids), "geo": geo},
            "verified": {"panel": "2.7.4", "node": "2.7.4", "subscription_page": "7.1.0"},
            "upstream": {"components": {"panel": comp("2.7.4"), "node": comp("2.7.4"), "subscription_page": comp("7.1.0")}},
            "installations": installs if installs is not None else [
                {"id": 1, "components": ["panel", "subscription_page"], "outdated": []},
                {"id": 2, "components": ["node"], "outdated": ["node"]}]}


def rows(result):
    return {r["key"]: r for r in result["components"]}


def test_everything_switched_on():
    result = eco.build(shop(), github(), remnawave(geo=True), release(), now=NOW)
    r = rows(result)
    assert list(r) == ["shop", "remnawave_panel", "remnawave_node", "remnawave_subscription_page", "geo", "android_client",
                       "android_user", "android_admin", "ios_user", "ios_admin"]
    assert (r["shop"]["installed"], r["shop"]["latest"], r["shop"]["state"], r["shop"]["auto"]) == ("v28.117.0", TAG, "update", "on")
    assert "03:00" in r["shop"]["schedule"]
    assert (r["remnawave_panel"]["state"], r["remnawave_panel"]["auto"]) == ("current", "on")
    assert (r["remnawave_node"]["state"], r["remnawave_node"]["note"]) == ("update", "Отстаёт установок: 1 из 1")
    assert r["geo"]["auto"] == "on" and "04:30" in r["geo"]["schedule"]
    assert r["android_client"]["auto"] == "in_app" and r["android_client"]["latest"] == f"выпуск {TAG}"
    assert result["checked_at"] == "2026-11-11T12:00:00+00:00"
    assert result["summary"] == {"total": 10, "automatic": 6, "switched_off": 0, "no_mechanism": 4, "updates_waiting": 2}


def test_no_promise_where_there_is_no_mechanism():
    r = rows(eco.build(shop(), github(False), remnawave(), release(), now=NOW))
    # The shop and admin apps for Android do not look for a new version: the table says so instead of «автоматически».
    for key in ("android_user", "android_admin"):
        assert r[key]["auto"] == "none" and r[key]["latest"] == "3.5.0" and "вручную" in r[key]["how"]
    for key in ("ios_user", "ios_admin"):
        assert r[key]["auto"] == "none" and "Apple Developer" in r[key]["note"]
    assert eco.SELF_CHECKING_APPS == {"android_client"}


def test_agent_not_installed_and_switched_off():
    r = rows(eco.build(shop(alive=False), github(), remnawave(enabled=False), release(), now=NOW))
    assert r["shop"]["auto"] == "not_installed" and r["shop"]["schedule"] is None and "install" in r["shop"]["note"]
    assert r["remnawave_panel"]["auto"] == "off" and r["remnawave_panel"]["schedule"] is None
    assert r["geo"]["auto"] == "off" and "Гео-списки" in r["geo"]["note"]
    off = rows(eco.build(shop(enabled=False), github(False), remnawave(), release(), now=NOW))["shop"]
    assert (off["auto"], off["state"]) == ("off", "current")


def test_failed_update_waits_for_the_administrator():
    r = rows(eco.build(shop(recovery_mode=True, last_result="failed"), github(), remnawave(), release(), now=NOW))
    assert r["shop"]["last_result"] == "failed" and "ждёт проверки" in r["shop"]["note"]


def test_remnawave_not_installed_by_the_shop_and_partial_choice():
    r = rows(eco.build(shop(), github(), remnawave(installs=[]), release(), now=NOW))
    assert r["remnawave_panel"]["state"] == "not_installed" and r["remnawave_panel"]["auto"] == "none"
    # Auto-update covers installation 1 only: the node of installation 2 is not updated at night.
    r = rows(eco.build(shop(), github(), remnawave(ids=[1]), release(), now=NOW))
    assert r["remnawave_panel"]["auto"] == "on" and r["remnawave_node"]["auto"] == "off"


def test_newer_upstream_release_is_explained_not_installed():
    r = rows(eco.build(shop(), github(), remnawave(newer=True), release(), now=NOW))
    assert r["remnawave_panel"]["installed"] == "2.7.4" and r["remnawave_panel"]["latest"] == "2.8.0"
    assert "выпуск магазина проверит" in r["remnawave_panel"]["note"]


def test_github_unreachable_gives_unknown_not_current():
    result = eco.build(shop(latest=None), {"current_tag": "v28.117.0"}, remnawave(), None, "GitHub не ответил", now=NOW)
    r = rows(result)
    assert r["shop"]["state"] == "unknown" and r["shop"]["note"] == "GitHub не ответил" and r["shop"]["installed"] == "v28.117.0"
    assert r["android_user"]["latest"] is None and "файла приложения нет" in r["android_user"]["note"]


def test_app_versions_come_from_file_names_only():
    assert eco.app_versions(release("something_else_9_9_9.apk", "corgi_lusi_android_user_x.apk")) == {
        "android_client": "в выпуске", "android_user": "3.5.0", "android_admin": "3.5.0", "ios_user": "3.5.0", "ios_admin": "3.5.0"}
    assert eco.app_versions({"assets": [{"name": "corgi-lusi-client.apk"}]}) == {}  # the manifest is missing: no claim
    assert eco.app_versions(None) == {}
