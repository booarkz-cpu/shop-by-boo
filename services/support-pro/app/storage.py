import os
import re
import secrets
from pathlib import Path

UPLOAD = Path(os.getenv('UPLOAD_DIR', '/data/uploads')).resolve()
MAX_BYTES = int(os.getenv('MAX_UPLOAD_MB', '50')) * 1024 * 1024


def safe_name(name):
    return re.sub(r'[\x00-\x1f\x7f/\\]', '_', name or 'attachment')[-160:]


def new_path(name):
    UPLOAD.mkdir(parents=True, exist_ok=True)
    return UPLOAD / (secrets.token_hex(16) + '_' + safe_name(name))


def checked_path(path):
    target = Path(path).resolve()
    if not target.is_relative_to(UPLOAD) or not target.is_file():
        raise ValueError('Файл недоступен')
    return target


async def save_upload(upload):
    path = new_path(upload.filename)
    size = 0
    try:
        with path.open('wb') as out:
            while chunk := await upload.read(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Превышен допустимый размер файла')
                out.write(chunk)
        await scan_file(path)
        return path, size
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class BoundedWriter:
    def __init__(self, file):
        self.file, self.size = file, 0

    def write(self, data):
        self.size += len(data)
        if self.size > MAX_BYTES:
            raise ValueError('Превышен допустимый размер файла')
        return self.file.write(data)

    def seek(self, *args):
        return self.file.seek(*args)

    def flush(self):
        return self.file.flush()


async def scan_file(path):
    """Optional ClamAV INSTREAM; configured scanner failures fail closed."""
    import asyncio, struct
    host = os.getenv('CLAMAV_HOST')
    if not host:
        if os.getenv('REQUIRE_ANTIVIRUS','false').lower()=='true':
            raise ValueError('Антивирус не настроен; загрузка отклонена')
        return
    async def scan():
        reader, writer = await asyncio.open_connection(host,int(os.getenv('CLAMAV_PORT','3310')))
        try:
            writer.write(b'zINSTREAM\0')
            with path.open('rb') as file:
                while chunk:=file.read(65536):
                    writer.write(struct.pack('!I',len(chunk))+chunk)
                    await writer.drain()
            writer.write(b'\0\0\0\0');await writer.drain()
            result=await reader.readuntil(b'\0')
            if not result.rstrip(b'\0').endswith(b': OK'):raise ValueError('Файл отклонён антивирусом')
        finally:
            writer.close();await writer.wait_closed()
    try:await asyncio.wait_for(scan(),timeout=60)
    except ValueError:raise
    except Exception as exc:raise ValueError('Антивирус недоступен; файл не принят') from exc
