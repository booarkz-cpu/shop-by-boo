> Актуальная инструкция дистрибутива v28.38.0. Runtime/API `21.5.1`, head магазина `0081_subscription_proxy`, Support Pro `0008`.

# 05. Поддержка

## Для чего

Клиент пишет в поддержку из кабинета, Mini App или бота (`/support`). Ответить можно двумя способами:

- в самой админке магазина;
- в **Support Pro** — отдельном центре поддержки с очередями, назначением, SLA, шаблонами, отчётами и внутренними заметками.

Support Pro дополнительно принимает обращения по email (IMAP или собственный приём почты магазина) и из Zendesk/Freshdesk. История и файлы хранятся в магазине. Support Pro видит их через защищённый мост.

## Где и кто

| Раздел | Что делает | Права |
| --- | --- | --- |
| **Пользователи → Обращения клиентов** | Открытые, решённые и все обращения; ответ с вложениями; объединение и разделение обращений одного клиента | чтение `support.read` (все роли), ответ `support.write` (оператор, администратор) |
| **Пользователи → Support Pro** | Состояние Support Pro (настроен, онлайн), кнопка «Открыть Support Pro» (вход по одноразовому SSO на 60 секунд) | `read` |
| `https://support.ДОМЕН` | Сама панель Support Pro | Свои роли: admin, manager, senior_operator, operator, viewer, auditor |

## Настройка

### Встроенный Support Pro

Установщик уже всё связал:

- `SUPPORT_PRO_URL`, `SUPPORT_PRO_SSO_SECRET` и `SUPPORT_BRIDGE_TOKEN` в `.env` магазина;
- `SSO_SECRET`, `SHOP_BRIDGE_URL`, `SHOP_BRIDGE_TOKEN` в `support-pro/.env`;
- администратор Support Pro `admin` с паролем из вывода установки.

1. **Пользователи → Support Pro** → «Открыть Support Pro». Или войдите на `https://support.ДОМЕН` логином `admin`.
2. **Операции** (`/operations`): создайте команды и операторов, назначьте роли.
3. **SLA**: рабочие часы, часовой пояс, сроки первого ответа и решения для четырёх приоритетов. По умолчанию пн–пт 09:00–18:00 UTC.
4. Категории и шаблоны ответов (подстановки `{name}`, `{ticket_id}`).
5. По желанию — ИИ-подсказки: `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL` в `support-pro/.env`. Подсказки работают только по кнопке оператора, сами клиенту ничего не отправляют.
6. По желанию — антивирус для вложений. Запустите clamd рядом (например, контейнер `clamav/clamav`) и задайте в `support-pro/.env` `CLAMAV_HOST`, `CLAMAV_PORT` и `REQUIRE_ANTIVIRUS=true`. В самостоятельной установке Support Pro для этого есть профиль `docker compose --profile antivirus up -d`.

Если мост нужно пересоздать (например, после ручной правки `.env`):

```bash
cd /opt/vpn-shop
python3 scripts/configure-support-bridge.py --origin https://api.ДОМЕН --instance support-main --dry-run
python3 scripts/configure-support-bridge.py --origin https://api.ДОМЕН --instance support-main
docker compose up -d backend worker support_pro support_worker
```

### Email-канал

Письма клиентов становятся обращениями, ответы уходят письмом с сохранением цепочки. Есть два способа приёма.

**Способ A — ящик у провайдера (IMAP)**, в `support-pro/.env`:

```dotenv
EMAIL_ADDRESS=support@ДОМЕН
EMAIL_IMAP_HOST=imap.provider.example
EMAIL_IMAP_PORT=993
EMAIL_IMAP_SECURITY=ssl
EMAIL_IMAP_USER=support@ДОМЕН
EMAIL_IMAP_PASSWORD=...
EMAIL_SMTP_HOST=smtp.provider.example
EMAIL_SMTP_PORT=587
EMAIL_SMTP_SECURITY=starttls
EMAIL_SMTP_USER=support@ДОМЕН
EMAIL_SMTP_PASSWORD=...
```

**Способ B — собственный приём почты магазина.** IMAP не нужен:

