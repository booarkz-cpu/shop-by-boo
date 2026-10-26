"""Admin content / branding: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ---------- Admin content / branding ----------

class _PinnedPublicDNSBackend:
    """httpcore backend that resolves hostnames immediately before each new TCP connection.

    The resolved IP is then passed as a literal to the underlying socket connector while
    httpcore keeps the original hostname for TLS SNI/certificate verification. This closes
    the validation-vs-use DNS rebinding window: the connection cannot perform a second DNS
    lookup after the public-IP check.
    """
    def __init__(self):
        import httpcore
        self._backend=httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        import httpcore
        try:
            literal=shop.ipaddress.ip_address(host)
            if literal.is_private or not literal.is_global:
                raise OSError("destination is not a globally routable IP")
            target=str(literal)
        except ValueError:
            try:
                infos=shop.socket.getaddrinfo(host,port,type=shop.socket.SOCK_STREAM)
            except OSError as exc:
                raise OSError(f"DNS resolution failed: {exc}") from exc
            addresses=[]
            for info in infos:
                addr=info[4][0].split("%",1)[0]
                try: ip=shop.ipaddress.ip_address(addr)
                except ValueError: continue
                if ip.is_private or not ip.is_global:
                    raise OSError("hostname resolved to a non-public address")
                if str(ip) not in addresses:
                    addresses.append(str(ip))
            if not addresses:
                raise OSError("hostname has no globally routable address")
            target=addresses[0]
        return await self._backend.connect_tcp(target,port,timeout,local_address,socket_options)


def _pinned_public_http_client(timeout_seconds:int):
    import httpx
    transport=httpx.AsyncHTTPTransport(retries=0,trust_env=False)
    # httpx exposes the httpcore pool internally; using its documented network-backend
    # abstraction avoids a second DNS lookup while retaining the original TLS hostname.
    transport._pool._network_backend=shop._PinnedPublicDNSBackend()
    return httpx.AsyncClient(timeout=timeout_seconds,transport=transport,follow_redirects=False)


def _resolve_public_host(host:str,port:int=443)->list[str]:
    try:
        literal=shop.ipaddress.ip_address(host)
        if literal.is_private or not literal.is_global:
            raise shop.HTTPException(400,"Private or local monitoring targets are not allowed")
        return [str(literal)]
    except ValueError:
        try:
            infos=shop.socket.getaddrinfo(host,port,type=shop.socket.SOCK_STREAM)
        except OSError:
            raise shop.HTTPException(400,"Monitoring hostname cannot be resolved")
        addresses=[]
        for info in infos:
            addr=info[4][0].split("%",1)[0]
            try: ip=shop.ipaddress.ip_address(addr)
            except ValueError: continue
            if ip.is_private or not ip.is_global:
                raise shop.HTTPException(400,"Monitoring hostname resolves to a private or local address")
            if str(ip) not in addresses: addresses.append(str(ip))
        if not addresses:
            raise shop.HTTPException(400,"Monitoring hostname has no public address")
        return addresses

def validate_public_url(value: str|None, *, allow_empty: bool=True) -> str|None:
    if value is None or value=="":
        if allow_empty: return value
        raise shop.HTTPException(400,"URL is required")
    parsed=shop.urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise shop.HTTPException(400,"Only absolute HTTPS URLs are allowed")
    host=parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"} or host.endswith(".localhost"):
        raise shop.HTTPException(400,"Private or local monitoring targets are not allowed")
    try:
        port=parsed.port or 443
    except ValueError:
        raise shop.HTTPException(400,"Invalid URL port")
    if not 1 <= port <= 65535:
        raise shop.HTTPException(400,"Invalid URL port")
    shop._resolve_public_host(host, port)
    return value

class SettingIn(BaseModel): value:str=Field(max_length=100000)
class MenuIn(BaseModel):
    title:str=Field(min_length=1,max_length=255)
    action:str=Field(default="",min_length=0,max_length=255)
    item_type:str=Field(default="webapp",pattern="^(webapp|url|field|folder|info)$")
    sort_order:int=Field(default=0,ge=-100000,le=100000)
    enabled:bool=True
    parent_id:int|None=Field(default=None,gt=0)
    style:str=Field(default='default',pattern='^(default|primary|success|danger)$')
    icon_custom_emoji_id:str|None=Field(default=None,pattern=r'^[0-9]{5,32}$')
    icon:str=Field(default='',max_length=16)
class FieldIn(BaseModel): key:str=Field(min_length=1,max_length=100,pattern=r"^[A-Za-z0-9_.-]+$"); label:str=Field(min_length=1,max_length=255); field_type:str=Field(default="text",pattern="^(text|url|number)$"); value:str=Field(default="",max_length=10000); enabled:bool=True; sort_order:int=Field(default=0,ge=-100000,le=100000)

BRANDING_KEYS = {"app_name", "app_logo", "app_favicon", "theme_default"}

@shop.app.get("/api/public/branding")
async def public_branding(db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(shop.select(shop.AppSetting).where(shop.AppSetting.key.in_(shop.BRANDING_KEYS)))).scalars().all()
    values={x.key:x.value for x in rows}
    return {
        "name": values.get("app_name") or "Корги Люси",
        "logo_url": values.get("app_logo") or "",
        "favicon_url": values.get("app_favicon") or "",
        "theme_default": values.get("theme_default") if values.get("theme_default") in {"light","dark"} else "dark",
    }

@shop.app.get("/api/admin/content")
async def admin_content(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    # Never expose the raw AppSetting table to the browser: it contains encrypted
    # staging/payment/backup secrets. Return only content settings and booleans.
    safe_keys={"app_name","app_logo","app_favicon","theme_default","bot_name","miniapp_title","miniapp_subtitle","miniapp_background_color","miniapp_background_image","miniapp_image","miniapp_instructions","miniapp_buttons","bot_start_image"}
    secret_keys={"yookassa_shop_id","yookassa_secret_key","platega_merchant_id","platega_secret","rollypay_api_key","rollypay_signing_secret","backup_password","staging_e2e.config"}
    ss=(await db.execute(shop.select(shop.AppSetting).where(shop.AppSetting.key.in_(safe_keys|secret_keys)))).scalars().all()
    setting_values={x.key:x.value for x in ss if x.key in safe_keys}
    mini_buttons_fingerprint=shop.hashlib.sha256(setting_values.get("miniapp_buttons","[]").encode()).hexdigest()
    try: setting_values["miniapp_buttons"]=shop.json.loads(setting_values.get("miniapp_buttons","[]"))
    except Exception: setting_values["miniapp_buttons"]=[]
    secret_status={x.key:bool(x.value) for x in ss if x.key in secret_keys}
    mm=(await db.execute(shop.select(shop.BotMenuItem).order_by(shop.BotMenuItem.sort_order,shop.BotMenuItem.id))).scalars().all(); ff=(await db.execute(shop.select(shop.CustomField).order_by(shop.CustomField.sort_order,shop.CustomField.id))).scalars().all(); ii=(await db.execute(shop.select(shop.MenuImage).order_by(shop.MenuImage.sort_order,shop.MenuImage.id))).scalars().all()
    return {"miniapp_buttons_fingerprint":mini_buttons_fingerprint,"settings":setting_values,"secret_status":secret_status,"menu":[{"id":x.id,"title":x.title,"action":x.action,"item_type":x.item_type,"sort_order":x.sort_order,"enabled":x.enabled,"parent_id":x.parent_id,"style":x.style,"icon_custom_emoji_id":x.icon_custom_emoji_id,"icon":x.icon} for x in mm],"fields":[{"id":x.id,"key":x.key,"label":x.label,"field_type":x.field_type,"value":x.value,"enabled":x.enabled,"sort_order":x.sort_order} for x in ff],"images":[{"id":x.id,"title":x.title,"url":"/media/"+x.filename,"sort_order":x.sort_order,"enabled":x.enabled} for x in ii]}

@shop.app.put("/api/admin/settings/{key}")
async def admin_setting(key:str,payload:SettingIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    # Content managers may only modify explicitly public branding keys. Security,
    # payment, staging and backup settings are intentionally not writable here.
    if key not in {"app_name","bot_name","theme_default"}: raise shop.HTTPException(403,"Настройка недоступна для управления контентом")
    if key=="app_name" and (not payload.value.strip() or len(payload.value.strip())>255): raise shop.HTTPException(400,"Название панели должно содержать от 1 до 255 символов")
    if key=="theme_default" and payload.value not in {"light","dark"}: raise shop.HTTPException(400,"theme_default должен быть light или dark")
    row=await db.get(shop.AppSetting,key);
    if not row: row=shop.AppSetting(key=key,value=payload.value); db.add(row)
    else: row.value=payload.value
    if key=="bot_name" and shop.settings.bot_token:
        import httpx
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            r=await client.post(f"https://api.telegram.org/bot{shop.settings.bot_token}/setMyName",json={"name":payload.value})
            if not r.is_success: raise shop.HTTPException(502,"Telegram rejected bot name")
    await shop.audit(db,"content.setting.updated",admin.email,key); await db.commit(); return {"ok":True}

async def _store_branding_image(file:UploadFile, kind:str, max_bytes:int=2*1024*1024) -> str:
    allowed={"image/png","image/jpeg","image/webp"}
    if file.content_type not in allowed:
        raise shop.HTTPException(400,"Разрешены только PNG, JPG и WEBP")
    data=await shop._read_upload_limited(file,max_bytes)
    try:
        from PIL import Image, ImageOps
        with Image.open(shop.BytesIO(data)) as im:
            im.verify()
        with Image.open(shop.BytesIO(data)) as im:
            im=ImageOps.exif_transpose(im).convert("RGBA")
            max_side=2048 if kind in {"logo","client-logo"} else 512
            im.thumbnail((max_side,max_side),Image.Resampling.LANCZOS)
            out=shop.BytesIO(); im.save(out,"PNG",optimize=True)
            normalized=out.getvalue()
    except Exception:
        raise shop.HTTPException(400,"Файл не является корректным изображением")
    if len(normalized)>max_bytes:
        raise shop.HTTPException(413,"Нормализованное изображение слишком большое")
    name=f"branding-{kind}-{shop.secrets.token_hex(16)}.png"
    root=shop.pathlib.Path(shop.settings.media_dir); root.mkdir(parents=True,exist_ok=True)
    (root/name).write_bytes(normalized)
    return "/media/"+name

async def _replace_branding_file(db:AsyncSession,key:str,new_url:str):
    row=await db.get(shop.AppSetting,key); old=row.value if row else ""
    if row: row.value=new_url
    else: db.add(shop.AppSetting(key=key,value=new_url))
    if old.startswith("/media/"):
        old_name=shop.pathlib.Path(old.removeprefix("/media/")).name
        try: shop.pathlib.Path(shop.settings.media_dir,old_name).unlink(missing_ok=True)
        except Exception as exc: shop.logger.warning("Unable to remove old branding asset: %s",exc)

@shop.app.post("/api/admin/branding/logo")
async def admin_branding_logo(file:UploadFile=File(...),db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    url=await shop._store_branding_image(file,"logo")
    await shop._replace_branding_file(db,"app_logo",url); await shop.audit(db,"content.branding.logo.updated",admin.email); await db.commit()
    return {"ok":True,"url":url}

@shop.app.post("/api/admin/branding/favicon")
async def admin_branding_favicon(file:UploadFile=File(...),db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    url=await shop._store_branding_image(file,"favicon",512*1024)
    await shop._replace_branding_file(db,"app_favicon",url); await shop.audit(db,"content.branding.favicon.updated",admin.email); await db.commit()
    return {"ok":True,"url":url}

@shop.app.delete("/api/admin/branding/{kind}")
async def admin_branding_delete(kind:str,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    key={"logo":"app_logo","favicon":"app_favicon"}.get(kind)
    if not key: raise shop.HTTPException(404,"Branding asset not found")
    row=await db.get(shop.AppSetting,key)
    if row and row.value.startswith("/media/"):
        name=shop.pathlib.Path(row.value.removeprefix("/media/")).name
        try: shop.pathlib.Path(shop.settings.media_dir,name).unlink(missing_ok=True)
        except Exception as exc: shop.logger.warning("Unable to remove branding asset: %s",exc)
        row.value=""
    await shop.audit(db,f"content.branding.{kind}.deleted",admin.email); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/bot/start-image")
async def admin_bot_start_image(file:UploadFile=File(...),db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    allowed={"image/jpeg","image/png","image/webp"}
    if file.content_type not in allowed: raise shop.HTTPException(400,"Разрешены JPG, PNG и WEBP")
    data=await file.read(5*1024*1024+1)
    if len(data)>5*1024*1024: raise shop.HTTPException(413,"Изображение слишком большое (5 МБ)")
    if not shop._valid_image_signature(data,file.content_type): raise shop.HTTPException(400,"Некорректное содержимое изображения")
    ext={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[file.content_type]
    shop.pathlib.Path(shop.settings.media_dir).mkdir(parents=True,exist_ok=True)
    name="bot-start-"+shop.secrets.token_hex(16)+ext
    shop.pathlib.Path(shop.settings.media_dir,name).write_bytes(data)
    row=await db.get(shop.AppSetting,"bot_start_image")
    new_url="/media/"+name
    if row: old=row.value; row.value=new_url
    else: db.add(shop.AppSetting(key="bot_start_image",value=new_url)); old=""
    if old.startswith("/media/"):
        try: shop.pathlib.Path(shop.settings.media_dir, shop.pathlib.Path(old.removeprefix("/media/")).name).unlink(missing_ok=True)
        except Exception as exc: shop.logger.warning("Unable to remove old bot image: %s",exc)
    await shop.audit(db,"content.bot.start_image.updated",admin.email)
    await db.commit()
    return {"ok":True,"url":new_url}

@shop.app.delete("/api/admin/bot/start-image")
async def admin_bot_start_image_delete(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    row=await db.get(shop.AppSetting,"bot_start_image")
    if row and row.value.startswith("/media/"):
        try: shop.pathlib.Path(shop.settings.media_dir, shop.pathlib.Path(row.value.removeprefix("/media/")).name).unlink(missing_ok=True)
        except Exception as exc: shop.logger.warning("Unable to remove bot image: %s",exc)
    if row: row.value=""
    await shop.audit(db,"content.bot.start_image.deleted",admin.email)
    await db.commit()
    return {"ok":True}

class MiniAppConfigIn(BaseModel):
    title:str=Field(default="",max_length=255)
    subtitle:str=Field(default="",max_length=1000)
    background_color:str=Field(default="#f5f7fb",max_length=32)
    instructions:str=Field(default="",max_length=20000)
    buttons:list[dict]=Field(default_factory=list)

@shop.app.put("/api/admin/miniapp/config")
async def admin_miniapp_config(payload:MiniAppConfigIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    from .menu_tree import lock_menu
    await lock_menu(db)
    import re
    if payload.background_color and not re.fullmatch(r"#[0-9a-fA-F]{6}",payload.background_color):
        raise shop.HTTPException(400,"background_color must be #RRGGBB")
    if len(payload.buttons)>30:
        raise shop.HTTPException(400,"Можно настроить не более 30 кнопок")
    field_rows=(await db.execute(shop.select(shop.CustomField.key).where(shop.CustomField.enabled.is_(True)))).scalars().all()
    field_keys=set(field_rows)
    from .menu_tree import normalize_mini_buttons
    buttons=normalize_mini_buttons(payload.buttons,field_keys)
    values={"miniapp_title":payload.title,"miniapp_subtitle":payload.subtitle,"miniapp_background_color":payload.background_color,"miniapp_instructions":payload.instructions,"miniapp_buttons":shop.json.dumps(buttons,ensure_ascii=False)}
    for key,value in values.items():
        row=await db.get(shop.AppSetting,key)
        if row: row.value=value
        else: db.add(shop.AppSetting(key=key,value=value))
    await shop.audit(db,"content.miniapp.updated",admin.email)
    await db.commit()
    return {"ok":True}

@shop.app.post("/api/admin/miniapp/image")
async def admin_miniapp_image(file:UploadFile=File(...),db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    allowed={"image/jpeg","image/png","image/webp"}
    if file.content_type not in allowed: raise shop.HTTPException(400,"Разрешены JPG, PNG и WEBP")
    data=await file.read(5*1024*1024+1)
    if len(data)>5*1024*1024: raise shop.HTTPException(413,"Изображение слишком большое (5 МБ)")
    if not shop._valid_image_signature(data,file.content_type): raise shop.HTTPException(400,"Некорректное содержимое изображения")
    ext={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[file.content_type]
    shop.pathlib.Path(shop.settings.media_dir).mkdir(parents=True,exist_ok=True)
    name="miniapp-image-"+shop.secrets.token_hex(16)+ext; shop.pathlib.Path(shop.settings.media_dir,name).write_bytes(data); new_url="/media/"+name
    row=await db.get(shop.AppSetting,"miniapp_image")
    if row: old=row.value; row.value=new_url
    else: db.add(shop.AppSetting(key="miniapp_image",value=new_url)); old=""
    if old.startswith("/media/"):
        try: shop.pathlib.Path(shop.settings.media_dir, shop.pathlib.Path(old.removeprefix("/media/")).name).unlink(missing_ok=True)
        except Exception as exc: shop.logger.warning("Unable to remove old miniapp image: %s",exc)
    await shop.audit(db,"content.miniapp.image.updated",admin.email); await db.commit(); return {"ok":True,"url":new_url}

@shop.app.delete("/api/admin/miniapp/image")
async def admin_miniapp_image_delete(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    row=await db.get(shop.AppSetting,"miniapp_image")
    if row and row.value.startswith("/media/"):
        try: shop.pathlib.Path(shop.settings.media_dir, shop.pathlib.Path(row.value.removeprefix("/media/")).name).unlink(missing_ok=True)
        except Exception as exc: shop.logger.warning("Unable to remove miniapp image: %s",exc)
    if row: row.value=""
    await shop.audit(db,"content.miniapp.image.deleted",admin.email); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/miniapp/background")
async def admin_miniapp_background(file:UploadFile=File(...),db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    if file.content_type not in {"image/jpeg","image/png","image/webp"}: raise shop.HTTPException(400,"Only JPG, PNG and WEBP are allowed")
    data=await shop._read_upload_limited(file,8*1024*1024)
    if not shop._valid_image_signature(data,file.content_type): raise shop.HTTPException(400,"Invalid image signature")
    ext={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[file.content_type]
    name="miniapp-bg-"+shop.secrets.token_hex(16)+ext
    shop.pathlib.Path(shop.settings.media_dir).mkdir(parents=True,exist_ok=True)
    shop.pathlib.Path(shop.settings.media_dir,name).write_bytes(data)
    row=await db.get(shop.AppSetting,"miniapp_background_image")
    if not row: db.add(shop.AppSetting(key="miniapp_background_image",value="/media/"+name))
    else:
        old=row.value
        row.value="/media/"+name
        if old.startswith("/media/"):
            try: shop.pathlib.Path(shop.settings.media_dir, shop.pathlib.Path(old.removeprefix("/media/")).name).unlink(missing_ok=True)
            except Exception as exc:
                shop.logger.warning("Non-critical operation failed: %s", exc)
    await shop.audit(db,"content.miniapp.background.updated",admin.email)
    await db.commit()
    return {"ok":True,"url":"/media/"+name}

@shop.app.delete("/api/admin/miniapp/background")
async def admin_miniapp_background_delete(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    row=await db.get(shop.AppSetting,"miniapp_background_image")
    if row and row.value.startswith("/media/"):
        try: shop.pathlib.Path(shop.settings.media_dir, shop.pathlib.Path(row.value.removeprefix("/media/")).name).unlink(missing_ok=True)
        except Exception as exc:
            shop.logger.warning("Non-critical operation failed: %s", exc)
    if row: row.value=""
    await db.commit()
    return {"ok":True}

@shop.app.post("/api/admin/menu",response_model=dict)
async def admin_menu(payload:MenuIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    from .menu_tree import lock_menu,validate_bot_tree
    await lock_menu(db);await validate_bot_tree(db,payload)
    if payload.item_type not in {"webapp","url","field","folder","info"} or (payload.item_type=="info" and payload.action not in {"faq","rules","privacy","offer","menu"}): raise shop.HTTPException(400,"Недопустимый тип кнопки")
    if payload.item_type=="url": shop.validate_public_url(payload.action,allow_empty=False)
    if payload.item_type=="webapp": shop.validate_public_url(payload.action or shop.settings.mini_app_url,allow_empty=False)
    if payload.item_type=="field":
        if not payload.action: raise shop.HTTPException(400,"Для кнопки поля требуется ключ поля")
        exists=await db.execute(shop.select(shop.CustomField.id).where(shop.CustomField.key==payload.action,shop.CustomField.enabled.is_(True)).limit(1))
        if exists.scalar_one_or_none() is None: raise shop.HTTPException(400,"Кнопка field ссылается на неизвестное или отключённое поле")
    existing_count=int((await db.execute(shop.select(shop.func.count()).select_from(shop.BotMenuItem))).scalar() or 0)
    if existing_count>=30: raise shop.HTTPException(400,"Можно настроить не более 30 кнопок")
    x=shop.BotMenuItem(**payload.model_dump()); db.add(x); await shop.audit(db,"content.menu.created",admin.email); await db.commit(); await db.refresh(x); return {"id":x.id}

@shop.app.put("/api/admin/menu/{item_id}")
async def admin_menu_update(item_id:int,payload:MenuIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    from .menu_tree import lock_menu,validate_bot_tree
    await lock_menu(db);await validate_bot_tree(db,payload,item_id)
    x=await db.get(shop.BotMenuItem,item_id);
    if not x: raise shop.HTTPException(404,"Menu item not found")
    if payload.item_type not in {"webapp","url","field","folder","info"} or (payload.item_type=="info" and payload.action not in {"faq","rules","privacy","offer","menu"}): raise shop.HTTPException(400,"Недопустимый тип кнопки")
    if payload.item_type=="url": shop.validate_public_url(payload.action,allow_empty=False)
    if payload.item_type=="webapp": shop.validate_public_url(payload.action or shop.settings.mini_app_url,allow_empty=False)
    if payload.item_type=="field":
        if not payload.action: raise shop.HTTPException(400,"Для кнопки поля требуется ключ поля")
        exists=await db.execute(shop.select(shop.CustomField.id).where(shop.CustomField.key==payload.action,shop.CustomField.enabled.is_(True)).limit(1))
        if exists.scalar_one_or_none() is None: raise shop.HTTPException(400,"Кнопка field ссылается на неизвестное или отключённое поле")
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    await shop.audit(db,"content.menu.updated",admin.email,str(item_id)); await db.commit(); return {"ok":True}

@shop.app.delete("/api/admin/menu/{item_id}")
async def admin_menu_delete(item_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    from .menu_tree import lock_menu
    await lock_menu(db)
    if await db.scalar(shop.select(shop.BotMenuItem.id).where(shop.BotMenuItem.parent_id==item_id).limit(1)):raise shop.HTTPException(409,"Сначала перенесите или удалите дочерние кнопки")
    x=await db.get(shop.BotMenuItem,item_id)
    if not x: raise shop.HTTPException(404,"Menu item not found")
    await db.delete(x)
    from .bot_banners import forget_menu_banner
    banner_file=await forget_menu_banner(db,item_id)
    await shop.audit(db,"content.menu.deleted",admin.email,str(item_id))
    await db.commit()
    from .bot_banners import remove_file
    remove_file(banner_file)
    return {"ok":True}

@shop.app.post("/api/admin/fields")
async def admin_field(payload:FieldIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    x=shop.CustomField(**payload.model_dump()); db.add(x); await db.commit(); await db.refresh(x); return {"id":x.id}

@shop.app.put("/api/admin/fields/{field_id}")
async def admin_field_update(field_id:int,payload:FieldIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    x=await db.get(shop.CustomField,field_id);
    if not x: raise shop.HTTPException(404,"Field not found")
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    await db.commit(); return {"ok":True}

@shop.app.delete("/api/admin/fields/{field_id}")
async def admin_field_delete(field_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    x=await db.get(shop.CustomField,field_id);
    if not x: raise shop.HTTPException(404,"Field not found")
    await db.delete(x); await db.commit(); return {"ok":True}

async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    chunks=[]
    total=0
    while True:
        chunk=await file.read(min(1024*1024, max_bytes-total+1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise shop.HTTPException(413, f"Uploaded file is too large (max {max_bytes} bytes)")
    return b"".join(chunks)


def _valid_image_signature(data:bytes, content_type:str)->bool:
    if content_type=="image/jpeg": return data.startswith(b"\xff\xd8\xff")
    if content_type=="image/png": return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type=="image/gif": return data.startswith((b"GIF87a",b"GIF89a"))
    if content_type=="image/webp": return data.startswith(b"RIFF") and data[8:12]==b"WEBP"
    return False

@shop.app.post("/api/admin/images")
async def admin_image(title:str=Form(...),sort_order:int=Form(0),enabled:bool=Form(True),file:UploadFile=File(...),db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    allowed={"image/png","image/jpeg","image/webp","image/gif"}
    if file.content_type not in allowed: raise shop.HTTPException(400,"Unsupported image type")
    data=await shop._read_upload_limited(file,5*1024*1024)
    if file.content_type not in {"image/jpeg","image/png","image/webp","image/gif"}: raise shop.HTTPException(400,"Only JPG, PNG, WEBP and GIF are allowed")
    if not shop._valid_image_signature(data,file.content_type): raise shop.HTTPException(400,"Invalid image signature")
    ext={"image/jpeg":".jpg","image/png":".png","image/webp":".webp","image/gif":".gif"}[file.content_type]
    name=shop.secrets.token_hex(16)+ext; shop.pathlib.Path(shop.settings.media_dir,name).write_bytes(data)
    x=shop.MenuImage(title=title,filename=name,sort_order=sort_order,enabled=enabled); db.add(x); await db.commit(); await db.refresh(x); return {"id":x.id,"url":"/media/"+name}

@shop.app.delete("/api/admin/images/{image_id}")
async def admin_image_delete(image_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    x=await db.get(shop.MenuImage,image_id);
    if not x: raise shop.HTTPException(404,"Image not found")
    try: shop.pathlib.Path(shop.settings.media_dir,x.filename).unlink(missing_ok=True)
    except Exception as exc:
        shop.logger.warning("Non-critical operation failed: %s", exc)
    await db.delete(x); await db.commit(); return {"ok":True}


__all__ = ['BRANDING_KEYS', 'FieldIn', 'MenuIn', 'MiniAppConfigIn', 'SettingIn', '_PinnedPublicDNSBackend', '_pinned_public_http_client', '_read_upload_limited', '_replace_branding_file', '_resolve_public_host', '_store_branding_image', '_valid_image_signature', 'admin_bot_start_image', 'admin_bot_start_image_delete', 'admin_branding_delete', 'admin_branding_favicon', 'admin_branding_logo', 'admin_content', 'admin_field', 'admin_field_delete', 'admin_field_update', 'admin_image', 'admin_image_delete', 'admin_menu', 'admin_menu_delete', 'admin_menu_update', 'admin_miniapp_background', 'admin_miniapp_background_delete', 'admin_miniapp_config', 'admin_miniapp_image', 'admin_miniapp_image_delete', 'admin_setting', 'public_branding', 'validate_public_url']
