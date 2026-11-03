"""Deployment Agent: the runner of the Remnawave wizard's installations (v28.66, stage 10; docs/ru/new/DEPLOYMENT_AGENT.md).

The worker calls ``run_next`` in its own loop (``installer_worker``). An approved installation is ``queued``; one
worker takes it with ``FOR UPDATE SKIP LOCKED``, marks it ``running`` and runs its steps in order over SSH, writing
each step's status and log tail. While it runs, ``heartbeat_at`` moves every 20 seconds; a ``running`` row whose
heartbeat stopped for 5 minutes (the worker died) becomes ``failed`` with «прервано», never silently re-run.

After a failed step the runner undoes what the run did, in reverse order:
* install — files removed or restored, containers stopped (volumes stay), node removed from the panel, ufw rule removed;
* update / reinstall — the previous files are restored and the containers started again from them;
* diagnose, restore, remove — nothing to undo; the failure is reported as it is."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import rw_plan, rw_steps
from .models import RemnawaveDeploymentStep, RemnawaveInstallation, RemnawaveServer
from .rw_remote import tail
from .security import decrypt_secret, encrypt_secret

logger = logging.getLogger("vpnshop.rw_jobs")
STALE = timedelta(minutes=5)
HEARTBEAT_SECONDS = 20
CONNECT = None  # tests replace it with a fake SSH factory


def server_dict(row: RemnawaveServer) -> dict:
    secret = decrypt_secret(row.ssh_secret)
    return {"id": row.id, "name": row.name, "host": row.host, "ssh_port": row.ssh_port, "ssh_user": row.ssh_user,
            "host_key_fingerprint": row.host_key_fingerprint,
            "key": secret if row.auth_method == "key" else None, "password": secret if row.auth_method == "password" else None}


def load_secrets(row: RemnawaveInstallation) -> dict:
    return json.loads(decrypt_secret(row.secrets)) if row.secrets else {}


def store_secrets(row: RemnawaveInstallation, secrets: dict) -> None:
    row.secrets = encrypt_secret(json.dumps(secrets, sort_keys=True))


async def recover_stale(engine) -> int:
    now = datetime.utcnow()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        rows = (await db.execute(select(RemnawaveInstallation).where(
            RemnawaveInstallation.status == "running",
            (RemnawaveInstallation.heartbeat_at.is_(None)) | (RemnawaveInstallation.heartbeat_at < now - STALE)))).scalars().all()
        for row in rows:
            row.status = "failed"; row.finished_at = now; row.worker_id = None
            row.error = "Прервано: исполнитель остановился во время установки. Проверьте серверы («Диагностика») и запустите заново"
            await db.execute(update(RemnawaveDeploymentStep).where(RemnawaveDeploymentStep.installation_id == row.id,
                                                                   RemnawaveDeploymentStep.status == "running").values(status="failed", finished_at=now))
        await db.commit()
        return len(rows)


async def _heartbeat(engine, installation_id: int) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            async with AsyncSession(engine) as db:
                await db.execute(update(RemnawaveInstallation).where(RemnawaveInstallation.id == installation_id)
                                 .values(heartbeat_at=datetime.utcnow()))
                await db.commit()
        except Exception:
            logger.exception("installation %s heartbeat failed", installation_id)


async def run_next(engine, worker_id: str) -> bool:
    """Take one queued installation and run it to the end. Returns False when nothing was queued."""
    await recover_stale(engine)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        row = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.status == "queued")
                                .order_by(RemnawaveInstallation.id).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if not row:
            return False
        now = datetime.utcnow()
        row.status = "running"; row.started_at = now; row.heartbeat_at = now; row.worker_id = worker_id
        await db.commit()
    beat = asyncio.create_task(_heartbeat(engine, row.id))
    try:
        await execute(engine, row.id)
    except Exception:
        logger.exception("installation %s crashed", row.id)
        async with AsyncSession(engine) as db:
            await db.execute(update(RemnawaveInstallation).where(RemnawaveInstallation.id == row.id, RemnawaveInstallation.status == "running")
                             .values(status="failed", error="Внутренняя ошибка исполнителя (журнал worker)", finished_at=datetime.utcnow()))
            await db.commit()
    finally:
        beat.cancel()
    return True


async def _context(db: AsyncSession, row: RemnawaveInstallation) -> rw_steps.Context:
    from .config import settings
    plan = rw_plan.PlanIn(**row.params)
    servers = {}
    for sid in row.server_ids:
        server = await db.get(RemnawaveServer, sid)
        if not server:
            raise rw_steps.StepError(f"Сервер {sid} удалён из реестра")
        servers[sid] = server_dict(server)
    state = dict((row.result or {}).get("state") or {})
    return rw_steps.Context(plan=plan, servers=servers, secrets=load_secrets(row), state=state,
                            shop_panel_url=(settings.remnawave_url or "").rstrip("/") or None,
                            shop_panel_token=settings.remnawave_token or None, connect=CONNECT)


def _step_dict(st: RemnawaveDeploymentStep) -> dict:
    return {"kind": st.kind, "server_id": st.server_id, "params": st.params or {}, "title": st.title}


async def _save(db: AsyncSession, row: RemnawaveInstallation, ctx: rw_steps.Context, st: RemnawaveDeploymentStep | None = None,
                status: str | None = None) -> None:
    store_secrets(row, ctx.secrets)
    row.result = {**(row.result or {}), "state": ctx.state}
    if st is not None:
        st.log_tail = tail("\n".join(ctx.log), ctx.secret_values()) or None
        if status:
            st.status = status
            st.finished_at = datetime.utcnow()
    ctx.log.clear()
    await db.commit()


async def execute(engine, installation_id: int) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        row = await db.get(RemnawaveInstallation, installation_id)
        steps = (await db.execute(select(RemnawaveDeploymentStep).where(RemnawaveDeploymentStep.installation_id == row.id)
                                  .order_by(RemnawaveDeploymentStep.position))).scalars().all()
        try:
            ctx = await _context(db, row)
        except (rw_steps.StepError, ValueError) as exc:
            row.status = "failed"; row.error = str(exc)[:2000]; row.finished_at = datetime.utcnow()
            await db.commit()
            return
        done: list[RemnawaveDeploymentStep] = []
        failure = None
        for st in steps:
            await db.refresh(row, ["cancel_requested"])
            if row.cancel_requested:
                failure = "Отменено администратором"
                break
            if st.kind not in rw_steps.STEP_KINDS:
                failure = f"Шаг {st.kind} не из закрытого списка"
                st.status = "failed"
                break
            st.status = "running"; st.started_at = datetime.utcnow()
            await db.commit()
            try:
                await rw_steps.RUN[st.kind](ctx, _step_dict(st))
            except rw_steps.StepError as exc:
                failure = f"{st.title}: {exc}"
                ctx.log.append(f"Ошибка: {exc}")
                await _save(db, row, ctx, st, "failed")
                break
            except Exception as exc:
                logger.exception("installation %s step %s crashed", row.id, st.kind)
                failure = f"{st.title}: внутренняя ошибка ({type(exc).__name__})"
                await _save(db, row, ctx, st, "failed")
                break
            await _save(db, row, ctx, st, "done")
            done.append(st)
            if st.kind == "preflight":
                await _remember_facts(db, st.server_id, ctx.state.get("preflight", {}).get(str(st.server_id)))
        if failure is None:
            await _finish(db, row, ctx)
            return
        await _rollback(db, row, ctx, done)
        for st in steps:
            if st.status == "pending":
                st.status = "skipped"
        row.status = "cancelled" if row.cancel_requested and failure == "Отменено администратором" else "failed"
        row.error = failure[:2000]; row.finished_at = datetime.utcnow(); row.worker_id = None
        await _save(db, row, ctx)


async def _rollback(db: AsyncSession, row: RemnawaveInstallation, ctx: rw_steps.Context, done: list) -> None:
    if row.action == "install":
        undo = [st for st in reversed(done) if st.kind in rw_steps.UNDO]
        for st in undo:
            try:
                await rw_steps.UNDO[st.kind](ctx, _step_dict(st))
                ctx.log.append("Отменено")
                await _save(db, row, ctx, st, "rolled_back")
            except Exception as exc:
                ctx.log.append(f"Отменить не удалось: {type(exc).__name__}: {exc}")
                await _save(db, row, ctx, st)
    elif row.action in ("update", "reinstall"):
        written = [st for st in reversed(done) if st.kind == "write_files"]
        for st in written:
            try:
                await rw_steps.UNDO["write_files"](ctx, _step_dict(st))
                await rw_steps.run_compose_up(ctx, {**_step_dict(st), "kind": "compose_up"})
                ctx.log.append("Возвращены прежние файлы, контейнеры запущены с ними")
                await _save(db, row, ctx, st, "rolled_back")
            except Exception as exc:
                ctx.log.append(f"Вернуть прежнее не удалось: {type(exc).__name__}: {exc}")
                await _save(db, row, ctx, st)


async def _remember_facts(db: AsyncSession, server_id: int, out: dict | None) -> None:
    server = await db.get(RemnawaveServer, server_id)
    if not server or not out:
        return
    facts = out.get("facts", {})
    server.os = (facts.get("os_name") or "")[:64] or None
    server.arch = facts.get("arch"); server.cpu_cores = facts.get("cpu"); server.ram_mb = facts.get("ram_mb")
    server.disk_gb = facts.get("disk_gb"); server.preflight = out; server.last_checked_at = datetime.utcnow()
    server.updated_at = datetime.utcnow()
    await db.commit()


async def _finish(db: AsyncSession, row: RemnawaveInstallation, ctx: rw_steps.Context) -> None:
    roles = rw_plan.roles_of(ctx.plan)
    for sid, rs in roles.items():
        server = await db.get(RemnawaveServer, sid)
        if not server:
            continue
        if row.action == "remove":
            server.roles = [r for r in (server.roles or []) if r not in rs]
            server.status = "removed" if not server.roles else "installed"
        elif row.action in ("install", "update", "reinstall", "restore"):
            server.roles = sorted(set(server.roles or []) | set(rs))
            server.status = "installed"
        server.updated_at = datetime.utcnow()
    plan = ctx.plan
    row.result = {**(row.result or {}), "state": ctx.state,
                  "panel_url": f"https://{plan.panel_domain}" if plan.panel_domain and plan.panel_server_id else None,
                  "subscription_url": f"https://{plan.sub_domain}" if plan.sub_domain and plan.subpage_server_id else None,
                  "nodes": ctx.state.get("nodes", {})}
    row.status = "succeeded"; row.error = None; row.finished_at = datetime.utcnow(); row.worker_id = None
    await _save(db, row, ctx)


async def installer_worker(engine, worker_id: str) -> None:
    """The worker's loop: separate from the generic job queue, so an hour-long installation never blocks payments."""
    await recover_stale(engine)
    while True:
        try:
            if not await run_next(engine, worker_id):
                await asyncio.sleep(3)
        except Exception:
            logger.exception("installer loop failure")
            await asyncio.sleep(5)
