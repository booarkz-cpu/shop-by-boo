# Тестирование функций, требующих внешних зависимостей и секретов

Дистрибутив `v28.57.0`, runtime/API `21.5.1`, миграция магазина `0088_filter_and_regions`.

Документ составлен так, чтобы после выдачи секретов можно было пройти тестирование **без повторного
изучения проекта**: для каждой функции указаны модули, переменные окружения, команды, ожидаемый
результат и критерии приёмки.

Все имена секретов и переменных взяты из фактического кода (`backend/app/config.py`,
`backend/app/gateways/*.py`, `.github/workflows/*.yml`) — ни одно имя не придумано.

## Статусы

| Статус | Значение |
| --- | --- |
| `PASS` | Проверено, ожидаемый результат получен |
| `FAIL` | Проверено, результат не соответствует ожиданию |
| `BLOCKED_SECRETS` | Нужны ключи/токены, которых нет |
| `BLOCKED_ACCESS` | Нужен сервер, сеть или права |
| `NOT_RUN` | Не выполнялось |
| `NOT_APPLICABLE` | Неприменимо к этой установке |

Правило: непроверенный сценарий **не** отмечается как успешный. Текущее состояние всех групп —
в сводке §14.

## 1. Подготовка окружения

```bash
git clone https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-test.txt

cp .env.example .env
# заполните только те группы, которые собираетесь проверять
```

Минимальный набор для локального запуска без внешних сервисов:

```bash
export APP_SECRET='local-only-secret'
export APP_ENV=test
export MEDIA_DIR=/tmp/media            # иначе StaticFiles упадёт на /data/media
export COOKIE_SECURE=false
export DATABASE_URL='sqlite+aiosqlite:///./local.db'
export PAYMENTS_SANDBOX=true           # песочница платежей вне production
export MOBILE_REQUIRE_PROOF=false
export AUTO_RENEW_ENABLED=false
```

`PAYMENTS_SANDBOX=true` действует только при `APP_ENV` из
`{development, dev, test, testing, staging, sandbox}` (`backend/app/sandbox_mode.py`). В `production`
флаг отклоняется на старте — это защита, а не баг.

Базовый прогон тестов:

```bash
cd backend && python -m pytest -q ../tests
```

Полный набор — 2507 тестов; в песочнице на `v28.57.0` проходит без падений.

## 2. Remnawave (панель VPN)

**Назначение.** Выдача и продление подписок, устройства, узлы, синхронизация статусов.

**Модули.** `backend/app/remnawave.py`, `remnawave_events.py`, `remnawave_shop_api.py`,
`sub_proxy.py`, `subscription_freeze.py`.

**Переменные.**

| Переменная | Обязательна | Примечание |
| --- | --- | --- |
| `REMNAWAVE_URL` | да | Базовый URL панели, https |
| `REMNAWAVE_TOKEN` | да | API-токен панели |
| `REMNAWAVE_WEBHOOK_SECRET` | для webhook | Проверка `X-Remnawave-Signature` |
| `REMNAWAVE_CB_FAILURES` | нет | Порог circuit breaker (по умолчанию 5) |
| `REMNAWAVE_CB_COOLDOWN` | нет | Пауза в секундах (по умолчанию 30) |
| `REMNAWAVE_LIVE_URL`, `REMNAWAVE_LIVE_TOKEN` | для live-теста | Только для `tests/live/` |

**Что проверено без секретов.**

```bash
python -m pytest -q ../tests -k "remnawave or subscription or sub_proxy"
```

Покрыто: разбор ответов, circuit breaker, повторные запросы, тайм-ауты, обработка ошибок панели.
Статус: `PASS`.

**Сценарий с реальной панелью.**

```bash
export REMNAWAVE_URL='https://panel.example.com'
export REMNAWAVE_TOKEN='<token>'
python -m pytest -q ../tests/live/test_remnawave_live.py -v
```

Проверяется: доступность панели, чтение списка пользователей, создание/продление подписки,
ограничение устройств, идемпотентность повторного вызова.

**Ожидаемый результат.** Тесты live проходят; в админке «Remnawave» видны узлы и пользователи;
подписка, созданная в магазине, появляется в панели в течение синхронизации.

**Критерии приёмки.** Создание подписки идемпотентно (повтор не создаёт дубль); отключение в
магазине отражается в панели; при недоступной панели магазин отдаёт понятную ошибку, а не 500.

