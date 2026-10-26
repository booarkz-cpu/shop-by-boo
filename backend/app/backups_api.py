"""Backups: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import pathlib
import tarfile

from . import main as shop

# ---------- Backups ----------
BACKUP_LOCK=asyncio.Lock()
BACKUP_INTERVALS={"off":0,"6h":21600,"12h":43200,"24h":86400}

async def setting_value(db,key,default=""):
    row=await db.get(shop.AppSetting,key); return row.value if row else default

async def set_setting(db,key,value):
    row=await db.get(shop.AppSetting,key)
    if row: row.value=value
    else: db.add(shop.AppSetting(key=key,value=value))

def _backup_path(filename: str) -> pathlib.Path:
    if not filename or shop.pathlib.Path(filename).name != filename or filename not in {filename.strip()} or "/" in filename or "\\" in filename:
        raise shop.HTTPException(400, "Invalid backup filename")
    path = (shop.pathlib.Path(shop.settings.backups_dir) / filename).resolve()
    root = shop.pathlib.Path(shop.settings.backups_dir).resolve()
    if path.parent != root:
        raise shop.HTTPException(400, "Invalid backup path")
    return path

async def enforce_backup_retention(db: AsyncSession):
    retention = int(await shop.setting_value(db, "backup_retention", "7"))
    rows = (await db.execute(shop.select(shop.BackupJob).where(shop.BackupJob.status == "completed").order_by(shop.BackupJob.created_at.desc()))).scalars().all()
    for old in rows[retention:]:
        if old.filename:
            shop._backup_path(old.filename).unlink(missing_ok=True)
        await db.delete(old)

def _database_cli_config():
    """Return host/user/database/password for PostgreSQL CLI tools from DATABASE_URL."""
    raw=shop.settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed=shop.urllib.parse.urlparse(raw)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RuntimeError("DATABASE_URL must use PostgreSQL")
    host=parsed.hostname or "db"
    user=shop.urllib.parse.unquote(parsed.username or "")
    database=shop.urllib.parse.unquote((parsed.path or "").lstrip("/"))
    password=shop.urllib.parse.unquote(parsed.password or shop.os.getenv("DB_PASSWORD", ""))
    port=str(parsed.port or 5432)
    if not user or not database:
        raise RuntimeError("DATABASE_URL is missing PostgreSQL user or database")
    return {"host":host,"port":port,"user":user,"database":database,"password":password}


async def create_project_backup(db, actor="system"):
    if shop.BACKUP_LOCK.locked(): raise shop.HTTPException(409,"A backup is already running")
    try:
        backup_lock,lock_token=await shop._acquire_redis_lock("lock:backup",ttl=3600,conflict_message="A backup is already running")
    except RuntimeError as exc:
        raise shop._lock_conflict(exc, "A backup is already running") from exc
    async with shop.BACKUP_LOCK:
        job=shop.BackupJob(status="running",created_at=shop.datetime.utcnow()); db.add(job); await db.commit(); await db.refresh(job)
        ts=shop.datetime.utcnow().strftime("%Y%m%d-%H%M%S"); work=shop.pathlib.Path(__import__("tempfile").mkdtemp(prefix="vpn-backup-"))
        try:
            backups=shop.pathlib.Path(shop.settings.backups_dir); backups.mkdir(parents=True,exist_ok=True); dump=work/"database.sql"; archive=work/f"remnawave-vpn-shop-{ts}.tar.gz"
            dbcli=shop._database_cli_config()
            proc=await shop.asyncio.create_subprocess_exec("pg_dump","-h",dbcli["host"],"-p",dbcli["port"],"-U",dbcli["user"],"-d",dbcli["database"],"--clean","--if-exists","--no-owner","--no-privileges",stdout=shop.asyncio.subprocess.PIPE,stderr=shop.asyncio.subprocess.PIPE,env={**shop.os.environ,"PGPASSWORD":dbcli["password"]})
            out,err=await proc.communicate()
            if proc.returncode!=0: raise RuntimeError(f"pg_dump failed: {err.decode(errors='ignore')[-1000:]}")
            dump.write_bytes(out)
            include_env=await shop.setting_value(db,"backup_include_env","1")=="1"
            with shop.tarfile.open(archive,"w:gz") as tar:
                def _tar_filter(info):
                    parts=set(shop.pathlib.Path(info.name).parts)
                    if parts & {"backups",".rollback","node_modules","__pycache__",".git"}: return None
                    if not include_env and shop.pathlib.Path(info.name).name == ".env": return None
                    if not (info.isfile() or info.isdir()): return None
                    return info
                tar.add(shop.settings.project_dir,arcname="project",filter=_tar_filter)
                tar.add(dump,arcname="database.sql")
                media=shop.pathlib.Path(shop.settings.media_dir)
                if media.exists(): tar.add(media,arcname="media")
                packages=media.resolve().parent/"app-packages"
                if packages.exists(): tar.add(packages,arcname="app-packages")
            encrypt=await shop.setting_value(db,"backup_encrypt","1")=="1"
            final=backups/archive.name
            if encrypt:
                password_enc=await shop.setting_value(db,"backup_password","")
                if not password_enc: raise RuntimeError("Backup encryption password is not configured")
                from .security import decrypt_secret
                password=decrypt_secret(password_enc); encrypted=backups/(archive.name+".enc")
                proc=await shop.asyncio.create_subprocess_exec("openssl","enc","-aes-256-cbc","-pbkdf2","-salt","-in",str(archive),"-out",str(encrypted),"-pass","stdin",stdin=shop.asyncio.subprocess.PIPE,stderr=shop.asyncio.subprocess.PIPE)
                _,err=await proc.communicate((password+"\n").encode())
                if proc.returncode!=0: raise RuntimeError(f"Encryption failed: {err.decode(errors='ignore')[-1000:]}")
                archive.unlink(missing_ok=True); final=encrypted
            else: shop.shutil.move(str(archive),str(final))
            job.status="completed"; job.filename=final.name; job.size_bytes=final.stat().st_size; job.sha256=shop.hashlib.sha256(final.read_bytes()).hexdigest(); job.encrypted=encrypt; job.finished_at=shop.datetime.utcnow()
            if await shop.setting_value(db,"backup_s3_enabled","0")=="1":
                try:
                    import boto3
                    s3=boto3.client("s3",endpoint_url=shop.settings.s3_endpoint_url,region_name=shop.settings.s3_region or None,aws_access_key_id=shop.settings.s3_access_key,aws_secret_access_key=shop.settings.s3_secret_key)
                    bucket=await shop.setting_value(db,"backup_s3_bucket",shop.settings.s3_bucket); prefix=await shop.setting_value(db,"backup_s3_prefix",shop.settings.backup_s3_prefix).strip("/")
                    key=f"{prefix}/{final.name}"
                    await shop.asyncio.to_thread(s3.upload_file,str(final),bucket,key)
                    remote=await shop.asyncio.to_thread(s3.head_object,Bucket=bucket,Key=key)
                    if int(remote.get("ContentLength",-1)) != final.stat().st_size: raise RuntimeError("S3 remote size verification failed")
                    # Keep the same retention policy remotely.
                    listing=await shop.asyncio.to_thread(s3.list_objects_v2,Bucket=bucket,Prefix=prefix+"/")
                    objects=sorted(listing.get("Contents",[]),key=lambda o:o.get("LastModified"))
                    keep=max(1,int(await shop.setting_value(db,"backup_retention","7")))
                    for obj in objects[:-keep]:
                        await shop.asyncio.to_thread(s3.delete_object,Bucket=bucket,Key=obj["Key"])
                except Exception as exc: raise RuntimeError(f"S3 upload failed: {exc}")
            await shop.audit(db,"backup.created",actor,final.name,{"encrypted":encrypt,"include_env":include_env,"sha256":job.sha256,"s3":await shop.setting_value(db,"backup_s3_enabled","0")=="1"}); await shop.enforce_backup_retention(db); await db.commit()
            return {"id":job.id,"status":job.status,"filename":job.filename,"size_bytes":job.size_bytes,"encrypted":encrypt}
        except Exception as e:
            job.status="failed"; job.error=str(e)[:2000]; job.finished_at=shop.datetime.utcnow(); shop._METRICS["backup_failures"] += 1; await db.commit(); shop.logger.warning("Backup %s failed: %s", job.id, e); await shop.send_alert(f"Backup #{job.id} failed"); raise
        finally:
            shop.shutil.rmtree(work,ignore_errors=True)
            await shop._release_payment_side_effect_lock(backup_lock,lock_token)
@shop.app.get("/api/admin/backups")
async def list_backups(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.BackupJob).order_by(shop.BackupJob.created_at.desc()).limit(50))).scalars().all()
    return [{"id":x.id,"status":x.status,"filename":x.filename,"size_bytes":x.size_bytes,"sha256":x.sha256,"encrypted":x.encrypted,"error":"unavailable" if x.error else None,"created_at":x.created_at,"finished_at":x.finished_at} for x in rows]

class BackupConfigIn(BaseModel):
    schedule: str = "24h"
    retention: int = Field(default=7, ge=1, le=90)
    encrypt: bool = True
    password: str|None = Field(default=None,min_length=12,max_length=256)
    include_env: bool = True
    s3_enabled: bool = False
    s3_bucket: str|None = Field(default=None,max_length=255)
    s3_prefix: str = Field(default="vpn-shop",max_length=100)

@shop.app.get("/api/admin/backups/config")
async def backup_config(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    return {"schedule":await shop.setting_value(db,"backup_schedule","off"),"retention":int(await shop.setting_value(db,"backup_retention","7")),"encrypt":await shop.setting_value(db,"backup_encrypt","1")=="1","include_env":await shop.setting_value(db,"backup_include_env","1")=="1","password_configured":bool(await shop.setting_value(db,"backup_password","")),"s3_enabled":await shop.setting_value(db,"backup_s3_enabled","0")=="1","s3_bucket":await shop.setting_value(db,"backup_s3_bucket",""),"s3_prefix":await shop.setting_value(db,"backup_s3_prefix",shop.settings.backup_s3_prefix)}

@shop.app.put("/api/admin/backups/config")
async def update_backup_config(payload:BackupConfigIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    if payload.schedule not in shop.BACKUP_INTERVALS: raise shop.HTTPException(400,"Invalid backup schedule")
    if payload.include_env and not payload.encrypt: raise shop.HTTPException(400,"Encrypt backups when .env is included")
    if payload.encrypt and payload.password is None and not await shop.setting_value(db,"backup_password",""): raise shop.HTTPException(400,"Set a backup encryption password first")
    if payload.s3_enabled and not (shop.settings.s3_endpoint_url and (payload.s3_bucket or shop.settings.s3_bucket) and shop.settings.s3_access_key and shop.settings.s3_secret_key): raise shop.HTTPException(400,"S3 is not configured in environment")
    await shop.set_setting(db,"backup_schedule",payload.schedule); await shop.set_setting(db,"backup_retention",str(payload.retention)); await shop.set_setting(db,"backup_encrypt","1" if payload.encrypt else "0"); await shop.set_setting(db,"backup_include_env","1" if payload.include_env else "0"); await shop.set_setting(db,"backup_s3_enabled","1" if payload.s3_enabled else "0"); await shop.set_setting(db,"backup_s3_bucket",payload.s3_bucket or shop.settings.s3_bucket); await shop.set_setting(db,"backup_s3_prefix",payload.s3_prefix)
    if payload.password is not None: await shop.set_setting(db,"backup_password",shop.encrypt_secret(payload.password))
    await shop.audit(db,"backup.config.updated",admin.email,None,{"schedule":payload.schedule,"retention":payload.retention,"encrypt":payload.encrypt,"include_env":payload.include_env}); await db.commit(); return await shop.backup_config(db,admin)

@shop.app.post("/api/admin/backups/run")
async def run_backup(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    try:
        return await shop.create_project_backup(db,admin.email)
    except shop.HTTPException:
        raise
    except Exception as exc:
        shop.logger.warning("Backup request failed: %s", exc)
        raise shop.HTTPException(500, "Backup failed") from exc

@shop.app.get("/api/admin/backups/{backup_id}/download")
async def download_backup(backup_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    job=await db.get(shop.BackupJob,backup_id)
    if not job or not job.filename: raise shop.HTTPException(404,"Backup not found")
    path=shop._backup_path(job.filename)
    if not path.is_file(): raise shop.HTTPException(404,"Backup file not found")
    return shop.FileResponse(path,filename=job.filename,media_type="application/octet-stream",headers={"Cache-Control":"private, no-store"})

@shop.app.delete("/api/admin/backups/{backup_id}")
async def delete_backup(backup_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    job=await db.get(shop.BackupJob,backup_id)
    if not job or not job.filename: raise shop.HTTPException(404,"Backup not found")
    shop._backup_path(job.filename).unlink(missing_ok=True); await db.delete(job); await shop.audit(db,"backup.deleted",admin.email,job.filename); await db.commit(); return {"ok":True}

async def backup_scheduler():
    while True:
        try:
            await shop.asyncio.sleep(60)
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                interval=shop.BACKUP_INTERVALS.get(await shop.setting_value(db,"backup_schedule","off"),0)
                if not interval or shop.BACKUP_LOCK.locked(): continue
                last=(await db.execute(shop.select(shop.BackupJob).where(shop.BackupJob.status=="completed").order_by(shop.BackupJob.created_at.desc()).limit(1))).scalar_one_or_none()
                if last and (shop.datetime.utcnow()-last.created_at).total_seconds()<interval: continue
                await shop.create_project_backup(db,"scheduler")
                await shop.enforce_backup_retention(db)
                await db.commit()
        except Exception: continue

@shop.app.post("/api/admin/backups/{backup_id}/verify")
async def verify_backup(backup_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("backups.write"))):
    job=await db.get(shop.BackupJob,backup_id)
    if not job or not job.filename: raise shop.HTTPException(404,"Backup not found")
    path=shop._backup_path(job.filename)
    if not path.is_file(): raise shop.HTTPException(404,"Backup file not found")
    h=shop.hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""): h.update(chunk)
    digest=h.hexdigest()
    return {"ok":digest==job.sha256,"expected":job.sha256,"actual":digest,"size_bytes":path.stat().st_size}

MAX_BACKUP_ARCHIVE_BYTES=1024*1024*1024
MAX_BACKUP_MEMBERS=50000
MAX_BACKUP_EXTRACTED_BYTES=5*1024*1024*1024
MAX_BACKUP_FILE_BYTES=1024*1024*1024
MAX_BACKUP_PATH_DEPTH=32

def _validate_tar_safety(tar:tarfile.TarFile):
    members=tar.getmembers()
    if len(members)>shop.MAX_BACKUP_MEMBERS: raise shop.HTTPException(400,"Backup contains too many files")
    total=0
    seen=set()
    for m in members:
        posix=shop.pathlib.PurePosixPath(m.name)
        parts=posix.parts
        if not parts or str(posix) in seen: raise shop.HTTPException(400,"Duplicate or empty backup path")
        seen.add(str(posix))
        if posix.is_absolute() or ".." in parts: raise shop.HTTPException(400,"Unsafe backup path")
        if len(parts)>shop.MAX_BACKUP_PATH_DEPTH: raise shop.HTTPException(400,"Backup path is too deep")
        if m.size>shop.MAX_BACKUP_FILE_BYTES: raise shop.HTTPException(400,"Backup member is too large")
        if m.isfile(): total += m.size
        if total>shop.MAX_BACKUP_EXTRACTED_BYTES: raise shop.HTTPException(400,"Backup extracted size is too large")
        if not (m.isfile() or m.isdir()): raise shop.HTTPException(400,"Only regular files and directories are allowed in backups")

def _safe_extract_members(tar:tarfile.TarFile, names:set[str], destination:pathlib.Path):
    root=destination.resolve()
    for member in tar.getmembers():
        if member.name not in names: continue
        target=(destination/member.name).resolve()
        if target != root and root not in target.parents: raise shop.HTTPException(400,"Unsafe archive path")
        tar.extract(member,path=destination)

@shop.app.post("/api/admin/backups/{backup_id}/validate")
async def validate_backup_archive(backup_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("backups.write"))):
    job=await db.get(shop.BackupJob,backup_id)
    if not job or not job.filename: raise shop.HTTPException(404,"Backup not found")
    path=shop._backup_path(job.filename)
    if not path.is_file(): raise shop.HTTPException(404,"Backup file not found")
    if path.stat().st_size>shop.MAX_BACKUP_ARCHIVE_BYTES: raise shop.HTTPException(400,"Backup archive is too large")
    work=shop.pathlib.Path(__import__("tempfile").mkdtemp(prefix="validate-"))
    try:
        source=path
        if job.encrypted:
            password_enc=await shop.setting_value(db,"backup_password","")
            if not password_enc: raise shop.HTTPException(500,"Backup password is not configured")
            dec=work/"backup.tar.gz"
            proc=await shop.asyncio.create_subprocess_exec("openssl","enc","-d","-aes-256-cbc","-pbkdf2","-in",str(source),"-out",str(dec),"-pass","stdin",stdin=shop.asyncio.subprocess.PIPE,stderr=shop.asyncio.subprocess.PIPE)
            _,err=await proc.communicate((shop.decrypt_secret(password_enc)+"\n").encode())
            if proc.returncode!=0: raise shop.HTTPException(400,"Backup decryption failed")
            source=dec
        with shop.tarfile.open(source,"r:gz") as tar:
            shop._validate_tar_safety(tar)
            names=[m.name for m in tar.getmembers()]
            if not any(m.name=="database.sql" and m.isfile() for m in tar.getmembers()): raise shop.HTTPException(400,"Regular database.sql not found in backup")
            root=work.resolve()
            for name in names:
                target=(work/name).resolve()
                if target!=root and root not in target.parents: raise shop.HTTPException(400,"Unsafe archive path")
        return {"ok":True,"database_sql":True,"members":len(names),"checksum":job.sha256}
    finally: shop.shutil.rmtree(work,ignore_errors=True)

class RestoreApprovalIn(BaseModel):
    otp: str = Field(min_length=6, max_length=10)
    approval_id: str = Field(default="", max_length=48)
    confirm: str = ""

@shop.app.post("/api/admin/backups/{backup_id}/restore/request")
async def request_restore(backup_id:int,payload:RestoreApprovalIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("backups.restore"))):
    from .restore_approval import request_approval
    return await request_approval(db, await db.get(shop.BackupJob,backup_id), admin, payload.otp)

@shop.app.post("/api/admin/backups/{backup_id}/restore/approve")
async def approve_restore(backup_id:int,payload:RestoreApprovalIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("backups.restore"))):
    from .restore_approval import use_approval
    return await use_approval(db, await db.get(shop.BackupJob,backup_id), admin, payload.otp, payload.approval_id, approve=True)

@shop.app.post("/api/admin/backups/{backup_id}/restore")
async def restore_backup(backup_id:int,payload:RestoreApprovalIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("backups.restore"))):
    if payload.confirm!="RESTORE": raise shop.HTTPException(400,"Set confirm=RESTORE")
    from .restore_approval import require_restore_admin, use_approval
    require_restore_admin(admin, payload.otp)
    job=await db.get(shop.BackupJob,backup_id)
    if not job or not job.filename: raise shop.HTTPException(404,"Backup not found")
    path=shop._backup_path(job.filename)
    if not path.is_file(): raise shop.HTTPException(404,"Backup file not found")
    if path.stat().st_size>shop.MAX_BACKUP_ARCHIVE_BYTES: raise shop.HTTPException(400,"Backup archive is too large")
    if job.sha256:
        h=shop.hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024*1024),b""): h.update(chunk)
        if h.hexdigest()!=job.sha256: raise shop.HTTPException(409,"Backup checksum mismatch")
    await use_approval(db, job, admin, payload.otp, payload.approval_id)
    if shop.redis_client is None: raise shop.HTTPException(503,"Redis is required for restore")
    try:
        maintenance_lock,maintenance_token=await shop._acquire_redis_lock("lock:maintenance",ttl=1800,conflict_message="Maintenance operation already in progress")
    except RuntimeError as exc:
        raise shop._lock_conflict(exc, "Maintenance operation already in progress") from exc
    try:
        await shop.set_setting(db,"maintenance_mode","1"); await db.commit()
        # Always create a fresh pre-restore snapshot so a failed/incorrect restore can be recovered.
        await shop.create_project_backup(db, f"pre-restore:{admin.email}")
    except shop.HTTPException:
        await shop._release_payment_side_effect_lock(maintenance_lock,maintenance_token); raise
    except Exception as exc:
        shop.logger.warning("Pre-restore snapshot failed: %s", exc)
        await shop._release_payment_side_effect_lock(maintenance_lock,maintenance_token)
        raise shop.HTTPException(500, "Restore failed") from exc
    work=shop.pathlib.Path(__import__("tempfile").mkdtemp(prefix="restore-"))
    restore_ok=False
    try:
        source=path
        if job.encrypted:
            password_enc=await shop.setting_value(db,"backup_password","")
            if not password_enc: raise shop.HTTPException(500,"Backup password is not configured")
            dec=work/"backup.tar.gz"; from .security import decrypt_secret
            proc=await shop.asyncio.create_subprocess_exec("openssl","enc","-d","-aes-256-cbc","-pbkdf2","-in",str(source),"-out",str(dec),"-pass","stdin",stdin=shop.asyncio.subprocess.PIPE,stderr=shop.asyncio.subprocess.PIPE); _,err=await proc.communicate((decrypt_secret(password_enc)+"\n").encode())
            if proc.returncode!=0: raise shop.HTTPException(400,"Backup decryption failed")
            source=dec
        with shop.tarfile.open(source,"r:gz") as tar:
            shop._validate_tar_safety(tar)
            member=next((m for m in tar.getmembers() if m.name=="database.sql"),None)
            if not member or not member.isfile(): raise shop.HTTPException(400,"Regular database.sql not found in backup")
            shop._safe_extract_members(tar,{"database.sql"},work)
            media_members=[m.name for m in tar.getmembers() if m.name=="media" or m.name.startswith("media/")]
            if media_members:
                media_root=shop.pathlib.Path(shop.settings.media_dir)
                media_root.mkdir(parents=True,exist_ok=True)
                for name in media_members:
                    target=(media_root/shop.pathlib.Path(name).relative_to("media")).resolve() if name!="media" else media_root.resolve()
                    if target!=media_root.resolve() and media_root.resolve() not in target.parents: raise shop.HTTPException(400,"Unsafe media archive path")
                    shop._safe_extract_members(tar,{name},work)
                extracted=work/"media"
                if extracted.exists():
                    for src in extracted.rglob("*"):
                        if src.is_file():
                            dst=media_root/src.relative_to(extracted); dst.parent.mkdir(parents=True,exist_ok=True); shop.shutil.copy2(src,dst)
            package_members=[m.name for m in tar.getmembers() if m.name=="app-packages" or m.name.startswith("app-packages/")]
            if package_members:
                media_root=shop.pathlib.Path(shop.settings.media_dir)
                package_root=(media_root.resolve().parent/"app-packages")
                package_root.mkdir(parents=True,exist_ok=True)
                for name in package_members:
                    target=(package_root/shop.pathlib.Path(name).relative_to("app-packages")).resolve() if name!="app-packages" else package_root.resolve()
                    if target!=package_root.resolve() and package_root.resolve() not in target.parents: raise shop.HTTPException(400,"Unsafe media archive path")
                    shop._safe_extract_members(tar,{name},work)
                extracted_packages=work/"app-packages"
                if extracted_packages.exists():
                    for src in extracted_packages.rglob("*"):
                        if src.is_file() and src.suffix in {".apk",".ipa"} and len(src.name)==36:
                            dst=package_root/src.name
                            if dst.parent.resolve()!=package_root.resolve(): continue
                            shop.shutil.copy2(src,dst)
        sql_file=work/"database.sql"
        # Use the configured SQLAlchemy database URL rather than hard-coded deployment
        # credentials. This keeps restore correct for non-default DB hosts/users/passwords.
        dbcli=shop._database_cli_config()
        proc=await shop.asyncio.create_subprocess_exec("psql","-h",dbcli["host"],"-p",dbcli["port"],"-U",dbcli["user"],"-d",dbcli["database"],"-v","ON_ERROR_STOP=1","-f",str(sql_file),env={**shop.os.environ,"PGPASSWORD":dbcli["password"]},stdout=shop.asyncio.subprocess.PIPE,stderr=shop.asyncio.subprocess.PIPE); out,err=await proc.communicate()
        if proc.returncode!=0:
            shop.logger.warning("Restore failed: %s", err.decode(errors="ignore")[-1000:])
            raise shop.HTTPException(500, "Restore failed")
        # The active SQLAlchemy session is invalid after destructive DB replacement.
        await db.close()
        mig=await shop.asyncio.create_subprocess_exec("alembic","upgrade","head",cwd=shop.settings.project_dir,stdout=shop.asyncio.subprocess.PIPE,stderr=shop.asyncio.subprocess.PIPE); mout,merr=await mig.communicate()
        if mig.returncode!=0:
            shop.logger.warning("Migration after restore failed: %s", merr.decode(errors="ignore")[-1000:])
            raise shop.HTTPException(500, "Migration after restore failed")
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as check_db:
            await check_db.execute(shop.sql_text("SELECT 1"))
            await shop.audit(check_db,"backup.restored",admin.email,job.filename); await check_db.commit()
        restore_ok=True
        return {"ok":True,"restored":job.filename,"migrations":"head"}
    finally:
        shop.shutil.rmtree(work,ignore_errors=True)
        if restore_ok:
            try:
                async with shop.AsyncSession(shop.engine,expire_on_commit=False) as unlock_db:
                    await shop.set_setting(unlock_db,"maintenance_mode","0"); await shop.set_setting(unlock_db,"restore_state","ok"); await unlock_db.commit()
            except Exception as exc:
                shop.logger.warning("Non-critical operation failed: %s", exc)
        else:
            try:
                async with shop.AsyncSession(shop.engine,expire_on_commit=False) as fail_db:
                    await shop.set_setting(fail_db,"maintenance_mode","1"); await shop.set_setting(fail_db,"restore_state","failed"); await fail_db.commit()
            except Exception as exc:
                shop.logger.warning("Non-critical operation failed: %s", exc)
        await shop._release_payment_side_effect_lock(maintenance_lock,maintenance_token)


__all__ = ['BACKUP_INTERVALS', 'BACKUP_LOCK', 'BackupConfigIn', 'MAX_BACKUP_ARCHIVE_BYTES', 'MAX_BACKUP_EXTRACTED_BYTES', 'MAX_BACKUP_FILE_BYTES', 'MAX_BACKUP_MEMBERS', 'MAX_BACKUP_PATH_DEPTH', 'RestoreApprovalIn', '_backup_path', '_database_cli_config', '_safe_extract_members', '_validate_tar_safety', 'approve_restore', 'backup_config', 'backup_scheduler', 'create_project_backup', 'delete_backup', 'download_backup', 'enforce_backup_retention', 'list_backups', 'request_restore', 'restore_backup', 'run_backup', 'set_setting', 'setting_value', 'update_backup_config', 'validate_backup_archive', 'verify_backup']
