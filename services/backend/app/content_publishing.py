"""Versioned, structured public pages. Drafts and audit metadata stay private."""
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AuditLog, ContentPage, ContentRevision
from .security import require_permission


def private(response: Response): response.headers['Cache-Control'] = 'private, no-store'
admin_router = APIRouter(prefix='/api/admin/pages', dependencies=[Depends(private), Depends(require_permission('manage_content'))])
public_router = APIRouter(prefix='/api/public/pages', dependencies=[Depends(private)])


class Item(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2000)


class Block(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['hero', 'text', 'cta', 'features', 'faq']
    title: str = Field(default='', max_length=200)
    text: str = Field(default='', max_length=10000)
    label: str = Field(default='', max_length=100)
    url: str = Field(default='', max_length=2048)
    items: list[Item] = Field(default_factory=list, max_length=20)

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        if not value: return value
        if any(c.isspace() or ord(c)<32 or c=='\\' for c in value): raise ValueError('Некорректная ссылка')
        if value.startswith('#') or value.startswith('/') and not value.startswith('//'): return value
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password: raise ValueError('Ссылка должна использовать HTTPS или путь внутри магазина')
        return value

    @model_validator(mode='after')
    def required_content(self):
        if self.kind=='cta' and not (self.label.strip() and self.url): raise ValueError('Кнопке нужны подпись и ссылка')
        if self.kind in ('features','faq') and not self.items: raise ValueError('Добавьте элементы блока')
        if self.kind in ('hero','text') and not (self.title.strip() or self.text.strip()): raise ValueError('Пустой текстовый блок')
        return self


class PageIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    slug: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,79}$')
    locale: Literal['ru','en'] = 'ru'
    kind: Literal['news','landing','legal']
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default='', max_length=1000)
    blocks: list[Block] = Field(min_length=1, max_length=30)
    starts_at: datetime|None = None
    ends_at: datetime|None = None

    @field_validator('title')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Заголовок не может быть пустым')
        return value

    @field_validator('starts_at','ends_at')
    @classmethod
    def utc_time(cls,value):
        if value is not None:
            from datetime import timezone
            if value.tzinfo is None: raise ValueError('Укажите часовой пояс расписания')
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode='after')
    def window(self):
        if self.ends_at and self.starts_at and self.ends_at<=self.starts_at: raise ValueError('Конец публикации должен быть позже начала')
        size=sum(len(str(x).encode('utf-8')) for x in (self.title,self.summary,*[b.model_dump_json() for b in self.blocks]))
        if size>128*1024: raise ValueError('Содержимое страницы превышает 128 КиБ')
        return self


class SaveIn(PageIn):
    version: int = Field(ge=1)


class VersionIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version: int = Field(ge=1)


class RestoreIn(VersionIn):
    revision: int = Field(ge=1)


def payload(body):
    data=body.model_dump(mode='json', exclude={'version'})
    # Store timestamps as explicit UTC even after validation converts DB times to naive UTC.
    for key in ('starts_at','ends_at'):
        if data[key]: data[key]+='Z'
    return data


def record(page):
    base=settings.cabinet_url.rstrip('/')
    parsed=urlsplit(base)
    public_url=base+'/#page/'+page.slug if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password else None
    return {'public_url':public_url,'id':page.id,'version':page.version,'draft':page.draft,'published_revision':page.published_revision,
        'archived':page.archived,'created_at':page.created_at,'updated_at':page.updated_at}


async def current(db,page_id,version=None):
    page=await db.scalar(select(ContentPage).where(ContentPage.id==page_id).execution_options(populate_existing=True).with_for_update())
    if not page: raise HTTPException(404,'Страница не найдена')
    if version is not None and page.version!=version: raise HTTPException(409,'Страница изменена. Загрузите актуальную версию')
    return page


async def change(db,page,values,action,admin):
    old=page.version
    values.update(version=old+1,updated_at=datetime.utcnow())
    result=await db.execute(update(ContentPage).where(ContentPage.id==page.id,ContentPage.version==old).values(**values).execution_options(synchronize_session=False))
    if result.rowcount!=1: raise HTTPException(409,'Страница изменена. Загрузите актуальную версию')
    db.add(AuditLog(actor=admin.email,action='content.'+action,target=str(page.id),details=str(old+1)))
    await db.flush(); await db.refresh(page)
    return page


@admin_router.get('')
async def pages(offset:int=Query(0,ge=0), limit:int=Query(50,ge=1,le=100), db:AsyncSession=Depends(get_db)):
    return [record(p) for p in (await db.scalars(select(ContentPage).order_by(ContentPage.id.desc()).offset(offset).limit(limit))).all()]