**Типичные ошибки.** `401` — истёк токен; `SSL: CERTIFICATE_VERIFY_FAILED` — самоподписанный
сертификат панели, нужен доверенный; тайм-аут — проверьте, что магазин видит панель по сети.

**Очистка.** Удалите созданных тестовых пользователей в панели; не трогайте реальных клиентов.

**Текущий статус:** `BLOCKED_SECRETS`.

## 3. Reverse proxy (Remnawave)

**Назначение.** TLS-терминация, маршрутизация на панель и подписки, скрытие прямых портов.

**Модули.** `deploy/Caddyfile`, `deploy/caddy/`, `deploy/nginx/`, `backend/app/sub_proxy.py`.

**Переменные.** `DOMAIN`, `ACME_EMAIL` (в `.env.example`), плюс параметры Caddyfile.

**Что проверено без секретов.**

```bash
# синтаксис конфигурации Caddy
docker run --rm -v "$PWD/deploy:/etc/caddy" caddy:2 caddy validate --config /etc/caddy/Caddyfile
# синтаксис nginx
docker run --rm -v "$PWD/deploy/nginx:/etc/nginx" nginx:alpine nginx -t
```

В песочнице Docker недоступен → `BLOCKED_ACCESS`. Разбор YAML/конфигов выполнен вручную: структура
корректна.

**Сценарий с сервером.**

```bash
curl -sI https://panel.example.com        # 200, валидный сертификат
curl -sI https://shop.example.com/health  # 200
curl -s https://shop.example.com/api/webhooks/remnawave -X POST -H 'X-Remnawave-Signature: ...' -d '{}'
```

**Критерии приёмки.** Сертификат валиден и продлевается; заголовки безопасности присутствуют;
подписочные ссылки открываются без прямого доступа к портам панели.

**Текущий статус:** `BLOCKED_ACCESS`.

## 4. Telegram-бот

**Назначение.** `/start`, меню, покупка, выдача конфигурации, уведомления, поддержка.

**Модули.** `backend/app/bot.py`, `bot_workspace.py`, `bot_banners.py`, `telegram_stars.py`,
`telegram_backup.py`, `bot-entrypoint.sh`, сервис `bot` в `docker-compose.yml`.

**Переменные.**

| Переменная | Обязательна |
| --- | --- |
| `BOT_TOKEN` | да |
| `ADMIN_TELEGRAM_ID` | да |
| `REQUIRED_TELEGRAM_CHANNEL` | нет |
| `BOT_USERNAME` | рекомендуется |

**Что проверено без секретов.**

```bash
python -m pytest -q ../tests -k "bot or telegram"
```

Покрыто: маршрутизация callback, меню, локализация, обработка повторных событий, отсутствие токена.
Статус: `PASS`.

**Сценарий с ботом.**

1. `BOT_TOKEN=...` в `.env`, `docker compose up -d bot backend`.
2. В Telegram: `/start` → появляется меню.
3. Выбрать тариф → создать платёж (в песочнице) → проверить выдачу конфигурации.
4. Нажать кнопку поддержки → тикет создаётся.
5. Повторно нажать ту же callback-кнопку → дубль операции не создаётся.

**Критерии приёмки.** `/start` отвечает < 2 с; меню соответствует `admin` → «Контент»; конфигурация
выдаётся один раз на подписку; повторный callback не создаёт второй платёж.

**Типичные ошибки.** `401 Unauthorized` — неверный `BOT_TOKEN`; «Conflict: terminated by other
getUpdates» — запущены два инстанса бота или одновременно polling и webhook.

**Очистка.** `/deletewebhook` при переходе на polling; удалить тестовые заказы.

**Текущий статус:** `BLOCKED_SECRETS`.

## 5. Telegram Mini App

**Назначение.** Магазин внутри Telegram; авторизация через `initData`.

**Модули.** `miniapp/`, `backend/app/auth_api.py`, `admin_auth_api.py`, `app_login.py`.

**Переменные.** `BOT_TOKEN` (ключ HMAC для проверки подписи), `MINI_APP_URL`, `CABINET_URL`.

**Что проверено без секретов.** Проверка `initData` реализована в `auth_api.py`:
HMAC-сверка `hmac.compare_digest`, отказ при отсутствии токена, отказ при `auth_date` старше 600 с.
Покрыто тестами вместе с группой Telegram. Статус: `PASS` (логика), `BLOCKED_SECRETS` (живой прогон).

