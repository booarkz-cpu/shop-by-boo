# Сводный аудит безопасности — 20.0.14

Дата: 26 сентября 2026. База: 20.0.13. Это исправления исходников и проверяемых сценариев, а не сертификат отсутствия уязвимостей. Доступ к рабочему VDS, его `.env`, сетям, сертификатам и реальным платёжным кабинетам в ходе этого аудита не предоставлялся.

## Результаты по 19 пунктам

| № | Проблема | Изменение / способ проверки |
| --- | --- | --- |
| 1–2 | Общий мобильный ключ и отсутствие production gate | Общий ключ удалён из клиентов и defaults. Production отвергает старый публичный ключ и legacy HMAC. Android/iOS 2.14.0 используют отдельный случайный verifier для каждого входа, S256 challenge и одноразовый зашифрованный код на 120 секунд. |
| 3 | Browser CORS и bearer в JSON | Вход native возвращает код, не JWT. Обмен запрещён при любом `Origin`/`Sec-Fetch-Site`, в production принимается только на `API_DOMAIN`. CORS разделён между admin/cabinet; mobile exchange не имеет CORS. Веб-сессии используют HttpOnly cookie. |
| 4 | RollyPay с пустым signing secret | Класс провайдера использует общий fail-closed verifier. Для маршрутизации нужны API key и signing secret. Проверки непустого секрета и timestamp обязательны. |
| 5–6 | Redis без пароля | Backend, worker и Support Pro используют `REDIS_PASSWORD`; противоречие паролю в URL вызывает ошибку. Оба Redis в Compose требуют AUTH, не публикуют порт на хост. Installer генерирует разные пароли. |
| 7 | Все запросы получают 429 при отказе Redis | Rate limit использует ограниченный по памяти локальный fixed-window fallback. Это лимит на процесс: при нескольких workers суммарный аварийный предел выше. Платёжные locks, SSO replay и обмен кодов остаются fail-closed. Redis по-прежнему обязателен для запуска приложения. |
| 8 | Доверие всем private IP | Приложение доверяет только `TRUSTED_PROXY_CIDRS`. Uvicorn не переписывает peer из headers. Caddy и backend соединяются отдельной ingress-сетью с закреплёнными IP; Compose доверяет только IP Caddy `/32`. |
| 9 | Разные механизмы Platega | Класс и endpoint используют официальный `X-MerchantId` + `X-Secret`, constant-time comparison, fail-closed, повторную проверку состояния/суммы/валюты/order через API и дедупликацию. Выдуманный HMAC или timestamp не добавлен: провайдер их не присылает. |
| 10 | Stripe/PayPal без event dedupe | После аутентификации требуется ID события. Атомарный claim в PostgreSQL предшествует бизнес-действиям; завершённые события пропускаются, неуспешные допускают повтор. Есть конкурентный тест claim. |
| 11 | Runtime `exec(compile(parts))` | `services/backend/app/main.py` — обычный полный исходный модуль. Фрагменты `main_src` удалены. Python компилируется непосредственно в CI; дополнительная сборка не нужна. |
| 12 | SSO token в URL | Слабый/default SSO secret отклоняется. POST form вместо query string; TTL ≤60 секунд, одноразовое поглощение Redis, `Referrer-Policy: no-referrer`. Дополнительно устранено повышение всех ролей до admin: роль сохраняется, конфликт с существующей локальной ролью отклоняется. |
| 13 | Root runtime | Backend/bot/Support уже имели непривилегированного пользователя. Теперь frontend nginx и Caddy тоже запускаются с явным UID, без capabilities. Standalone Support nginx/backup также непривилегированные. См. исключения и миграцию volumes ниже. |
| 14 | HTML из CMS | Cabinet выводит `body` как React text с сохранением переносов строк. `dangerouslySetInnerHTML` для CMS удалён; HTML отображается текстом. |
| 15 | SSRF, private IP, rebinding | Backend уже проверял HTTPS/public IP и подключался к проверенному literal IP. Такой же transport применяется к исходящим Support webhooks; redirects и proxy env выключены, сохраняется TLS SNI исходного hostname. Тесты проверяют localhost, RFC1918, metadata, IPv6 и единственное DNS-разрешение. |
| 16 | Фактический production CORS | Добавлена валидация точных HTTPS origins по назначению доменов; wildcard/null запрещены. Реальная конфигурация VDS не проверена — требуется приёмка оператором. |
| 17 | IP allowlist за ingress | Caddy перезаписывает XFF, backend принимает его только от закреплённого peer; порт backend не опубликован. Реальная доступность портов VDS и поведение внешнего CDN требуют проверки на месте. |
| 18 | Неполные настройки провайдеров | Production startup отвергает частично заданные YooKassa, Platega, RollyPay, Stripe, PayPal; для YooKassa обязательны публичный IP allowlist и доверенный ingress. Все поля пустые — провайдер выключен. |
| 19 | Restore через backups.write | Новый `backups.restore`, только роль admin. Запрос и независимое подтверждение требуют MFA. Разрешение связано с backup ID/SHA-256, живёт 10 минут и атомарно поглощается один раз. OTP передаётся в JSON. Аудит — БД + файл на backup volume + журнал процесса. |

