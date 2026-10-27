"""Promo code generator and the daily encrypted database copy to the owner's Telegram chat."""
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import main as shop
from app import promo_generator, telegram_backup
from app.models import PromoCode
from app.security import encrypt_secret
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="a@b.c")


@pytest.mark.asyncio
async def test_a_batch_of_unique_one_off_codes_is_created_and_exported(database):
    out = await promo_generator.generate_promo_codes(promo_generator.GenerateIn(count=40, prefix="bf", kind="percent", value=Decimal("25")), database, ADMIN)
    assert out["count"] == 40 and len(set(out["codes"])) == 40
    assert all(c.startswith("BF-") and len(c) == 11 and not set(c[3:]) & set("01OI") for c in out["codes"])
    row = await database.scalar(select(PromoCode).where(PromoCode.code == out["codes"][0]))
    assert (row.usage_limit, row.max_uses_per_user, row.value) == (1, 1, Decimal("25"))
    csv = (await promo_generator.export_promo_codes("bf", database, ADMIN)).body.decode()
    assert csv.count("\n") == 41 and out["codes"][5] in csv
    with pytest.raises(Exception):
        promo_generator.GenerateIn(count=5001, value=Decimal("1"))
    with pytest.raises(HTTPException):
        await promo_generator.generate_promo_codes(promo_generator.GenerateIn(count=1, value=Decimal("150")), database, ADMIN)
    assert await database.scalar(select(func.count(PromoCode.id))) == 40


class Telegram:
    def __init__(self):
        self.files = []

    async def post(self, url, data=None, files=None):
        name, fh, _ = files["document"]
        self.files.append((data["chat_id"], name, len(fh.read()), data["caption"]))
        return type("R", (), {"status_code": 200})()


async def fake_dump(target: Path):
    target.write_bytes(b"PGDMP" + b"x" * 1000)


@pytest.mark.asyncio
async def test_the_database_copy_is_encrypted_split_and_sent_once_a_day(database, monkeypatch):
    monkeypatch.setattr(shop.settings, "bot_token", "1:x")
    with pytest.raises(HTTPException):
        await telegram_backup.put_telegram_backup(telegram_backup.TelegramBackupIn(enabled=True, chat_id=""), database, ADMIN)
    await telegram_backup.put_telegram_backup(telegram_backup.TelegramBackupIn(enabled=True, chat_id="-1001234567890", time="03:30"), database, ADMIN)
    alerts = []

    async def alert(text):
        alerts.append(text)
    monkeypatch.setattr("app.ops_alerts.send", alert)
    tg = Telegram()
    night = datetime(2026, 10, 28, 0, 40, tzinfo=timezone.utc)  # 03:40 MSK
    result = await telegram_backup.tick(database, night, client=tg, dump=fake_dump)
    assert result and result.startswith("Ошибка"), result
    assert "пароль" in alerts[0] and tg.files == [], (alerts, tg.files)
    await shop.set_setting(database, "backup_password", encrypt_secret("backup-pass"))
    await database.commit()
    monkeypatch.setattr(telegram_backup, "PART_BYTES", 400)
    assert await telegram_backup.tick(database, night, client=tg, dump=fake_dump) is None, "already done today"
    tomorrow = datetime(2026, 10, 29, 0, 40, tzinfo=timezone.utc)
    result = await telegram_backup.tick(database, tomorrow, client=tg, dump=fake_dump)
    assert result.startswith("Отправлено: 3") and len(tg.files) == 3 and all(f[0] == "-1001234567890" for f in tg.files)
    assert "Часть 1 из 3" in tg.files[0][3] and tg.files[0][1].endswith(".part01")


@pytest.mark.asyncio
async def test_the_sent_copy_decrypts_back_to_the_dump(tmp_path):
    raw, enc = tmp_path / "db.pgc", tmp_path / "db.pgc.enc"
    await fake_dump(raw)
    await telegram_backup.encrypt(raw, enc, "backup-pass")
    assert enc.read_bytes()[:8] == b"Salted__"
    parts = telegram_backup.split(enc, 300)
    joined = tmp_path / "joined.enc"
    joined.write_bytes(b"".join(p.read_bytes() for p in parts))
    out = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", str(joined), "-pass", "pass:backup-pass"], capture_output=True)
    assert out.returncode == 0 and out.stdout == raw.read_bytes()