**Сценарий.**

1. Открыть Mini App из бота.
2. Убедиться, что запросы уходят с `initData`.
3. Проверить, что подделанный `initData` отклоняется: `401 Invalid Telegram initData`.
4. Проверить истечение: изменить `auth_date` на час назад → `401 Expired Telegram initData`.

**Критерии приёмки.** Подпись проверяется на сервере, не в клиенте; просроченный `initData`
отклоняется; без `BOT_TOKEN` — `401`.

**Текущий статус:** `BLOCKED_SECRETS`.

## 6. Платежи

**Назначение.** Создание платежа, подтверждение, выдача подписки, возвраты.

**Провайдеры в коде.** `yookassa`, `platega`, `rollypay`, `cryptobot`, `freekassa`, `sandbox`,
плюс шлюзы из `backend/app/gateways/`: `anore`, `antilopay`, `aurapay`, `cashera`, `cloudpayments`,
`lava`, `mulenpay`, `pal24`, `paritypay`, `wata`.

**Переменные.**

| Провайдер | Переменные |
| --- | --- |
| ЮKassa | `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_IP_ALLOWLIST` |
| Platega | `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET` |
| RollyPay | `ROLLYPAY_API_KEY`, `ROLLYPAY_SIGNING_SECRET` |
| CryptoBot | `CRYPTOBOT_TOKEN` |
| FreeKassa | `FREEKASSA_SHOP_ID`, `FREEKASSA_SECRET1`, `FREEKASSA_SECRET2`, `FREEKASSA_API_KEY`, `FREEKASSA_WEBHOOK_IP_ALLOWLIST` |
| Anore | `ANORE_SHOP_ID`, `ANORE_API_KEY`, `ANORE_SECRET_KEY` |
| Antilopay | `ANTILOPAY_PROJECT_ID`, `ANTILOPAY_SECRET_ID`, `ANTILOPAY_PUBLIC_KEY`, `ANTILOPAY_PRIVATE_KEY` |
| AuraPay | `AURAPAY_SHOP_ID`, `AURAPAY_API_KEY`, `AURAPAY_SECRET_KEY` |
| Cashera | `CASHERA_API_KEY`, `CASHERA_API_SECRET` |
| CloudPayments | `CLOUDPAYMENTS_PUBLIC_ID`, `CLOUDPAYMENTS_API_SECRET` |
| Lava | `LAVA_SHOP_ID`, `LAVA_SECRET_KEY`, `LAVA_WEBHOOK_SECRET` |
| MulenPay | `MULENPAY_SHOP_ID`, `MULENPAY_API_KEY`, `MULENPAY_SECRET_KEY` |
| Pay24 | `PAL24_SHOP_ID`, `PAL24_API_TOKEN`, `PAL24_SIGNATURE_TOKEN` |
| ParityPay | `PARITYPAY_SHOP_ID`, `PARITYPAY_SECRET_KEY`, `PARITYPAY_CALLBACK_SECRET` |
| Wata | `WATA_ACCESS_TOKEN` |

**Что проверено без секретов.**

```bash
export PAYMENTS_SANDBOX=true APP_ENV=test
python -m pytest -q ../tests -k "payment or webhook or refund or dunning or promo"
```

Покрыто: идемпотентность webhook, повторные уведомления, порядок провайдеров
(`_payment_provider_order`), circuit breaker, возвраты, отмена, истечение срока, резервирование
промокодов, запрет выдачи подписки по клиентскому сообщению. Статус: `PASS`.

Важно: подписка **никогда** не активируется по клиентскому сообщению — только по подтверждённому
событию провайдера или sandbox-платежу вне production.

**Сценарий с реальным провайдером.**

```bash
export YOOKASSA_SHOP_ID='...' YOOKASSA_SECRET_KEY='...'
export YOOKASSA_WEBHOOK_IP_ALLOWLIST='<CIDR провайдера>'
export ACCEPTANCE_AMOUNT=10 ACCEPTANCE_RETURN_URL='https://shop.example.com/paid'
python -m pytest -q ../tests/live/test_payments_live.py -v
```

