"""«Обновления» → «Вся экосистема»: one table of everything the shop consists of and how each part is updated from GitHub.

The page changes nothing: it reads what the existing mechanisms already know and says honestly where there is no
automatic update at all.

* the shop itself (bot, Mini App, cabinet, admin panel, Support Pro — one release) — the host agent, ``auto_update_api``;
* Remnawave: panel, node, subscription page, geo lists — ``rw_autoupdate``;
* the Android apps — the files of the latest shop release on GitHub; the app checks them itself;
* iOS — no automatic update: it needs a signed build in App Store or TestFlight.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/ecosystem-updates")
APP_ASSET = re.compile(r"^corgi_lusi_(android|ios)_(user|admin)_(\d+)_(\d+)_(\d+)_")
RW_TITLES = {"panel": "Панель Remnawave", "node": "Ноды Remnawave", "subscription_page": "Страница подписки Remnawave"}
# Apps that look for a new version on GitHub themselves. Kept here so that the table cannot promise more than the code does.
SELF_CHECKING_APPS = {"android_client"}

__all__ = ["router", "build", "app_versions"]


def app_versions(release: dict | None) -> dict:
    """Versions of the mobile apps in a GitHub release, read from the names of its files."""
    found: dict[str, str] = {}
    names = {str(a.get("name") or "") for a in (release or {}).get("assets") or []}
    for name in names:
        match = APP_ASSET.match(name)
        if match:
            found[f"{match[1]}_{match[2]}"] = ".".join(match.group(3, 4, 5))
    if "corgi-lusi-client.apk" in names and "corgi-lusi-client.json" in names:
        found["android_client"] = "в выпуске"
    return found


def _row(key: str, title: str, **fields) -> dict:
    row = {"key": key, "title": title, "installed": None, "latest": None, "state": "unknown", "auto": "none", "schedule": None,
           "last_result": None, "how": "", "tab": None, "note": None}
    row.update(fields)
    return row


def _shop(shop: dict, github: dict | None, github_error: str | None) -> dict:
    status = shop.get("status") or {}
    alive = bool(shop.get("available") and shop.get("agent_alive"))
    enabled = bool(status.get("enabled")) and alive
    update = bool((github or {}).get("update_available"))
    note = None
    if not alive:
        note = shop.get("setup_hint") or "Агент автообновления не установлен"
    elif status.get("recovery_mode"):
        note = "Последнее обновление не удалось: автообновление ждёт проверки администратора"
    elif github_error:
        note = github_error
    return _row("shop", "Магазин: бот, Mini App, кабинет, панель администратора, Support Pro",
                installed=(github or {}).get("current_tag") or status.get("installed"),
                latest=(f"v{github['latest']}" if (github or {}).get("latest") else status.get("latest")),
                state="unknown" if github_error or (github is None and not status.get("latest")) else ("update" if update else "current"),
                auto="on" if enabled else ("off" if alive else "not_installed"),
                schedule=f"каждую ночь в {status['time']} по времени сервера" if enabled and status.get("time") else None,
                last_result=status.get("last_result"), tab="releases", note=note,
                how="Агент на сервере проверяет выпуск на GitHub, сверяет SHA-256 и манифест, делает снимок и копию базы, "
                    "обновляет и при сбое откатывает.")


def _remnawave(rw: dict) -> list[dict]:
    settings = rw.get("settings") or {}
    enabled = bool(settings.get("enabled"))
    chosen = set(settings.get("installation_ids") or [])
    installs = rw.get("installations") or []
    covered = [i for i in installs if not chosen or i["id"] in chosen]
    components = (rw.get("upstream") or {}).get("components") or {}
    rows = []
    for key, title in RW_TITLES.items():
        info = components.get(key) or {}
        mine = [i for i in installs if key in (i.get("components") or [])]
        stale = [i for i in mine if key in (i.get("outdated") or [])]
        if not mine:
            state, note = "not_installed", "Магазин этот компонент не устанавливал: обновлять нечего"
        elif stale:
            state, note = "update", f"Отстаёт установок: {len(stale)} из {len(mine)}"
        else:
            state, note = "current", None
        if info.get("newer"):
            note = ((note + ". ") if note else "") + (f"На GitHub уже {info.get('latest')}: магазин поставит её после того, "
                                                     "как выпуск магазина проверит эту версию")
        on = enabled and any(i in covered for i in mine)
        rows.append(_row(f"remnawave_{key}", title, installed=(rw.get("verified") or {}).get(key), latest=info.get("latest"),
                         state=state, auto="on" if on else ("off" if mine else "none"),
                         schedule=f"каждую ночь в {settings.get('time')} МСК" if on else None, tab="releases", note=note,
                         how="Ставятся только версии, которые выпуск магазина проверил на настоящей панели и ноде; "
                             "перед обновлением — копия базы панели, при сбое — откат."))
    geo = bool(settings.get("geo")) and enabled
    rows.append(_row("geo", "Гео-списки для маршрутизации на нодах", state="unknown", auto="on" if geo else "off",
                     schedule=f"каждую ночь в {settings.get('time')} МСК" if geo else None, tab="releases",
                     note=None if geo else "Включается галочкой «Гео-списки» в автообновлении Remnawave",
                     how="Свежая сборка списков с проверкой SHA-256 — только на нодах, где модуль гео-списков установлен."))
    return rows


def _apps(versions: dict, tag: str | None) -> list[dict]:
    where = f"выпуск {tag}" if tag else None
    rows = []
    for key, title in (("android_client", "«Корги Люси: клиент» для Android"), ("android_user", "Приложение магазина для Android"),
                       ("android_admin", "Приложение администратора для Android")):
        present = key in versions
        checks = key in SELF_CHECKING_APPS
        rows.append(_row(key, title, latest=(versions.get(key) if versions.get(key) != "в выпуске" else where) if present else None,
                         state="unknown", auto="in_app" if checks else "none",
                         schedule="проверка раз в сутки на устройстве, если включена в настройках приложения" if checks else None,
                         how="Приложение само находит новый APK в выпуске на GitHub, сверяет SHA-256 и предлагает установить. "
                             "Подпись проверяет Android." if checks else
                             "APK лежит в каждом выпуске на GitHub. Приложение новую версию само не ищет: её ставят вручную.",
                         note=None if present else "В последнем выпуске на GitHub файла приложения нет"))
    for key, title in (("ios_user", "Приложение магазина для iOS"), ("ios_admin", "Приложение администратора для iOS")):
        rows.append(_row(key, title, latest=versions.get(key), state="unknown", auto="none",
                         how="В выпуске лежит неподписанная сборка. Автоматического обновления нет.",
                         note="Нужен аккаунт Apple Developer: обновления на iOS идут только через App Store или TestFlight"))
    return rows


def build(shop: dict, github: dict | None, rw: dict, release: dict | None, github_error: str | None = None,
          now: datetime | None = None) -> dict:
    rows = [_shop(shop, github, github_error), *_remnawave(rw), *_apps(app_versions(release), (release or {}).get("tag_name"))]
    return {"checked_at": (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat(), "components": rows,
            "summary": {"total": len(rows), "automatic": sum(r["auto"] in ("on", "in_app") for r in rows),
                        "switched_off": sum(r["auto"] in ("off", "not_installed") for r in rows),
                        "no_mechanism": sum(r["auto"] == "none" for r in rows),
                        "updates_waiting": sum(r["state"] == "update" for r in rows)}}


async def fetch_release() -> dict:
    """Seam for tests."""
    from .github_update import fetch_latest_release
    return await fetch_latest_release()


@router.get("")
async def get_ecosystem(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.releases"))):
    from . import auto_update_api, rw_autoupdate
    from .github_update import release_status
    from .main import APP_VERSION
    from .release_identity import DISTRIBUTION_TAG

    release, github, error = None, None, None
    try:
        release = await fetch_release()
        github = release_status(APP_VERSION, release, current_distribution=DISTRIBUTION_TAG)
    except Exception:  # noqa: BLE001 — the table is still useful without GitHub
        error = "GitHub не ответил: последние версии неизвестны"
        github = None
    if github is None:
        github_view = {"current_tag": DISTRIBUTION_TAG} if error else None
    else:
        github_view = github
    rw = await rw_autoupdate.overview(db, with_panel=False)
    return build(auto_update_api.read_state(), github_view, rw, release, error)
