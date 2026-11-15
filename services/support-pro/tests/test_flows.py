import asyncio
import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.types import Message as TelegramMessage
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select, func
from fastapi.testclient import TestClient
from app import main, bot, worker, storage
from app.models import Operator, Ticket, Message, Attachment, Client, Notification, TicketRead, Settings, Macro, now
from app.services import create_ticket, close_ticket
from app.sla import DEFAULTS, business_add, validate, utc
from conftest import post

pytestmark = pytest.mark.asyncio


def incoming(uid=777, mid=1, text='Нужна помощь', **kwargs):
    return TelegramMessage.model_validate({'message_id': mid, 'date': now(), 'chat': {'id': uid, 'type': 'private'},
        'from': {'id': uid, 'is_bot': False, 'first_name': 'Анна', 'username': 'anna'}, 'text': text, **kwargs})


class FakeBot:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.media_failure = None
    async def send_message(self, uid, text, **kwargs):
        self.calls.append(('text', uid, text))
        if self.failure:
            raise self.failure
        return SimpleNamespace(message_id=len(self.calls) + 100)
    async def send_document(self, uid, file, **kwargs):
        self.calls.append(('document', uid, file.filename))
        if self.media_failure:
            raise self.media_failure
        return SimpleNamespace(message_id=len(self.calls) + 100)
    send_photo = send_document
    send_video = send_document
    async def get_file(self, file_id):
        return SimpleNamespace(file_path='file/path', file_size=7)
    async def download_file(self, path, destination, **kwargs):
        destination.write(b'example')


async def test_incoming_attachment_delivery_read_and_search(env):
    tid = await bot.receive(incoming(text=None, caption='Ошибка оплаты', photo=[{'file_id': 'PHOTO', 'file_unique_id': 'UNIQUE', 'width': 20, 'height': 20, 'file_size': 7}]))
    fake = FakeBot()
    assert await worker.download_one(fake)
    async with env['session']() as s:
        t = await s.get(Ticket, tid)
        assert t.assigned_to == env['oid'] and t.waiting_since and t.first_response_due
        a = await s.scalar(select(Attachment))
        assert a.state == 'ready' and storage.checked_path(a.path).read_bytes() == b'example'
        aid, last_id = a.id, t.last_customer_message_id
    assert (await env['client'].get(f'/attachment/{aid}')).content == b'example'
    assert (await env['client'].get('/?queue=unread')).text.count('Новое сообщение') == 1
    assert (await post(env, f'/ticket/{tid}/read', last_id=last_id)).status_code == 200
    page = await env['client'].get('/?queue=unread')
    assert 'Найдено: 0' in page.text
    response = await post(env, f'/ticket/{tid}/reply', text='Проверяем заказ', kind='reply', nonce='1234567890abcdef')
    assert response.status_code == 303
    mid = await worker.claim_message()
    assert mid
    await worker.deliver(fake, mid)
    async with env['session']() as s:
        m = await s.get(Message, mid)
        t = await s.get(Ticket, tid)
        assert m.delivery_state == 'sent' and m.operator_id == env['oid']
        assert t.first_response_at and t.waiting_since is None
    assert 'Ошибка оплаты' in (await env['client'].get('/?q=Проверяем')).text
    assert f'/ticket/{tid}' in (await env['client'].get('/?q=%23' + str(tid))).text
    assert 'Отправлено в Telegram' in (await env['client'].get(f'/ticket/{tid}')).text


async def test_incoming_dedup_and_note_never_sent(env):
    tid = await bot.receive(incoming())
    assert await bot.receive(incoming()) == tid
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Message)) == 1
    for _ in range(2):
        response = await post(env, f'/ticket/{tid}/reply', text='Секретная заметка', kind='note', nonce='note12345678901234')
        assert response.status_code == 303
    assert await worker.claim_message() is None
    async with env['session']() as s:
        notes = (await s.scalars(select(Message).where(Message.sender == 'note'))).all()
        assert len(notes) == 1 and notes[0].delivery_state == 'internal'
    assert 'Внутренняя заметка' in (await env['client'].get(f'/ticket/{tid}')).text


