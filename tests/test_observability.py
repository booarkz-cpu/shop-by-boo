from datetime import datetime, timedelta
import json
from pathlib import Path
import pytest
from app.observability import operational_metrics
from app.models import Job, SupportTicket, WorkerState
from test_subscription_commerce import database


@pytest.mark.asyncio
async def test_gauges_zero_fill_bound_status_and_exclude_private_data(database):
    database.add_all([Job(job_key='secret-account-key',kind='email',status='queued',created_at=datetime.utcnow()-timedelta(seconds=100)),
        Job(job_key='other-key',kind='private-kind',status='unknown-status-with-secret'),
        WorkerState(worker_id='secret-host',role='primary',last_seen_at=datetime.utcnow()),
        WorkerState(worker_id='old-host',role='primary',last_seen_at=datetime.utcnow()-timedelta(minutes=5)),
        SupportTicket(user_id=1,subject='private-email',message='private-message',status='open')])
    await database.commit()
    output=await operational_metrics(database)
    assert 'vpnshop_jobs{status="queued"} 1' in output
    assert 'vpnshop_jobs{status="failed"} 0' in output
    assert 'vpnshop_jobs{status="other"} 1' in output
    assert 'vpnshop_workers_online 1' in output
    assert 'vpnshop_subscriptions_active 1' in output
    assert 'vpnshop_support_tickets{status="open"} 1' in output
    age=float(next(x.split()[-1] for x in output.splitlines() if x.startswith('vpnshop_oldest_queued_job_seconds ')))
    assert 99 <= age <= 110
    for secret in ('secret','private','unknown-status','old-host','primary'):assert secret not in output


def test_dashboard_panels_have_unique_ids_and_fit_grid():
    dashboard=json.loads(Path('infrastructure/monitoring/grafana/vpnshop-operations.json').read_text())
    assert len(dashboard['panels'])==14
    assert len({x['id'] for x in dashboard['panels']})==14
    for panel in dashboard['panels']:
        assert panel['gridPos']['x']+panel['gridPos']['w']<=24
        assert panel['datasource']['uid']=='${datasource}'
        assert 'job="$job"' in panel['targets'][0]['expr']


@pytest.mark.asyncio
async def test_metrics_database_failure_is_explicit_not_zero_counts(monkeypatch):
    from app import main as shop, db as database_module
    from starlette.requests import Request
    class BrokenSession:
        async def __aenter__(self):raise RuntimeError('unavailable database with private details')
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(database_module,'SessionLocal',BrokenSession)
    monkeypatch.setattr(shop.settings,'metrics_enabled',True)
    monkeypatch.setattr(shop.settings,'metrics_token','metrics-test-token')
    response=await shop.metrics(Request({'type':'http','headers':[(b'x-metrics-token',b'metrics-test-token')]}))
    output=response.body.decode()
    assert 'vpnshop_database_metrics_available 0' in output
    assert 'vpnshop_jobs{' not in output and 'vpnshop_payments{' not in output
    assert 'private' not in output


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,token,header,status',[(False,'secret','secret',404),(True,'','',503),(True,'secret','wrong',401)])
async def test_metrics_authentication_fails_closed(monkeypatch,enabled,token,header,status):
    from app import main as shop
    from fastapi import HTTPException
    from starlette.requests import Request
    monkeypatch.setattr(shop.settings,'metrics_enabled',enabled)
    monkeypatch.setattr(shop.settings,'metrics_token',token)
    with pytest.raises(HTTPException) as error:
        await shop.metrics(Request({'type':'http','headers':[(b'x-metrics-token',header.encode())]}))
    assert error.value.status_code==status
