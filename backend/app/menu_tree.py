"""Bounded menu trees with Telegram button styles and custom emoji metadata."""
import secrets
import logging
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from fastapi import HTTPException
from sqlalchemy import select,text
from .models import BotMenuItem

MAX_ITEMS=30
MAX_DEPTH=4
Style=Literal['default','primary','success','danger']
logger = logging.getLogger(__name__)


async def lock_menu(db):
    if db.bind.dialect.name=='postgresql':await db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':1300000091})


async def validate_bot_tree(db,payload,item_id=None):
    rows=(await db.scalars(select(BotMenuItem).execution_options(populate_existing=True))).all()
    by_id={row.id:row for row in rows}
    if item_id is None and len(rows)>=MAX_ITEMS:raise HTTPException(400,'Не более 30 кнопок')
    if payload.item_type!='folder' and any(row.parent_id==item_id for row in rows if item_id is not None):raise HTTPException(409,'Сначала перенесите дочерние кнопки')
    parent=payload.parent_id;visited={item_id} if item_id else set();depth=1
    while parent is not None:
        if parent in visited:raise HTTPException(409,'Цикл в дереве меню')
        visited.add(parent);row=by_id.get(parent)
        if not row or row.item_type!='folder':raise HTTPException(409,'Родитель должен быть существующей папкой')
        parent=row.parent_id;depth+=1
        if depth>MAX_DEPTH:raise HTTPException(400,'Максимум четыре уровня меню')
    # Moving a folder must preserve the depth of its entire subtree.
    def height(identifier,trail):
        if identifier in trail:raise HTTPException(409,'Цикл в дереве меню')
        children=[row.id for row in rows if row.parent_id==identifier]
        return 1+max((height(child,trail|{identifier}) for child in children),default=0)
    if item_id is not None and depth+height(item_id,set())-1>MAX_DEPTH:raise HTTPException(400,'Перенос превышает четыре уровня меню')