- задайте одинаковый `MAIL_INBOUND_SECRET` в обоих `.env`;
- задайте маршрут `support@ДОМЕН=support` в `MAIL_RECEIVER_ROUTES` ([модуль 26](26-mail.md));
- для ответов клиентам всё равно нужен `EMAIL_SMTP_*`.

После правки: `docker compose up -d --force-recreate support_pro support_worker`.

### Zendesk или Freshdesk

```dotenv
HELPDESK_PROVIDER=zendesk          # или freshdesk
ZENDESK_SUBDOMAIN=acme
ZENDESK_EMAIL=agent@acme.example
ZENDESK_API_TOKEN=...
# FRESHDESK_DOMAIN=acme  FRESHDESK_API_KEY=...
HELPDESK_IMPORT_SINCE=2026-10-01   # пусто — последние 30 дней
```

Обращения внешнего helpdesk попадают в общую очередь Support Pro, ответы операторов уходят туда комментарием. Повторная синхронизация дублей не создаёт.

## Работа

1. Оператор берёт обращение из очереди «Без ответственного» или получает его автоназначением по нагрузке.
2. Отвечает, при необходимости прикрепляет файлы (в магазине — PNG/JPEG, PDF, TXT до 2 МБ, до трёх в сообщении).
3. Внутренние заметки видят только операторы, клиенту они не уходят.
4. Ответ оператора переводит обращение в «решено». Новое сообщение клиента снова его открывает.
5. Несколько обращений об одном можно объединить, а смешанное — разделить. Обе операции работают только внутри одного клиента и после предпросмотра ([регламент](../SUPPORT_TOPOLOGY_CURRENT.md)).
6. Отчёты Support Pro показывают время первого ответа и решения, соблюдение SLA и оценки 1–5. Есть экспорт в CSV.

## Проверка

1. Из кабинета тестового клиента создайте обращение с TXT-файлом.
2. Оно появляется и в **Обращениях клиентов**, и в Support Pro. Ответьте из Support Pro — ответ приходит в кабинет, обращение становится «решено».
3. Для email: письмо на адрес поддержки создаёт обращение, ответ приходит письмом.
4. `docker compose logs --tail=80 support_worker` — без ошибок моста.

## Проблемы

| Симптом | Причина | Что делать |
| --- | --- | --- |
| «SUPPORT_PRO_URL не задан» | Пустая переменная в `.env` магазина | Задайте `https://support.ДОМЕН`, перезапустите backend |
| Мост: HTTP 401 | Ключи в двух `.env` не совпадают | Запустите `configure-support-bridge.py` |
| Мост: HTTP 503 | `SUPPORT_BRIDGE_TOKEN` пуст в магазине | Задайте ключ скриптом |
| SSO не открывается | Секреты SSO разные или прошло больше 60 секунд | Совпадение `SUPPORT_PRO_SSO_SECRET` и `SSO_SECRET`; нажмите кнопку снова |
| Письма не становятся обращениями | Неверный IMAP или пустой `EMAIL_IMAP_HOST` | Логи `support_worker`, настройки ящика |
| Вложение отклонено | Антивирус обязателен, но недоступен | Проверьте контейнер `clamav` |

## API

Магазин: `GET /api/admin/support/tickets`, ответ и вложения — `/api/admin/support/...`, `GET /api/admin/support-pro/status`, `POST /api/admin/support-pro/sso`. Клиент: `/api/me/support/...`. Support Pro: `/live`, `/ready`, `/metrics`, `POST /email/inbound`.

## Подробнее

[Мост магазина и Support Pro](../WORKSPACE_SUPPORT_BRIDGE.md) · [Email-канал](../SUPPORT_EMAIL_CHANNEL_CURRENT.md) · [Zendesk/Freshdesk](../SUPPORT_HELPDESK_BRIDGE_CURRENT.md) · [Объединение и разделение](../SUPPORT_TOPOLOGY_CURRENT.md) · [История после объединения](../SUPPORT_REMOTE_HISTORY_CURRENT.md) · [Support Pro README](../../../support-pro/README.md).
