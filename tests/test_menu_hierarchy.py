"""Menu safety, compatibility and optimistic updates on SQLite and PostgreSQL."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from app import main as shop, menu_tree as tree
from app.models import BotMenuItem, AppSetting, CustomField
from test_subscription_commerce import database

ADMIN=SimpleNamespace(email='menu@example.test',role='admin')

@pytest.mark.asyncio
async def test_bot_tree_cycles_depth_move_and_nonrecursive_delete(database):
    db=database
    ids=[]
    for depth in range(4):
        result=await shop.admin_menu(shop.MenuIn(title=f'Folder {depth}',item_type='folder',parent_id=ids[-1] if ids else None),db,ADMIN)
        ids.append(result['id'])
    with pytest.raises(HTTPException) as e:
        await shop.admin_menu(shop.MenuIn(title='Too deep',item_type='folder',parent_id=ids[-1]),db,ADMIN)
    assert e.value.status_code==400
    with pytest.raises(HTTPException) as e:
        await shop.admin_menu_update(ids[0],shop.MenuIn(title='Cycle',item_type='folder',parent_id=ids[2]),db,ADMIN)
    assert e.value.status_code==409
    with pytest.raises(HTTPException):await shop.admin_menu_delete(ids[0],db,ADMIN)
    with pytest.raises(HTTPException):await shop.admin_menu_update(ids[0],shop.MenuIn(title='Leaf',item_type='url',action='https://example.com'),db,ADMIN)
    other=await shop.admin_menu(shop.MenuIn(title='Other',item_type='folder'),db,ADMIN)
    with pytest.raises(HTTPException):await shop.admin_menu_update(ids[0],shop.MenuIn(title='Move entire subtree',item_type='folder',parent_id=other['id']),db,ADMIN)
    assert (await db.get(BotMenuItem,ids[0])).parent_id is None
    # Moving a subtree out to the root makes room for another child.
    await shop.admin_menu_update(ids[2],shop.MenuIn(title='Moved',item_type='folder'),db,ADMIN)
    await shop.admin_menu_delete(ids[1],db,ADMIN)
    with pytest.raises(HTTPException):await shop.admin_menu(shop.MenuIn(title='Invalid parent',item_type='folder',parent_id=9999),db,ADMIN)

@pytest.mark.asyncio
async def test_bot_keyboard_fields_styles_icons_and_disabled_ancestors(database):
    db=database
    db.add(CustomField(key='help',label='Help',value='<private text>',enabled=True));await db.commit()
    root=await shop.admin_menu(shop.MenuIn(title='Menu',item_type='folder',style='primary',icon_custom_emoji_id='123456'),db,ADMIN)
    leaf=await shop.admin_menu(shop.MenuIn(title='Help',item_type='field',action='help',parent_id=root['id'],style='success',icon_custom_emoji_id='234567'),db,ADMIN)
    rows=(await db.scalars(select(BotMenuItem))).all();fields=(await db.scalars(select(CustomField))).all()
    root_markup=tree.telegram_keyboard(rows,fields).model_dump(exclude_none=True)
    assert root_markup['inline_keyboard'][0][0]['style']=='primary'
    markup=tree.telegram_keyboard(rows,fields,root['id'])
    assert markup.inline_keyboard[0][0].callback_data==f"menu-field:{leaf['id']}"
    assert markup.inline_keyboard[-1][0].callback_data=='menu:0'
    fallback=tree.without_custom_icons(markup)
    assert fallback.inline_keyboard[0][0].icon_custom_emoji_id is None
    assert fallback.inline_keyboard[0][0].style=='success'
    (await db.get(BotMenuItem,root['id'])).enabled=False;await db.commit()
    assert tree.visible_children(rows,root['id'])==[]
    with pytest.raises(ValidationError):shop.MenuIn(title='Bad',style='red')
    with pytest.raises(ValidationError):shop.MenuIn(title='Bad',icon_custom_emoji_id='https://evil.test')

@pytest.mark.asyncio
async def test_mini_tree_atomic_update_stale_fingerprint_and_other_settings(database):
    db=database
    db.add(AppSetting(key='miniapp_title',value='Keep this title'));await db.commit()
    fingerprint=hashlib.sha256(b'[]').hexdigest()
    buttons=[{'id':'root','title':'Root','type':'folder','children':[{'id':'plans','title':'Plans','type':'plans','style':'danger'}]}]
    result=await tree.save_mini_tree(tree.MiniTreeIn(buttons=buttons,fingerprint=fingerprint),db,ADMIN)
    assert result['buttons'][0]['children'][0]['style']=='danger'
    assert result['fingerprint']!=fingerprint
    assert (await db.get(AppSetting,'miniapp_title')).value=='Keep this title'
    with pytest.raises(HTTPException) as e:await tree.save_mini_tree(tree.MiniTreeIn(buttons=[],fingerprint=fingerprint),db,ADMIN)
    assert e.value.status_code==409
    assert json.loads((await db.get(AppSetting,'miniapp_buttons')).value)[0]['id']=='root'
    # Old flat configurations receive generated stable IDs on their next save.
    normalized=tree.normalize_mini_buttons([{'title':'Legacy','type':'plans'}],set())
    assert normalized[0]['id'] and normalized[0]['children']==[]

@pytest.mark.parametrize('buttons',[
    [{'id':'same','title':'A','type':'plans'},{'id':'same','title':'B','type':'plans'}],
    [{'title':'Bad','type':'url','url':'javascript:alert(1)'}],
    [{'title':'Field','type':'field','field_key':'missing'}],
    [{'title':'No code','type':'promo'}],
    [{'title':'Leaf','type':'plans','children':[{'title':'Child','type':'plans'}]}],
    [{'title':'Empty','type':'plans','style':'red'}],
    [{'title':'   ','type':'plans'}],
    [{'title':'Many','type':'plans'}]*31,
])
def test_mini_invalid_nodes_rejected(buttons):
    with pytest.raises(HTTPException):tree.normalize_mini_buttons(buttons,set())

def test_mini_max_depth_includes_leaf():
    node={'title':'Leaf','type':'plans'}
    for i in range(4):node={'title':f'Folder{i}','type':'folder','children':[node]}
    with pytest.raises(HTTPException):tree.normalize_mini_buttons([node],set())

@pytest.mark.asyncio
async def test_telegram_custom_emoji_permission_fallback_keeps_other_errors():
    from app.bot import menu_answer
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendMessage
    from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
    method=SendMessage(chat_id=1,text='Menu')
    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='X',callback_data='x',style='primary',icon_custom_emoji_id='123456')]])
    send=AsyncMock(side_effect=[TelegramBadRequest(method=method,message='custom emoji not allowed'),True])
    assert await menu_answer(send,'Menu',reply_markup=markup)
    assert send.await_args_list[-1].kwargs['reply_markup'].inline_keyboard[0][0].icon_custom_emoji_id is None
    send=AsyncMock(side_effect=TelegramBadRequest(method=method,message='chat not found'))
    with pytest.raises(TelegramBadRequest):await menu_answer(send,'Menu',reply_markup=markup)
    assert send.await_count==1

@pytest.mark.asyncio
async def test_emoji_fetch_is_allowlisted_static_bounded_and_token_private(database,monkeypatch,tmp_path):
    import io,httpx
    from PIL import Image
    from app.config import settings
    tree._emoji_cache.clear();tree._emoji_locks.clear()
    monkeypatch.setattr(settings,'bot_token','secret-menu-token');monkeypatch.setattr(settings,'media_dir',str(tmp_path))
    database.add(BotMenuItem(title='Emoji',action='',item_type='folder',icon_custom_emoji_id='123456'));await database.commit()
    content=io.BytesIO();Image.new('RGB',(24,24)).save(content,format='PNG')
    calls=[]
    def responder(request):
        calls.append(request)
        if request.url.path.endswith('getCustomEmojiStickers'):return httpx.Response(200,json={'ok':True,'result':[{'custom_emoji_id':'123456','is_animated':True,'thumbnail':{'file_id':'thumb'}}]})
        if request.url.path.endswith('getFile'):return httpx.Response(200,json={'ok':True,'result':{'file_path':'stickers/preview.png'}})
        return httpx.Response(200,content=content.getvalue())
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(responder),**kwargs))
    with pytest.raises(HTTPException) as e:await tree.menu_emoji('999999',database)
    assert e.value.status_code==404 and calls==[]
    result=await tree.menu_emoji('123456',database)
    assert result['url'].startswith('/media/menu-emoji-') and 'secret' not in json.dumps(result)
    assert len(calls)==3
    await tree.menu_emoji('123456',database);assert len(calls)==3
    assert (tmp_path/result['url'].split('/')[-1]).is_file()
    tree._emoji_cache.clear()
    def invalid(request):
        if request.url.path.endswith('getCustomEmojiStickers'):return responder(request)
        return httpx.Response(200,json={'ok':True,'result':{'file_path':'../token-leak'}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(invalid),**kwargs))
    with pytest.raises(HTTPException) as e:await tree.menu_emoji('123456',database)
    assert e.value.status_code==502 and 'secret' not in str(e.value.detail)

@pytest.mark.asyncio
async def test_postgres_concurrent_folder_moves_cannot_create_cycle(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL transaction locks run in CI')
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    a=await shop.admin_menu(shop.MenuIn(title='A',item_type='folder'),database,ADMIN)
    b=await shop.admin_menu(shop.MenuIn(title='B',item_type='folder'),database,ADMIN)
    async def move(node,parent):
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            try:
                await shop.admin_menu_update(node,shop.MenuIn(title='Moved',item_type='folder',parent_id=parent),db,ADMIN)
                return 200
            except HTTPException as exc:return exc.status_code
    assert sorted(await asyncio.gather(move(a['id'],b['id']),move(b['id'],a['id'])))==[200,409]

@pytest.mark.asyncio
async def test_postgres_menu_migration_guard_and_roundtrip(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL migrations run in CI')
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    spec=importlib.util.spec_from_file_location('menu_migration',Path('services/backend/alembic/versions/0061_menu_hierarchy.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    database.add(BotMenuItem(title='Legacy',action='https://example.com',item_type='url'));await database.commit()
    async with database.bind.begin() as conn:
        def run(connection):
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade();migration.upgrade()
        await conn.run_sync(run)
    database.expire_all();row=await database.scalar(select(BotMenuItem));assert row.style=='default' and row.parent_id is None
    row.style='primary';await database.commit()
    with pytest.raises(RuntimeError,match='prevent downgrade'):
        async with database.bind.begin() as conn:
            def refuse(connection):
                with Operations.context(MigrationContext.configure(connection)):migration.downgrade()
            await conn.run_sync(refuse)

@pytest.mark.asyncio
async def test_postgres_mini_tree_alone_blocks_menu_downgrade(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL migration run in CI')
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    spec=importlib.util.spec_from_file_location('menu_migration',Path('services/backend/alembic/versions/0061_menu_hierarchy.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    database.add(AppSetting(key='miniapp_buttons',value=json.dumps([{'id':'folder','type':'folder','title':'Keep'}])));await database.commit()
    with pytest.raises(RuntimeError,match='Mini App tree/styles prevent downgrade'):
        async with database.bind.begin() as conn:
            def refuse(connection):
                with Operations.context(MigrationContext.configure(connection)):migration.downgrade()
            await conn.run_sync(refuse)

@pytest.mark.asyncio
async def test_bot_callback_rechecks_disabled_ancestors_and_private_chat(monkeypatch):
    from app import bot
    root=SimpleNamespace(id=1,parent_id=None,enabled=False,item_type='folder',title='Disabled')
    leaf=SimpleNamespace(id=2,parent_id=1,enabled=True,item_type='field',action='help',title='Help',sort_order=0)
    field=SimpleNamespace(key='help',enabled=True,label='Label',value='SECRET')
    monkeypatch.setattr(bot,'get_bot_config',AsyncMock(return_value=({},[root,leaf],[field],None)))
    send=AsyncMock();answer=AsyncMock()
    query=SimpleNamespace(data='menu-field:2',from_user=SimpleNamespace(id=10),message=SimpleNamespace(chat=SimpleNamespace(type='private',id=10),answer=send),answer=answer)
    await bot.menu_callback(query);assert send.await_count==0
    root.enabled=True;query.message.chat.type='group';await bot.menu_callback(query);assert send.await_count==0
    query.message.chat.type='private';query.message.chat.id=11;await bot.menu_callback(query);assert send.await_count==0
    query.message.chat.id=10;await bot.menu_callback(query);assert send.await_count==1
    assert 'SECRET' in send.await_args.args[0]