class MiniButton(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(default_factory=lambda:secrets.token_hex(8),pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    title:str=Field(min_length=1,max_length=100)
    type:Literal['url','plans','promo','field','folder']
    style:Style='default'
    icon_custom_emoji_id:str|None=Field(default=None,pattern=r'^[0-9]{5,32}$')
    icon:str=Field(default='',max_length=16)
    url:str=Field(default='',max_length=2048)
    code:str=Field(default='',max_length=64)
    field_key:str=Field(default='',max_length=100)
    children:list['MiniButton']=Field(default_factory=list,max_length=30)

    @model_validator(mode='after')
    def shape(self):
        if not self.title.strip():raise ValueError('Название кнопки не может быть пустым')
        if self.children and self.type!='folder':raise ValueError('Дочерние кнопки допускаются только у папки')
        return self


def normalize_mini_buttons(buttons,field_keys):
    from .main import validate_public_url
    from pydantic import ValidationError
    try:roots=[MiniButton.model_validate(b) for b in buttons]
    except ValidationError:raise HTTPException(400,'Некорректные поля/стиль/emoji кнопки')
    seen=set();count=0
    def visit(node,depth):
        nonlocal count
        count+=1
        if count>MAX_ITEMS or depth>MAX_DEPTH:raise HTTPException(400,'Не более 30 кнопок и четырёх уровней')
        if node.id in seen:raise HTTPException(400,'ID кнопки должен быть уникальным')
        seen.add(node.id)
        if node.type=='url':validate_public_url(node.url,allow_empty=False)
        if node.type=='promo' and not node.code.strip():raise HTTPException(400,'Для промокода нужен код')
        if node.type=='field' and node.field_key not in field_keys:raise HTTPException(400,'Поле не существует или отключено')
        for child in node.children:visit(child,depth+1)
    for root in roots:visit(root,1)
    return [node.model_dump() for node in roots]


def visible_children(rows,parent_id=None):
    by_id={row.id:row for row in rows}
    if parent_id is not None:
        current=parent_id;seen=set()
        while current is not None:
            if current in seen:return []
            seen.add(current);parent=by_id.get(current)
            if not parent or not parent.enabled or parent.item_type!='folder':return []
            current=parent.parent_id
    return sorted([row for row in rows if row.enabled and row.parent_id==parent_id],key=lambda row:(row.sort_order,row.id))


def telegram_keyboard(rows,fields,parent_id=None):
    from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,WebAppInfo
    from .config import settings
    buttons=[]
    for row in visible_children(rows,parent_id):
        common={'text':(row.icon+' ' if row.icon and not row.icon_custom_emoji_id else '')+row.title,'style':row.style if row.style!='default' else None,'icon_custom_emoji_id':row.icon_custom_emoji_id}
        if row.item_type=='folder':button=InlineKeyboardButton(**common,callback_data=f'menu:{row.id}')
        elif row.item_type=='field':
            if not any(field.key==row.action and field.enabled for field in fields):continue
            button=InlineKeyboardButton(**common,callback_data=f'menu-field:{row.id}')
        elif row.item_type=='url' and row.action.startswith('https://'):button=InlineKeyboardButton(**common,url=row.action)
        elif row.item_type=='webapp' and (row.action or settings.mini_app_url).startswith('https://'):button=InlineKeyboardButton(**common,web_app=WebAppInfo(url=row.action or settings.mini_app_url))
        else:continue
        buttons.append([button])
    if parent_id is not None:
        row=next((row for row in rows if row.id==parent_id),None)
        buttons.append([InlineKeyboardButton(text='←',callback_data=f'menu:{row.parent_id if row and row.parent_id else 0}')])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def without_custom_icons(markup):
    from aiogram.types import InlineKeyboardMarkup
    data=markup.model_dump(exclude_none=True)
    for line in data['inline_keyboard']:
        for button in line:button.pop('icon_custom_emoji_id',None)
    return InlineKeyboardMarkup.model_validate(data)


# Telegram IDs are resolved server-side; the bot token never reaches the browser.
from fastapi import APIRouter,Path,Depends
from .db import get_db
from .security import require_permission
from sqlalchemy.ext.asyncio import AsyncSession
emoji_router=APIRouter()
_emoji_cache={}
_emoji_locks={}


@emoji_router.get('/api/public/menu-emoji/{emoji_id}')
async def menu_emoji(emoji_id:str=Path(pattern=r'^[0-9]{5,32}$'),db:AsyncSession=Depends(get_db)):
    import asyncio,json,time,hashlib,io,re
    import pathlib
    import httpx
    from PIL import Image
    from .config import settings
    from .models import AppSetting
    ids=set((await db.scalars(select(BotMenuItem.icon_custom_emoji_id).where(BotMenuItem.enabled==True,BotMenuItem.icon_custom_emoji_id.is_not(None)))).all())
    setting=await db.get(AppSetting,'miniapp_buttons')
    def collect(nodes,depth=0):
        if depth>4 or not isinstance(nodes,list):return
        for node in nodes[:30]:
            if not isinstance(node,dict):continue
            if isinstance(node.get('icon_custom_emoji_id'),str):ids.add(node['icon_custom_emoji_id'])
            if isinstance(node.get('children'),list):collect(node['children'],depth+1)
    try:collect(json.loads(setting.value) if setting else [])
    except (ValueError,TypeError) as exc:
        logger.warning('Configured menu tree is invalid while resolving custom emoji: %s', exc)
    if emoji_id not in ids:raise HTTPException(404,'Emoji не настроен в меню')
    if not settings.bot_token:raise HTTPException(503,'Бот не настроен')
    if len(_emoji_locks)>=64 and emoji_id not in _emoji_locks:_emoji_locks.clear()
    lock=_emoji_locks.setdefault(emoji_id,asyncio.Lock())
    async with lock:
        cached=_emoji_cache.get(emoji_id)
        if cached and cached[0]>time.monotonic():
            if not cached[1]:raise HTTPException(502,'Emoji временно недоступен')
            if pathlib.Path(settings.media_dir,cached[1].removeprefix('/media/')).is_file():return {'url':cached[1]}
        try:
            async with httpx.AsyncClient(timeout=8,follow_redirects=False) as client:
                response=await client.post(f'https://api.telegram.org/bot{settings.bot_token}/getCustomEmojiStickers',json={'custom_emoji_ids':[emoji_id]})
                response.raise_for_status();data=response.json()
                stickers=data.get('result') if data.get('ok') else None
                if not isinstance(stickers,list) or len(stickers)!=1 or stickers[0].get('custom_emoji_id')!=emoji_id:raise ValueError('Unexpected sticker')
                sticker=stickers[0];thumbnail=sticker.get('thumbnail') or {}
                file_id=thumbnail.get('file_id') or (sticker.get('file_id') if not sticker.get('is_animated') and not sticker.get('is_video') else None)
                if not isinstance(file_id,str):raise ValueError('No supported preview')
                response=await client.post(f'https://api.telegram.org/bot{settings.bot_token}/getFile',json={'file_id':file_id})
                response.raise_for_status();data=response.json();file_path=(data.get('result') or {}).get('file_path') if data.get('ok') else None
                if not isinstance(file_path,str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,300}',file_path) or '..' in file_path or file_path.startswith('/'):raise ValueError('Invalid file path')
                chunks=[];size=0
                async with client.stream('GET',f'https://api.telegram.org/file/bot{settings.bot_token}/{file_path}') as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>512*1024:raise ValueError('Preview too large')
                        chunks.append(chunk)
            with Image.open(io.BytesIO(b''.join(chunks))) as image:
                if image.format not in ('PNG','JPEG','WEBP') or max(image.size)>512:raise ValueError('Unsupported image')
                output=io.BytesIO();image.convert('RGBA').save(output,format='PNG');content=output.getvalue()
            filename='menu-emoji-'+hashlib.sha256(content).hexdigest()[:24]+'.png'
            directory=pathlib.Path(settings.media_dir);directory.mkdir(parents=True,exist_ok=True);(directory/filename).write_bytes(content)
            url='/media/'+filename
            if len(_emoji_cache)>=64:_emoji_cache.clear()
            _emoji_cache[emoji_id]=(time.monotonic()+3600,url)
            return {'url':url}
        except Exception:
            _emoji_cache[emoji_id]=(time.monotonic()+60,None)
            raise HTTPException(502,'Emoji временно недоступен; используется обычная иконка')


class MiniTreeIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    buttons:list[dict]=Field(max_length=30)
    fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')


@emoji_router.put('/api/admin/miniapp/menu')
async def save_mini_tree(body:MiniTreeIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_content'))):
    import hashlib,json
    from .models import AppSetting,CustomField,AuditLog
    await lock_menu(db)
    row=await db.scalar(select(AppSetting).where(AppSetting.key=='miniapp_buttons').execution_options(populate_existing=True))
    if hashlib.sha256((row.value if row else '[]').encode()).hexdigest()!=body.fingerprint:raise HTTPException(409,'Меню приложения изменено; загрузите актуальную версию')
    keys=set((await db.scalars(select(CustomField.key).where(CustomField.enabled==True))).all())
    buttons=normalize_mini_buttons(body.buttons,keys);raw=json.dumps(buttons,ensure_ascii=False)
    if row:row.value=raw
    else:db.add(AppSetting(key='miniapp_buttons',value=raw))
    db.add(AuditLog(actor=admin.email,action='content.miniapp.menu.saved'));await db.commit()
    return {'buttons':buttons,'fingerprint':hashlib.sha256(raw.encode()).hexdigest()}