**Критерии приёмки.** Сумма и валюта совпадают с заказом; webhook с неверной подписью отклоняется;
повторный webhook не выдаёт вторую подписку; возврат отзывает доступ; при сбое провайдера платёж
помечается `failed` с retry.

**Типичные ошибки.** `401` webhook — неверный секрет/подпись; `403` — IP не в allowlist; «провайдер
недоступен» при пустых ключах — `provider_configured()` возвращает `false`.

**Очистка.** Возвраты тестовых платежей в кабинете провайдера; удалить тестовые заказы.

**Текущий статус:** `BLOCKED_SECRETS`. Реальный платёжный цикл (`PASS`) требует хотя бы одного
провайдера.

## 7. OAuth: Яндекс, VK, email

**Переменные.** `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`, `YANDEX_REDIRECT_URI`,
`VK_CLIENT_ID`, `VK_CLIENT_SECRET`, `VK_REDIRECT_URI`. Email-вход включён всегда
(`email_auth_enabled: true` в `/api/public/config`).

**Что проверено без секретов.** `yandex_enabled` и `vk_enabled` в публичном конфиге вычисляются от
наличия ключей — без них кнопки не показываются. Статус: `PASS` (логика).

**Сценарий.** Зарегистрировать приложение, указать `REDIRECT_URI` = `<shop>/api/auth/<provider>/callback`,
войти, проверить создание пользователя и привязку к существующему аккаунту.

**Критерии приёмки.** `state` проверяется; повторный вход не создаёт дубль пользователя; аккаунты
объединяются по правилам `account_merge`.

**Текущий статус:** `BLOCKED_SECRETS`.

## 8. GitHub Actions

**Назначение.** CI, Docker, публикация релиза, деплой.

**Секреты (имена из workflow).** `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`,
`DEPLOY_PORT`, `HETZNER_API_TOKEN`, `WEBHOOK_BASE_URL`, `LOAD_TARGET_URL`, ключи мобильной подписи
(`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`,
`IOS_CERTIFICATE_BASE64`, `IOS_CERTIFICATE_PASSWORD`, `IOS_TEAM_ID`, `IOS_ADMIN_PROFILE_BASE64`,
`IOS_USER_PROFILE_BASE64`, `IOS_USER_PUSH_PROFILE_BASE64`, `IOS_USER_TUNNEL_PROFILE_BASE64`),
платёжные ключи из §6.

**Переменные.** `vars.AUTO_DEPLOY`, `vars.IOS_EXPORT_METHOD`.

**Что проверено без секретов.** Синтаксис всех 13 workflow разобран; шаги `ci.yml` повторены локально
(lint, shell, compile, документация, карта проекта, тесты, typecheck, build). Статус: `PASS`.

**Сценарий.** Push в ветку → PR → проверить зелёный CI → merge в `main` → `publish-release.yml`
публикует релиз только при успешных `ci.yml` и `docker.yml` на том же коммите.

**Критерии приёмки.** CI зелёный; релиз не публикуется при падении проверок; секреты не видны в логах.

**Текущий статус:** `BLOCKED_ACCESS` (нет прав на запись в чужой репозиторий; свои — есть).

## 9. Claude Code / автоматизация

**Назначение.** Ночные проверки дорожной карты, генерация отчётов.

Файлы: `.github/workflows/ci.yml` (существующий). Отдельный `claude-roadmap.yml` добавлен этим
релизом — см. [CLAUDE_GITHUB_AUTOMATION.md](CLAUDE_GITHUB_AUTOMATION.md). Секрет `ANTHROPIC_API_KEY`
для запуска не требуется: workflow выполняет только детерминированные проверки репозитория.

**Текущий статус:** `NOT_APPLICABLE` для внешних ключей; проверки репозитория — `PASS`.

## 10. Docker и установщик

```bash
cp .env.example .env && cp support-pro/.env.example support-pro/.env
docker compose -f docker-compose.yml config --quiet
docker compose --env-file .env.test -f docker-compose.test.yml config --quiet
bash -n deploy/install-vps.sh
```

В песочнице Docker отсутствует → `BLOCKED_ACCESS`. YAML разобран программно: 17 сервисов в
`docker-compose.yml`, 7 в test, 3 в integration, 9 в `support-pro` — структура валидна. Установщик
проходит `bash -n`.

**Сценарий.** Установка на чистый VPS по [INSTALL.md](../INSTALL.md), затем повторная установка
(должна сохранять `.env` и данные).