async def test_delivery_unknown_requires_confirmation(env):
    tid = await bot.receive(incoming())
    await post(env, f'/ticket/{tid}/reply', text='Ответ', nonce='reply12345678901234')
    mid = await worker.claim_message()
    fake = FakeBot()
    fake.failure = TelegramNetworkError(method=SendMessage(chat_id=777, text='x'), message='timeout')
    await worker.deliver(fake, mid)
    async with env['session']() as s:
        assert (await s.get(Message, mid)).delivery_state == 'uncertain'
        assert (await s.get(Ticket, tid)).first_response_at is None
    assert await worker.claim_message() is None
    assert (await post(env, f'/message/{mid}/retry')).status_code == 400
    assert (await post(env, f'/message/{mid}/retry', confirm_duplicate='yes')).status_code == 303
    fake.failure = None
    assert await worker.claim_message() == mid
    await worker.deliver(fake, mid)
    async with env['session']() as s:
        assert (await s.get(Message, mid)).delivery_state == 'sent'


async def test_partial_delivery_does_not_repeat_confirmed_text(env):
    tid = await bot.receive(incoming())
    response = await env['client'].post(f'/ticket/{tid}/reply', data={'csrf_token': env['csrf'], 'text': 'A' * 2000, 'nonce': 'file12345678901234'},
        files={'file': ('sample.txt', b'data', 'text/plain')})
    assert response.status_code == 303
    mid = await worker.claim_message()
    fake = FakeBot()
    fake.media_failure = TelegramBadRequest(method=SendMessage(chat_id=777, text='x'), message='document invalid')
    await worker.deliver(fake, mid)
    async with env['session']() as s:
        m = await s.get(Message, mid)
        assert m.text_sent and not m.attachment_sent and m.delivery_state == 'failed'
    await post(env, f'/message/{mid}/retry')
    fake.media_failure = None
    await worker.deliver(fake, await worker.claim_message())
    assert [c[0] for c in fake.calls] == ['text', 'document', 'document']
    assert fake.calls[0][2].endswith('A' * 2000) and '#1' in fake.calls[0][2]


async def test_new_incoming_while_reply_queued_remains_waiting(env):
    tid = await bot.receive(incoming())
    await post(env, f'/ticket/{tid}/reply', text='Ответ на первый вопрос', nonce='fresh12345678901234')
    await bot.receive(incoming(mid=2, text='Ещё вопрос'))
    await worker.deliver(FakeBot(), await worker.claim_message())
    async with env['session']() as s:
        assert (await s.get(Ticket, tid)).waiting_since is not None


async def test_split_moves_attachments_and_client_history(env):
    tid = await bot.receive(incoming())
    await bot.receive(incoming(mid=2, text=None, document={'file_id':'DOC','file_unique_id':'DOC_U','file_name':'sample.txt','file_size':7}))
    async with env['session']() as s:
        m = await s.scalar(select(Message).where(Message.source_key == 'tg:777:2'))
        mid = m.id
    response = await post(env, f'/ticket/{tid}/split', subject='Отдельная проблема', message_ids=str(mid))
    assert response.status_code == 303
    new_tid = int(response.headers['location'].split('/')[-1])
    async with env['session']() as s:
        assert (await s.get(Message, mid)).ticket_id == new_tid
        assert (await s.scalar(select(Attachment))).ticket_id == new_tid
        assert (await s.get(Client, 777)).current_ticket_id == new_tid
        assert (await s.get(Ticket, tid)).last_customer_message_id != mid
    assert await bot.receive(incoming(mid=3, text='Продолжение')) == new_tid
    page = await env['client'].get('/client/777')
    assert 'Отдельная проблема' in page.text and 'Нужна помощь' in page.text
    assert (await post(env, '/client/777', tags='VIP, оплата', notes='Проверить договор')).status_code == 303
    assert 'Проверить договор' in (await env['client'].get('/client/777')).text


async def test_rating_ownership_and_close_idempotency(env):
    tid = await bot.receive(incoming())
    for _ in range(2):
        assert (await post(env, f'/ticket/{tid}/update', status='closed', priority='normal', assigned_to=env['oid'])).status_code == 303
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Message).where(Message.sender == 'system')) == 1
    callback = SimpleNamespace(data=f'rate:{tid}:5', from_user=SimpleNamespace(id=888), answer=AsyncMock(), message=SimpleNamespace(edit_text=AsyncMock()))
    await bot.rate(callback)
    async with env['session']() as s:
        assert (await s.get(Ticket, tid)).rating is None
    callback.from_user.id = 777
    await bot.rate(callback)
    async with env['session']() as s:
        assert (await s.get(Ticket, tid)).rating == 5
    callback.data = f'rate:{tid}:1'
    await bot.rate(callback)
    async with env['session']() as s:
        assert (await s.get(Ticket, tid)).rating == 5


