"""System Control Center (v28.62.0, stage 6): one screen with the state of every part of the installation.

``GET /api/admin/health/summary`` (admin «Аналитика → Состояние системы») returns a list of checks. Each check
is read-only and typed: the browser never sends a command, a host name or a path. A check has

* ``key`` — a stable identifier (``backend``, ``frontend``, ``database``, ``migrations``, …);
* ``name`` — the title shown in the panel;
* ``status`` — ``ok`` (works), ``warn`` (works, but needs attention), ``error`` (does not work) or ``off``
  (not configured; nothing is broken, the function is simply not used);
* ``detail`` — one sentence of what was found, ``error`` — the reason of a failure;
* ``tab`` — the admin section where the part is managed;
* ``latency_ms`` for network checks.

Every check has its own time limit and its own ``try``: one slow or broken part never hides the others.
Secrets, tokens and answers of remote services are never put into the response.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import BackupJob, Job, PaymentProviderHealth, WorkerState

logger = logging.getLogger(__name__)

NETWORK_TIMEOUT = 5.0
# The reverse proxy as the backend sees it in docker compose (service «caddy», port 443 inside the network).
CADDY_HOST = "caddy"
# The static frontends as docker compose names them; each serves its build on port 80 inside the network.
FRONTENDS = (("admin", "админка"), ("cabinet", "кабинет"), ("miniapp", "Mini App"))
CADDY_PORT = 443
CERT_WARN_DAYS = 14
BACKUP_WARN_HOURS = 26
WORKER_STALE_SECONDS = 90
QUEUE_STUCK_MINUTES = 15
UPDATE_CACHE_SECONDS = 3600
UPDATE_FAILURE_CACHE_SECONDS = 600
SUCCESS_BACKUP = ("completed", "done", "succeeded", "ok")

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_update_cache: dict = {"at": 0.0, "value": None}


def check(key: str, name: str, status: str, detail: str, tab: str, **extra) -> dict:
    row = {"key": key, "name": name, "status": status, "detail": detail, "tab": tab}
    row.update({k: v for k, v in extra.items() if v is not None})
    return row


def _ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def migration_head() -> str | None:
    """The newest migration shipped with this release (read from the alembic scripts next to the app)."""
    try:
        from alembic.script import ScriptDirectory
        heads = ScriptDirectory(str(_ALEMBIC_DIR)).get_heads()
    except Exception as exc:  # noqa: BLE001 — a missing alembic folder is reported, not raised
        logger.warning("Cannot read migration head: %s", exc)
        return None
    return heads[0] if len(heads) == 1 else None


def backend_check(version: str, distribution: str) -> dict:
    return check("backend", "Backend (API)", "ok", f"Отвечает. Выпуск {distribution}, API {version}.", "releases")


async def database_checks(db: AsyncSession) -> list[dict]:
    start = time.monotonic()
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Control center: PostgreSQL check failed: %s", exc)
        await db.rollback()
        return [check("database", "PostgreSQL", "error", "База данных не отвечает.", "operations", error="unavailable"),
                check("migrations", "Миграции базы", "error", "Нельзя проверить: база не отвечает.", "releases", error="unavailable")]
    rows = [check("database", "PostgreSQL", "ok", "Отвечает на запросы.", "operations", latency_ms=_ms(start))]
    expected = migration_head()
    try:
        current = await db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Control center: alembic_version read failed: %s", exc)
        await db.rollback()
        current = None
    if not current:
        rows.append(check("migrations", "Миграции базы", "error", "В базе нет отметки миграций: выполните обновление.", "releases"))
    elif expected and current != expected:
        rows.append(check("migrations", "Миграции базы", "error",
                          f"База на миграции {current}, выпуск ждёт {expected}: обновление не завершено.", "releases"))
    else:
        rows.append(check("migrations", "Миграции базы", "ok", f"База на актуальной миграции {current}.", "releases"))
    return rows


async def redis_check(client) -> dict:
    if client is None:
        return check("redis", "Redis", "error", "Подключение к Redis не создано: проверьте REDIS_URL.", "operations", error="not connected")
    start = time.monotonic()
    try:
        await asyncio.wait_for(client.ping(), NETWORK_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Control center: Redis check failed: %s", exc)
        return check("redis", "Redis", "error", "Redis не отвечает.", "operations", error="unavailable")
    return check("redis", "Redis", "ok", "Отвечает.", "operations", latency_ms=_ms(start))


async def frontend_page(service: str) -> int:
    """GET / of a frontend container; returns the HTTP status."""
    import httpx
    async with httpx.AsyncClient(timeout=NETWORK_TIMEOUT, follow_redirects=False, trust_env=False) as client:
        return (await client.get(f"http://{service}/")).status_code


async def frontend_check(probe=frontend_page) -> dict:
    start = time.monotonic()
    results = await asyncio.gather(*(probe(service) for service, _ in FRONTENDS), return_exceptions=True)
    down = []
    for (service, title), result in zip(FRONTENDS, results):
        if not (isinstance(result, int) and result < 400):
            logger.warning("Control center: frontend %s check failed: %s", service, result)
            down.append(title)
    if len(down) == len(FRONTENDS):
        return check("frontend", "Frontend", "error", "Не отвечает ни один интерфейс: " + ", ".join(down) + ".", "deployments", error="unavailable")
    if down:
        return check("frontend", "Frontend", "error", "Не отвечает: " + ", ".join(down) + ". Остальные интерфейсы работают.", "deployments")
    return check("frontend", "Frontend", "ok", "Отвечают админка, кабинет и Mini App.", "deployments", latency_ms=_ms(start))


def _nodes(payload) -> list[dict]:
    from .tariff_api import _iter_nodes, public_node
    return [public_node(x) for x in _iter_nodes(payload)]


async def remnawave_checks(client_factory) -> list[dict]:
    from .remnawave import RemnawaveNotConfigured
    start = time.monotonic()
    try:
        payload = await asyncio.wait_for(client_factory().list_nodes(start=0, size=500), NETWORK_TIMEOUT * 2)
    except RemnawaveNotConfigured:
        return [check("remnawave", "Remnawave", "off", "Панель не подключена: укажите адрес и токен в «Настройки без перезапуска» (REMNAWAVE_URL, REMNAWAVE_TOKEN).", "remnawave"),
                check("nodes", "Узлы", "off", "Нет данных: панель Remnawave не подключена.", "nodes")]
    except Exception as exc:  # noqa: BLE001 — the panel answer is logged, not shown
        logger.warning("Control center: Remnawave check failed: %s", exc)
        return [check("remnawave", "Remnawave", "error", "Панель не отвечает или отклонила токен.", "remnawave", error="unavailable"),
                check("nodes", "Узлы", "error", "Нет данных: панель Remnawave не отвечает.", "nodes", error="unavailable")]
    rows = [check("remnawave", "Remnawave", "ok", "Панель отвечает, токен принят.", "remnawave", latency_ms=_ms(start))]
    nodes = _nodes(payload)
    active = [n for n in nodes if n.get("status") != "disabled"]
    online = [n for n in active if n.get("status") == "online"]
    if not nodes:
        rows.append(check("nodes", "Узлы", "warn", "В панели нет ни одного узла: клиентам некуда подключаться.", "nodes"))
    elif not online:
        rows.append(check("nodes", "Узлы", "error", f"Ни один из {len(active)} включённых узлов не на связи.", "nodes"))
    elif len(online) < len(active):
        rows.append(check("nodes", "Узлы", "warn", f"На связи {len(online)} из {len(active)} включённых узлов.", "nodes"))
    else:
        rows.append(check("nodes", "Узлы", "ok", f"На связи все включённые узлы: {len(online)}.", "nodes"))
    return rows


def public_domains() -> list[str]:
    seen: list[str] = []
    for value in (settings.api_domain, settings.admin_domain, settings.cabinet_domain, settings.app_domain):
        domain = str(value or "").strip().lower()
        if domain and domain != "localhost" and "." in domain and domain not in seen:
            seen.append(domain)
    return seen


async def certificate_expiry(domain: str, host: str = CADDY_HOST, port: int = CADDY_PORT) -> datetime:
    """Open a TLS connection to the reverse proxy with the domain as SNI and return the certificate's end date.

    The certificate is verified against the system trust store, so an expired or self-signed certificate fails."""
    context = ssl.create_default_context()
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, ssl=context, server_hostname=domain), NETWORK_TIMEOUT)
    try:
        cert = writer.get_extra_info("peercert") or {}
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 1)
        except Exception as exc:  # noqa: BLE001 — closing an already finished TLS stream
            logger.debug("TLS close: %s", exc)
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc)


async def proxy_checks(probe=certificate_expiry) -> list[dict]:
    domains = public_domains()
    if not domains:
        return [check("caddy", "Caddy (обратный прокси)", "off", "Домены не заданы (localhost): прокси и сертификаты не проверяются.", "operations"),
                check("tls", "Сертификаты TLS", "off", "Домены не заданы: сертификатов нет.", "operations")]
    results = await asyncio.gather(*(probe(d) for d in domains), return_exceptions=True)
    now = datetime.now(timezone.utc)
    reachable = [(d, r) for d, r in zip(domains, results) if isinstance(r, datetime)]
    failed = [(d, r) for d, r in zip(domains, results) if not isinstance(r, datetime)]
    for domain, exc in failed:
        logger.warning("Control center: TLS check of %s failed: %s", domain, exc)
    refused = [d for d, r in failed if not isinstance(r, ssl.SSLError)]
    if len(refused) == len(domains):
        caddy = check("caddy", "Caddy (обратный прокси)", "error", f"Прокси не принимает соединения на {CADDY_HOST}:{CADDY_PORT}.", "operations", error="unavailable")
    else:
        caddy = check("caddy", "Caddy (обратный прокси)", "ok", f"Принимает HTTPS для доменов: {len(domains) - len(refused)} из {len(domains)}.", "operations")
    bad = [d for d, r in failed if isinstance(r, ssl.SSLError)]
    soon = [(d, (r - now).days) for d, r in reachable if r - now < timedelta(days=CERT_WARN_DAYS)]
    if bad:
        tls = check("tls", "Сертификаты TLS", "error", "Сертификат не проходит проверку: " + ", ".join(bad) + ".", "operations")
    elif refused:
        tls = check("tls", "Сертификаты TLS", "error", "Нельзя проверить: " + ", ".join(refused) + " не отвечает.", "operations")
    elif soon:
        tls = check("tls", "Сертификаты TLS", "warn", "Скоро истекает: " + ", ".join(f"{d} — {max(days, 0)} дн." for d, days in soon)
                    + ". Caddy продлевает сам; если срок не растёт — проверьте порт 80 и DNS.", "operations")
    else:
        nearest = min(r for _, r in reachable)
        tls = check("tls", "Сертификаты TLS", "ok", f"Действуют для {len(reachable)} доменов, ближайший срок — {nearest:%d.%m.%Y}.", "operations")
    return [caddy, tls]


async def payments_check(db: AsyncSession, paused: bool) -> dict:
    from .ops_alerts import _agent_configured
    from .payment_policy import PAYMENT_AGENTS
    configured = [p for p in PAYMENT_AGENTS if _agent_configured(p)]
    if not configured:
        return check("payments", "Платежи", "off" if settings.payments_sandbox else "error",
                     "Ни один платёжный агент не настроен: ключи вводятся в «Настройки без перезапуска»." + (" Включён тестовый режим." if settings.payments_sandbox else ""), "providers")
    now = datetime.utcnow()
    rows = (await db.execute(select(PaymentProviderHealth).where(PaymentProviderHealth.provider.in_(configured)))).scalars().all()
    tripped = sorted(r.provider for r in rows if r.circuit_open_until and r.circuit_open_until > now)
    disabled = sorted(r.provider for r in rows if not r.enabled)
    working = [p for p in configured if p not in tripped and p not in disabled]
    if paused:
        return check("payments", "Платежи", "warn", "Приём платежей приостановлен вручную или режимом инцидента.", "providers")
    if not working:
        return check("payments", "Платежи", "error", "Все настроенные агенты отключены или временно выведены из очереди: " + ", ".join(tripped + disabled) + ".", "providers")
    detail = "Принимаются через: " + ", ".join(working) + "."
    if tripped:
        return check("payments", "Платежи", "warn", detail + " Временно выведены после ошибок: " + ", ".join(tripped) + ".", "providers")
    return check("payments", "Платежи", "ok", detail, "providers")


def telegram_check() -> dict:
    if not settings.bot_token:
        return check("telegram", "Telegram-бот", "off", "Бот не настроен: укажите BOT_TOKEN и BOT_USERNAME.", "content")
    if not settings.bot_username:
        return check("telegram", "Telegram-бот", "warn", "Токен задан, но нет BOT_USERNAME (вводится в «Настройки без перезапуска»): ссылки на бота не построятся.", "content")
    return check("telegram", "Telegram-бот", "ok", f"Токен и имя заданы: @{settings.bot_username.lstrip('@')}. Связь бота с Telegram проверяет healthcheck его контейнера.", "content")


async def jobs_check(db: AsyncSession) -> dict:
    now = datetime.utcnow()
    workers = int(await db.scalar(select(func.count()).select_from(WorkerState).where(
        WorkerState.role == settings.worker_role, WorkerState.status == "online",
        WorkerState.last_seen_at >= now - timedelta(seconds=WORKER_STALE_SECONDS))) or 0)
    stuck = int(await db.scalar(select(func.count()).select_from(Job).where(
        Job.status == "queued", Job.created_at < now - timedelta(minutes=QUEUE_STUCK_MINUTES),
        (Job.next_retry_at.is_(None)) | (Job.next_retry_at < now))) or 0)
    failed = int(await db.scalar(select(func.count()).select_from(Job).where(
        Job.status == "failed", Job.created_at >= now - timedelta(days=1))) or 0)
    if not workers:
        return check("jobs", "Фоновые задачи", "error", f"Нет живого обработчика задач (отметка старше {WORKER_STALE_SECONDS} с): выдача после оплаты не идёт.", "workers")
    parts = [f"Обработчиков на связи: {workers}."]
    if stuck:
        parts.append(f"Ждут дольше {QUEUE_STUCK_MINUTES} мин: {stuck}.")
    if failed:
        parts.append(f"Не выполнены за сутки: {failed}.")
    return check("jobs", "Фоновые задачи", "warn" if stuck or failed else "ok", " ".join(parts), "jobs")


async def backup_check(db: AsyncSession) -> dict:
    last = await db.scalar(select(BackupJob).where(BackupJob.status.in_(SUCCESS_BACKUP)).order_by(BackupJob.id.desc()).limit(1))
    if not last:
        return check("backup", "Резервные копии", "error", "Ни одной успешной копии: создайте её в разделе «Резервные копии».", "backups")
    at = last.finished_at or last.created_at
    hours = (datetime.utcnow() - at).total_seconds() / 3600
    if hours > BACKUP_WARN_HOURS:
        return check("backup", "Резервные копии", "warn", f"Последняя успешная копия {int(hours // 24)} дн. {int(hours % 24)} ч назад.", "backups")
    return check("backup", "Резервные копии", "ok", f"Последняя успешная копия {max(int(hours), 0)} ч назад.", "backups")


async def latest_release(fetch) -> dict | None:
    now = time.monotonic()
    cached = _update_cache["value"]
    age = now - _update_cache["at"]
    if _update_cache["at"] and age < (UPDATE_CACHE_SECONDS if cached else UPDATE_FAILURE_CACHE_SECONDS):
        return cached
    try:
        value = await asyncio.wait_for(fetch(), NETWORK_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.info("Control center: release lookup failed: %s", exc)
        value = None
    _update_cache.update(at=now, value=value)
    return value


async def updates_check(version: str, distribution: str, fetch=None) -> dict:
    from .github_update import fetch_latest_release, release_status
    payload = await latest_release(fetch or fetch_latest_release)
    if payload is None:
        return check("updates", "Обновления", "warn", f"Установлен {distribution}. GitHub не ответил — наличие нового выпуска неизвестно.", "releases")
    status = release_status(version, payload, current_distribution=distribution)
    if status["update_available"]:
        return check("updates", "Обновления", "warn", f"Установлен {distribution}, доступен v{status['latest']}.", "releases")
    return check("updates", "Обновления", "ok", f"Установлен {distribution} — это последний выпуск.", "releases")


def overall(checks: list[dict]) -> str:
    states = {c["status"] for c in checks}
    return "degraded" if "error" in states else "attention" if "warn" in states else "ok"


async def collect(db: AsyncSession, *, version: str, distribution: str, redis_client, remnawave_factory, payments_paused: bool) -> list[dict]:
    """All checks in a fixed order. Database checks run one after another on the request session; network checks
    (Redis, Remnawave, reverse proxy, GitHub) run in parallel, each with its own time limit."""
    network = asyncio.gather(frontend_check(), redis_check(redis_client), remnawave_checks(remnawave_factory), proxy_checks(),
                             updates_check(version, distribution))
    rows = [backend_check(version, distribution), *await database_checks(db)]
    db_rows: list[dict] = []
    steps = (("payments", "Платежи", "providers", lambda: payments_check(db, payments_paused)),
             ("jobs", "Фоновые задачи", "jobs", lambda: jobs_check(db)),
             ("backup", "Резервные копии", "backups", lambda: backup_check(db)))
    for key, title, tab, step in steps:
        try:
            db_rows.append(await step())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Control center: %s check failed: %s", key, exc)
            await db.rollback()
            db_rows.append(check(key, title, "error", "Проверка не выполнена: база не ответила.", tab, error="unavailable"))
    frontend_row, redis_row, remnawave_rows, proxy_rows, update_row = await network
    return [rows[0], frontend_row, *rows[1:], redis_row, *remnawave_rows, *proxy_rows, *db_rows, telegram_check(), update_row]
