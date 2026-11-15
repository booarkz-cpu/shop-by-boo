"""Server-side account bootstrap/recovery. Run only on the trusted host."""
import argparse
import asyncio
import getpass
import os
from dotenv import load_dotenv
load_dotenv()
import pyotp
from sqlalchemy import select
from .db import Session, ph, engine
from .models import Operator, Category, Macro, Settings
from .sla import DEFAULTS


def show_secret(login, secret):
    print(f'Настройка TOTP для {login}. Сохраните в приложении-аутентификаторе:')
    print(secret)
    print(pyotp.TOTP(secret).provisioning_uri(name=login, issuer_name='Support Pro'))
    print('Не передавайте этот ключ посторонним. Следующий вход требует пароль и код 2FA.')


async def run(args):
    async with Session() as s:
        if args.command == 'init':
            login = os.getenv('ADMIN_LOGIN', 'admin')
            op = await s.scalar(select(Operator).where(Operator.login == login))
            secret = None
            if not op:
                password = os.getenv('ADMIN_PASSWORD') or getpass.getpass('Пароль администратора (минимум 12 символов): ')
                if len(password) < 12:
                    raise SystemExit('Пароль должен содержать минимум 12 символов')
                secret = pyotp.random_base32()
                op = Operator(login=login, password_hash=ph.hash(password), role='admin', totp_secret=secret)
                s.add(op)
            elif not op.totp_secret:
                secret = pyotp.random_base32()
                op.totp_secret = secret
                op.auth_version += 1
            if not await s.scalar(select(Category.id).limit(1)):
                s.add_all([Category(name=x) for x in ['Общее', 'Оплата', 'Техническая проблема', 'Аккаунт', 'Другое']])
            if not await s.scalar(select(Macro.id).limit(1)):
                s.add_all([Macro(title='Получили обращение', body='Здравствуйте, {name}! Мы получили обращение #{ticket_id} и уже занимаемся вопросом.'),
                           Macro(title='Уточнение', body='Пожалуйста, пришлите дополнительную информацию или скриншот.')])
            if not await s.get(Settings, 1):
                s.add(Settings(id=1, data=DEFAULTS))
            await s.commit()
            if secret:
                show_secret(login, secret)
            else:
                print('Настройки и учётная запись уже существуют; пароль и 2FA сохранены.')
        elif args.command == 'reset-2fa':
            op = await s.scalar(select(Operator).where(Operator.login == args.login))
            if not op:
                raise SystemExit('Оператор не найден')
            secret = pyotp.random_base32()
            op.totp_secret, op.last_totp_step = secret, 0
            op.auth_version += 1
            await s.commit()
            show_secret(op.login, secret)
        elif args.command == 'reset-password':
            op = await s.scalar(select(Operator).where(Operator.login == args.login))
            if not op:
                raise SystemExit('Оператор не найден')
            password = getpass.getpass('Новый пароль: ')
            if len(password) < 12 or password != getpass.getpass('Повторите пароль: '):
                raise SystemExit('Пароли должны совпадать и содержать минимум 12 символов')
            op.password_hash = ph.hash(password)
            op.auth_version += 1
            await s.commit()
            print('Пароль изменён, сессии отозваны.')
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('reset-2fa').add_argument('login')
    sub.add_parser('reset-password').add_argument('login')
    asyncio.run(run(parser.parse_args()))