Официальный протокол Platega: [callback об изменении статуса](https://docs.platega.com/%D0%BA%D0%BE%D0%BB%D0%B1%D1%8D%D0%BA%D0%B8-%D0%BE%D0%B1%D1%89%D0%B0%D1%8F-%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D1%8F-2499110m0). Секретный header требует HTTPS. В протоколе RollyPay текущего адаптера timestamp проверяется отдельно от HMAC тела; защиту от повторных финансовых действий обеспечивает дедупликация, а не неподписанный timestamp.

## Ограничения модели безопасности

PKCE связывает ответ входа с verifier конкретной попытки. Это не аттестация официального приложения, не per-device аппаратный ключ и не полноценный OAuth authorization server. Пользователь по-прежнему обязан предъявить пароль и MFA, если она включена. Знание имени `X-Shop-Client` не заменяет эти проверки. Не храните общий application secret в APK/IPA.

При отказе Redis уже работающий процесс продолжает локальное ограничение запросов. Операции, которым нужна одноразовость или распределённая блокировка, могут отвечать 503; намеренного fail-open для финансовых действий нет.

`volume_init` — отдельная краткоживущая root-задача без сети для изменения владельцев volumes. PostgreSQL и Redis используют штатные entrypoint, которые под root подготавливают каталог и затем запускают daemon под своим UID. Это не root-серверы приложения. Не меняйте UID vendor images без проверки прав существующих volumes. Опциональный ClamAV управляет собственными привилегиями; его образ отдельно не проходил runtime-приёмку этого релиза.

Аудит restore на томе не является WORM-хранилищем: root хоста или скомпрометированный процесс с правом записи может его изменить. Отправляйте stdout в удалённое хранилище журналов. Four-eyes защищает штатный restore API; полномочия root VDS и администраторов, способных создавать новые учётные записи, требуют организационного контроля.

## Воспроизводимые проверки

```bash
APP_ENV=test python -m pytest -q tests
(cd services/support-pro && python -m pytest -q tests)
for app in admin cabinet miniapp; do (cd "$app" && npm ci && npm run typecheck && npm run build); done
```

PostgreSQL-тесты требуют `AUDIT_TEST_DATABASE_URL` на отдельной тестовой БД. CI выполняет миграции, конкурентные финансовые/restore/event тесты, dependency audit, Compose validation, запуск непривилегированных контейнеров с Redis AUTH, Android debug и iOS simulator builds. Эти проверки не заменяют end-to-end тест с реальным провайдером или DAST на VDS. Сборки native в CI не являются подписанными магазинными APK/IPA.

Предыдущий production payment gate сохраняется: полноценный staging E2E v2 пока не реализован, открытие реальных платежей остаётся закрытым. Этот security release не обходит gate.

Инструкция обновления и проверки окружения: [SECURITY_UPGRADE_20_0_14.md](SECURITY_UPGRADE_20_0_14.md).