async def test_auth_csrf_revocation_and_roles(env):
    tid = await bot.receive(incoming())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://testserver') as anon:
        assert (await anon.get(f'/ticket/{tid}')).status_code == 303
        assert (await anon.get('/attachment/1')).status_code == 303
    assert (await env['client'].post(f'/ticket/{tid}/reply', data={'text':'not allowed'})).status_code == 403
    assert (await post(env, f'/ticket/{tid}/update', status='arbitrary', priority='normal')).status_code == 400
    async with env['session']() as s:
        op = await s.get(Operator, env['oid'])
        op.role = 'operator'
        await s.commit()
    assert (await env['client'].get('/reports')).status_code == 403
    assert (await post(env, '/catalog/category', name='Unauthorized')).status_code == 403
    async with env['session']() as s:
        op = await s.get(Operator, env['oid'])
        op.active = False
        await s.commit()
    assert (await env['client'].get('/')).status_code == 303


async def test_totp_replay_rejected(env):
    # The code used to sign in, not «now()»: across a 30-second boundary now() is a fresh, valid code (the old flake).
    response = await post(env, '/login', login='admin', password='correct-password-123', code=env['code'])
    assert response.status_code == 401


async def test_websocket_denies_missing_login_origin_csrf(env):
    tid = await bot.receive(incoming())
    from starlette.websockets import WebSocketDisconnect
    with TestClient(main.app, base_url='https://testserver') as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f'/ws/ticket/{tid}', headers={'origin':'https://testserver'}):
                pass
        client.cookies.update(dict(env['client'].cookies))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f'/ws/ticket/{tid}?csrf={env["csrf"]}', headers={'origin':'https://evil.example'}):
                pass
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f'/ws/ticket/{tid}?csrf=wrong', headers={'origin':'https://testserver'}):
                pass


async def test_assignment_capacity_and_sla_dedup(env):
    async with env['session']() as s:
        op = await s.get(Operator, env['oid'])
        op.capacity = 1
        other = Operator(login='second', password_hash='unused', role='operator', capacity=1)
        s.add(other)
        await s.commit()
        second = other.id
    one = await bot.receive(incoming(uid=1))
    two = await bot.receive(incoming(uid=2))
    three = await bot.receive(incoming(uid=3))
    async with env['session']() as s:
        assert (await s.get(Ticket, one)).assigned_to == env['oid']
        assert (await s.get(Ticket, two)).assigned_to == second
        assert (await s.get(Ticket, three)).assigned_to is None
        t = await s.get(Ticket, one)
        t.first_response_due = now() - timedelta(minutes=1)
        await s.commit()
    await worker.maintenance()
    async with env['session']() as s:
        count = await s.scalar(select(func.count()).select_from(Notification))
    await worker.maintenance()
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Notification)) == count
        await close_ticket(s, await s.get(Ticket, one))
        await s.commit()
    await worker.maintenance()
    async with env['session']() as s:
        assert (await s.get(Ticket, three)).assigned_to == env['oid']


async def test_catalog_settings_reports_and_pagination(env):
    assert (await post(env, '/catalog/category', name='Возвраты')).status_code == 303
    assert (await post(env, '/catalog/category', name='Возвраты')).status_code == 409
    assert (await post(env, '/catalog/macro', title='Приветствие', body='Здравствуйте, {name}! #{ticket_id}', active='on')).status_code == 303
    for i in range(32):
        await bot.receive(incoming(uid=1000+i, text='=FORMULA' if i == 0 else f'Question {i}'))
    page = await env['client'].get('/')
    assert 'Найдено: 32' in page.text and '1 / 2' in page.text
    assert '2 / 2' in (await env['client'].get('/?page=2')).text
    assert (await env['client'].get('/?date_from=wrong')).status_code == 400
    for path in ['/catalog', '/settings', '/operators', '/reports', '/audit', '/client/1000']:
        response = await env['client'].get(path)
        assert response.status_code == 200, (path, response.text)
    report = await env['client'].get('/reports?format=csv')
    assert report.status_code == 200 and "'=FORMULA" in report.text
    values = {'timezone':'Europe/Moscow', 'workdays':['0','1','2','3','4'], 'start_hour':'10', 'end_hour':'19', 'warning_minutes':'15', 'auto_assign':'on'}
    for p in ('low','normal','high','urgent'):
        values['response_'+p] = '60'
        values['resolution_'+p] = '480'
    assert (await post(env, '/settings', **values)).status_code == 303
    async with env['session']() as s:
        assert (await s.get(Settings,1)).data['timezone'] == 'Europe/Moscow'