**Текущий статус:** `BLOCKED_ACCESS`.

## 11. Обновление и ночное автообновление

См. [AUTO_UPDATE_TESTING.md](AUTO_UPDATE_TESTING.md) — полная матрица из 19 сценариев.
В репозитории проходят сценарии 1, 2, 3, 4, 5, 6, 7, 13, 14, 15, 17, 19; сценарии с реальным
systemd — `BLOCKED_ACCESS`.

## 12. Android и iOS

**Исходники есть.** `mobile/android-user`, `mobile/android-admin`, `mobile/ios-user`,
`mobile/ios-admin`; артефакты `mobile/store/{app-store,google-play,rustore}`.

```bash
cd mobile/android-user && bash gradlew assembleDebug --no-daemon
xcodebuild -project mobile/ios-user/VpnShopUser.xcodeproj -scheme VpnShopUser \
  -sdk iphonesimulator -configuration Debug CODE_SIGNING_ALLOWED=NO build
```

В песочнице нет Android SDK и Xcode → `BLOCKED_ACCESS`. Публикация в Google Play и App Store не
выполнялась: в релизе `v28.57.0` лежат **unsigned** сборки (`corgi_lusi_android_user_3_4_0_unsigned.apk`
и аналоги). Ссылок на магазины приложений в проекте нет.

**Текущий статус:** `BLOCKED_ACCESS`, подпись — `BLOCKED_SECRETS`.

## 13. Push-уведомления (FCM / APNs)

**Переменные.** `FCM_PROJECT_ID`, `FCM_SERVICE_ACCOUNT_JSON`, `APNS_KEY_ID`, `APNS_TEAM_ID`,
`APNS_BUNDLE_ID`, `APNS_PRIVATE_KEY`, `APNS_ENVIRONMENT`.

Без ключей уведомления не отправляются, ошибка обрабатывается и логируется. Статус: `BLOCKED_SECRETS`.

## 14. Сводка текущего состояния

| Группа | Логика (без секретов) | Живой прогон |
| --- | --- | --- |
| Remnawave | PASS | BLOCKED_SECRETS |
| Reverse proxy | — | BLOCKED_ACCESS |
| Telegram-бот | PASS | BLOCKED_SECRETS |
| Mini App (`initData`) | PASS | BLOCKED_SECRETS |
| Платежи (15 провайдеров) | PASS | BLOCKED_SECRETS |
| OAuth Яндекс/VK | PASS | BLOCKED_SECRETS |
| GitHub Actions | PASS | BLOCKED_ACCESS |
| Claude Code / автоматизация | PASS | NOT_APPLICABLE |
| Docker / установщик | NOT_RUN (нет Docker) | BLOCKED_ACCESS |
| Обновление / автообновление | PASS | BLOCKED_ACCESS |
| Android / iOS | NOT_RUN | BLOCKED_ACCESS |
| FCM / APNs | PASS | BLOCKED_SECRETS |

## 15. Порядок действий после выдачи секретов

1. Заполнить `.env` (не коммитить).
2. `cd backend && python -m pytest -q ../tests` — базовая линия должна остаться зелёной.
3. Remnawave: `tests/live/test_remnawave_live.py`.
4. Платежи: `tests/live/test_payments_live.py` с минимальной суммой.
5. Telegram: `/start` и покупка в тестовом боте.
6. Mini App: вход и проверка отказа при подделанном `initData`.
7. Docker: `docker compose config --quiet`, затем установка на тестовый VPS.
8. Автообновление: матрица [AUTO_UPDATE_TESTING.md](AUTO_UPDATE_TESTING.md).
9. Зафиксировать результат каждого пункта в таблице §14, заменив статус на `PASS`/`FAIL`.

## 16. Безопасная очистка

```bash
# тестовые данные в БД
# использовать отдельную БД на время проверок:
export DATABASE_URL='sqlite+aiosqlite:///./acceptance.db'

# удалить локальные артефакты
rm -f acceptance.db local.db
rm -rf /tmp/media/acceptance-*

# тестовые релизы GitHub — только созданные вами
gh release delete vX.Y.Z --yes
```

Не удаляйте `.rollback` на сервере и не отзывайте `.env` без резервной копии.

Дата последней проверки логики в репозитории: `2026-10-31` (песочница, `v28.57.0`).