@admin_router.post('')
async def create(body:PageIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_content'))):
    page=ContentPage(slug=body.slug,locale=body.locale,kind=body.kind,draft=payload(body))
    db.add(page)
    try:
        await db.flush();db.add(AuditLog(actor=admin.email,action='content.created',target=str(page.id)));await db.commit()
    except IntegrityError:
        await db.rollback();raise HTTPException(409,'Slug уже существует для этого языка')
    return record(page)


@admin_router.get('/{page_id}')
async def get(page_id:int,db:AsyncSession=Depends(get_db)):
    return record(await current(db,page_id))


@admin_router.put('/{page_id}')
async def save(page_id:int,body:SaveIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_content'))):
    page=await current(db,page_id,body.version)
    if (body.slug,body.locale,body.kind)!=(page.slug,page.locale,page.kind): raise HTTPException(409,'Slug, язык и тип неизменяемы; создайте другую страницу')
    await change(db,page,{'draft':payload(body)},'saved',admin);await db.commit();return record(page)


@admin_router.post('/{page_id}/publish')
async def publish(page_id:int,body:VersionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_content'))):
    page=await current(db,page_id,body.version)
    data=PageIn.model_validate(page.draft)
    if data.ends_at and data.ends_at<=datetime.utcnow(): raise HTTPException(409,'Расписание уже завершилось')
    revision=page.version+1
    db.add(ContentRevision(page_id=page.id,version=revision,snapshot=page.draft,actor=admin.email,starts_at=data.starts_at,ends_at=data.ends_at))
    await change(db,page,{'published_revision':revision,'archived':False},'published',admin)
    await db.commit();return record(page)


@admin_router.post('/{page_id}/archive')
async def archive(page_id:int,body:VersionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_content'))):
    page=await current(db,page_id,body.version);await change(db,page,{'archived':True},'archived',admin)
    await db.commit();return record(page)


@admin_router.get('/{page_id}/revisions')
async def revisions(page_id:int,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:AsyncSession=Depends(get_db)):
    await current(db,page_id)
    return [{'version':r.version,'snapshot':r.snapshot,'actor':r.actor,'created_at':r.created_at} for r in
        (await db.scalars(select(ContentRevision).where(ContentRevision.page_id==page_id).order_by(ContentRevision.version.desc()).offset(offset).limit(limit))).all()]


@admin_router.post('/{page_id}/restore')
async def restore(page_id:int,body:RestoreIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_content'))):
    page=await current(db,page_id,body.version)
    revision=await db.scalar(select(ContentRevision).where(ContentRevision.page_id==page_id,ContentRevision.version==body.revision))
    if not revision: raise HTTPException(404,'Ревизия не найдена')
    await change(db,page,{'draft':revision.snapshot},'restored',admin);await db.commit();return record(page)


def visible_query():
    return select(ContentPage,ContentRevision).join(ContentRevision,(ContentRevision.page_id==ContentPage.id)&(ContentRevision.version==ContentPage.published_revision)).where(ContentPage.archived==False)


def visible(revision):
    now=datetime.utcnow();data=PageIn.model_validate(revision.snapshot)
    return (not data.starts_at or data.starts_at<=now) and (not data.ends_at or data.ends_at>now)


@public_router.get('')
async def catalog(locale:Literal['ru','en']='ru',kind:Literal['news','landing','legal']|None=None,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:AsyncSession=Depends(get_db)):
    query=visible_query().where(ContentPage.locale==locale)
    if kind:query=query.where(ContentPage.kind==kind)
    # SQL window filtering uses dedicated immutable publication timestamp columns.
    now=datetime.utcnow()
    query=query.where((ContentRevision.starts_at==None)|(ContentRevision.starts_at<=now),(ContentRevision.ends_at==None)|(ContentRevision.ends_at>now))
    return [{'slug':p.slug,'locale':p.locale,'kind':p.kind,'title':r.snapshot['title'],'summary':r.snapshot['summary'],'revision':r.version,'published_at':r.created_at} for p,r in
        (await db.execute(query.order_by(ContentRevision.created_at.desc(),ContentPage.id.desc()).offset(offset).limit(limit))).all()]


@public_router.get('/{slug}')
async def public_page(slug:str,locale:Literal['ru','en']='ru',db:AsyncSession=Depends(get_db)):
    row=(await db.execute(visible_query().where(ContentPage.slug==slug,ContentPage.locale==locale))).first()
    if not row or not visible(row[1]): raise HTTPException(404,'Страница не опубликована')
    p,r=row
    return {**r.snapshot,'revision':r.version,'published_at':r.created_at}