async def test_ai_disabled_and_provider_excludes_notes(env, monkeypatch):
    tid = await bot.receive(incoming())
    monkeypatch.delenv('AI_BASE_URL', raising=False)
    assert (await post(env, f'/ticket/{tid}/ai', mode='summary')).status_code == 503
    await post(env, f'/ticket/{tid}/reply', text='PRIVATE NOTE', kind='note', nonce='private123456789012')
    monkeypatch.setenv('AI_BASE_URL','https://provider.example/v1')
    monkeypatch.setenv('AI_API_KEY','secret-test')
    monkeypatch.setenv('AI_MODEL','model-test')
    captured = {}
    class Provider:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            captured.update(kwargs)
            return httpx.Response(200, json={'choices':[{'message':{'content':'Черновик ответа'}}]}, request=httpx.Request('POST',url))
    monkeypatch.setattr(main.httpx, 'AsyncClient', lambda **kwargs: Provider())
    response = await post(env, f'/ticket/{tid}/ai', mode='draft')
    assert response.json()['text'] == 'Черновик ответа'
    assert 'PRIVATE NOTE' not in json.dumps(captured, ensure_ascii=False)
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Message).where(Message.delivery_state == 'queued')) == 0


async def test_upload_bound_and_path_protection(env, monkeypatch):
    tid = await bot.receive(incoming())
    monkeypatch.setattr(storage, 'MAX_BYTES', 3)
    response = await env['client'].post(f'/ticket/{tid}/reply', data={'csrf_token':env['csrf'], 'nonce':'oversize12345678901'}, files={'file':('big.bin',b'1234','application/octet-stream')})
    assert response.status_code == 413
    assert not list((env['tmp_path']/'uploads').glob('*'))
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Message).where(Message.sender == 'operator')) == 0
    with pytest.raises(ValueError):
        storage.checked_path('/etc/passwd')


async def test_telegram_rate_limit_and_stale_claim(env):
    tid = await bot.receive(incoming())
    await post(env, f'/ticket/{tid}/reply', text='Ответ', nonce='retryafter123456789')
    fake = FakeBot()
    fake.failure = TelegramRetryAfter(method=SendMessage(chat_id=777,text='x'), message='rate', retry_after=10)
    mid = await worker.claim_message()
    await worker.deliver(fake,mid)
    assert await worker.claim_message() is None
    async with env['session']() as s:
        m = await s.get(Message,mid)
        assert m.delivery_state == 'queued' and m.next_attempt_at
        m.delivery_state, m.claimed_at = 'sending', now()-timedelta(minutes=6)
        await s.commit()
    await worker.maintenance()
    async with env['session']() as s:
        assert (await s.get(Message,mid)).delivery_state == 'uncertain'


async def test_sla_weekends_timezone_dst():
    config = dict(DEFAULTS)
    # Friday 17:30 UTC + 120 working minutes => Monday 10:30 UTC.
    assert business_add(datetime(2026,9,18,17,30,tzinfo=timezone.utc),120,config) == datetime(2026,9,21,10,30,tzinfo=timezone.utc)
    config = {**config,'timezone':'Europe/Moscow'}
    assert business_add(datetime(2026,9,18,14,30,tzinfo=timezone.utc),120,config) == datetime(2026,9,21,7,30,tzinfo=timezone.utc)
    config = {**config,'timezone':'Europe/Berlin','workdays':list(range(7)),'start_hour':0,'end_hour':24}
    assert business_add(datetime(2026,3,29,0,30,tzinfo=timezone.utc),120,config) == datetime(2026,3,29,2,30,tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        validate({**DEFAULTS,'workdays':[]})


async def test_websocket_authorized_connection(env, monkeypatch):
    tid = await bot.receive(incoming())
    class Pubsub:
        async def subscribe(self, channel): pass
        async def get_message(self, **kwargs):
            await asyncio.sleep(0.01)
            return {'data':'{"type":"changed"}'}
        async def aclose(self): pass
    monkeypatch.setattr(main, 'r', SimpleNamespace(pubsub=lambda: Pubsub()))
    with TestClient(main.app, base_url='https://testserver') as client:
        client.cookies.update(dict(env['client'].cookies))
        with client.websocket_connect(f'/ws/ticket/{tid}?csrf={env["csrf"]}', headers={'origin':'https://testserver'}) as ws:
            assert ws.receive_json() == {'type':'changed'}


async def test_operator_creation_and_health(env):
    response = await post(env, '/operators', login='agent', password='long-password-1234', role='operator')
    assert response.status_code == 200 and 'data:image/png;base64,' in response.text
    assert (await env['client'].get('/health')).status_code == 503
    import time
    await env['redis'].set('worker:heartbeat',str(time.time()))
    assert (await env['client'].get('/health')).status_code == 200
