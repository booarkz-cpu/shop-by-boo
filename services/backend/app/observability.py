"""Bounded, non-personal operational gauges shared by all API replicas."""
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from .models import Job, Payment, RefundRequest, Subscription, SupportTicket, WorkerState

STATUS_METRICS = (
    ('vpnshop_jobs', Job, ('queued', 'processing', 'completed', 'failed')),
    ('vpnshop_payments', Payment, ('pending', 'paid', 'fulfilled', 'failed', 'cancelled', 'refunded')),
    ('vpnshop_refunds', RefundRequest, ('requested', 'approved', 'processing', 'refunded', 'failed', 'review')),
    ('vpnshop_support_tickets', SupportTicket, ('open', 'in_progress', 'answered', 'closed')),
)


def gauge(name, description, values):
    return f'# HELP {name} {description}\n# TYPE {name} gauge\n' + ''.join(
        f'{name}{labels} {value}\n' for labels, value in values)


async def operational_metrics(db):
    now = datetime.utcnow()
    lines=[]
    for name, model, statuses in STATUS_METRICS:
        rows=(await db.execute(select(model.status, func.count()).group_by(model.status))).all()
        counts=dict(rows)
        other=sum(count for status, count in rows if status not in statuses)
        lines.append(gauge(name, 'Current database records by bounded status',
            [(f'{{status="{status}"}}', int(counts.get(status, 0))) for status in statuses]+[('{status="other"}', other)]))
    oldest=await db.scalar(select(func.min(Job.created_at)).where(Job.status == 'queued'))
    seconds=max(0, (now-oldest).total_seconds()) if oldest else 0
    online=await db.scalar(select(func.count()).select_from(WorkerState).where(
        WorkerState.status == 'online', WorkerState.last_seen_at >= now-timedelta(seconds=90)))
    active=await db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.lifecycle_status.in_(['active','cancel_scheduled','grace']),
        or_(Subscription.expires_at.is_(None), Subscription.expires_at > now)))
    lines.extend([
        gauge('vpnshop_oldest_queued_job_seconds','Age of oldest queued job including retry backoff',[('',round(seconds,3))]),
        gauge('vpnshop_workers_online','Workers with heartbeat within ninety seconds',[('',int(online or 0))]),
        gauge('vpnshop_subscriptions_active','Current locally active subscriptions, not a remote VPN probe',[('',int(active or 0))]),
        gauge('vpnshop_database_metrics_available','One when this scrape read database metrics',[('',1)]),
    ])
    # v28.147.0 (REQ-INFRA-0025): latency percentiles, disk, memory, CPU load and the database pool.
    from .host_metrics import lines as host_lines
    from .config import settings
    lines.append(host_lines(getattr(settings, 'media_dir', None)))
    return ''.join(lines)


async def security_metrics(db):
    """v28.75.0 (stage 16): security, backups and Remnawave — counts only, nothing personal."""
    from .models import AuditLog, BackupJob, RemnawaveInstallation, RemnawaveServer
    from .node_health import STATE_KEY, _load
    from .rw_ssh import KEY_MAX_AGE_DAYS
    now = datetime.utcnow()

    async def audits(action, since):
        return int(await db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == action, AuditLog.created_at >= since)) or 0)
    backup = await db.scalar(select(func.max(BackupJob.created_at)).where(BackupJob.status == 'completed'))
    servers = (await db.execute(select(RemnawaveServer.ssh_key_marker, RemnawaveServer.ssh_key_rotated_at))).all()
    due = sum(1 for marker, at in servers if not marker or (at and (now - at).days >= KEY_MAX_AGE_DAYS))
    failed = int(await db.scalar(select(func.count()).select_from(RemnawaveInstallation).where(
        RemnawaveInstallation.status == 'failed', RemnawaveInstallation.finished_at >= now - timedelta(days=1))) or 0)
    state = await _load(db, STATE_KEY, {"nodes": {}})
    down = sum(1 for item in (state.get("nodes") or {}).values() if isinstance(item, dict) and item.get("down_since"))
    return ''.join([
        gauge('vpnshop_admin_login_failures_15m', 'Failed sign-ins to the admin panel in the last 15 minutes',
              [('', await audits('admin.login.failed', now - timedelta(minutes=15)))]),
        gauge('vpnshop_admin_stepup_failures_1h', 'Wrong confirmations of dangerous actions in the last hour',
              [('', await audits('security.stepup.failed', now - timedelta(hours=1)))]),
        gauge('vpnshop_backup_last_success_age_seconds', 'Seconds since the last completed backup (-1: none yet)',
              [('', round((now - backup).total_seconds()) if backup else -1)]),
        gauge('vpnshop_rw_ssh_key_rotation_due', 'Wizard servers with an owner key or a shop key older than the limit',
              [('', due)]),
        gauge('vpnshop_rw_installations_failed_24h', 'Remnawave wizard runs that failed in the last day', [('', failed)]),
        gauge('vpnshop_nodes_down', 'Remnawave nodes the health monitor sees down', [('', down)]),
    ])
