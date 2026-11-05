# API для мобильных приложений

Приложения Android и iOS — пользовательское (`android-user`, `ios-user`) и администраторское (`android-admin`, `ios-admin`) — работают с тем же API, что кабинет и админка. Полный каталог маршрутов — [API_ENDPOINTS](../../API_ENDPOINTS.md). Здесь — то, что относится только к приложениям.

## Как приложение входит

Заголовок `X-Shop-Client: <приложение>` на каждом запросе. Веб-сессии живут в cookie, у приложений — свой вход:

1. **Пароль (и 2FA).** `POST /api/auth/login` (клиент) или `POST /api/admin/auth/login` (администратор) с заголовком PKCE S256 (`X-Shop-Code-Challenge`). В ответ приходит одноразовый `authorization_code`, не токен.
2. **Вход без пароля.** Бот (`/start app_login`, `/app`), кабинет или Mini App выдают одноразовый код (`POST /api/me/app-login`). Яндекс ID, VK ID и Google, запущенные из приложения, возвращают код по ссылке `corgi://login?base=…&code=…`; страница `GET /api/app/open` пересылает на схему приложения. Приложение обменивает код: `POST /api/auth/mobile/code`. Какие способы включены, сообщает `GET /api/public/app-login/methods`.
3. **Ключ доступа (passkey).** `/api/auth/passkeys/login/options` и `/verify`.
4. **Токен.** `POST /api/auth/mobile/token` с `code_verifier` — только из приложения, код без верификатора бесполезен браузеру. Токен хранится в Keychain (iOS) или зашифрованным ключом AES-GCM из Android Keystore (Android) и передаётся в `Authorization: Bearer`.

Проверка целостности (по желанию владельца): `POST /api/mobile/integrity/challenge`, затем Play Integrity / DeviceCheck при обмене кода. Подробно — `backend/app/mobile_auth.py`, `app_login.py`.

## Что настраивается из админки

| Маршрут | Что отдаёт | Где меняется |
| --- | --- | --- |
| `GET /api/mobile/layout` | экраны, кнопки, баннеры, тексты ru/en/uk | «Приложения: экраны и кнопки» |
| `GET /api/mobile/push-style` | категории push и кнопки | «Приложения: стиль push-уведомлений» |
| `GET /api/public/apps` | карточки приложений, ссылки на сборки | «Android и iOS» |
| `GET /api/public/config` | бренд, резервные адреса API (зеркала), сайты напрямую | «Оформление», «Android и iOS → Резервные адреса» |

## Данные клиента

Приложение использует маршруты кабинета `/api/me/*`:
- подписки, устройства, серверы, подключение и QR (`/api/me/connection-info`, `/api/me/connection-qr`);
- кошелёк, покупка и продление (`/api/me/subscription/quote`, `/purchase`, `/api/payments/create`);
- семья, подарки, конкурсы, поддержка;
- проверка скорости (`/api/me/speedtest`), диагностика (`/api/me/diagnostics`), рекомендация маршрута.

Push-токены — `POST /api/me/push/devices` и `/unregister`. События аналитики — `POST /api/mobile/events`, без персональных данных. Возврат после оплаты — `corgi://payment`, статус заказа проверяется `GET /api/me/payments/order/{id}`.

## Администраторское приложение

Использует маршруты `/api/admin/*` с теми же правами ролей ([RBAC](RBAC.md)) и панели Telegram/мобильных админок (`backend/app/mobile_panels.py`). Опасные действия ([подтверждение](RBAC.md#подтверждение-опасных-действий-step-up)) из приложения не вызываются — их делают в веб-админке.

## Адрес магазина вшит в сборку (с v28.85.0)

Покупатель и администратор не вводят адрес API.
- **Откуда берётся адрес.** Переменная репозитория `CORGI_SHOP_URL` (Settings → Secrets and variables → Actions → **Variables**) или строка в `mobile/shop-url.txt`; переменная важнее. Формат — `https://api.example.com`.
- **Что делает сборка.** Все четыре приложения собираются с этим адресом: Android через `BuildConfig.SHOP_URL`, iOS через `CorgiShopURL` в `Info.plist`.
- **Приложение клиента** не показывает поле адреса.
- **Приложение администратора** заполняет адрес в новом профиле. Профили других магазинов можно добавить вручную.
- **Если адрес не задан,** поле остаётся. Адрес также приходит сам из ссылки входа от бота или кабинета (`corgi://login?base=…`), а при блокировке — из подписанного списка зеркал.
