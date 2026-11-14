# Обновление безопасности до 20.0.14

Обновляйте backend, worker, web-интерфейсы и Support Pro согласованно. Старые Android/iOS клиенты больше не получают bearer при входе: соберите и распространите версии 2.14.0 из этого релиза. Подписанные магазинные сборки требуют ваших signing keys; они не входят в исходный ZIP.

## До обновления

1. Выберите окно обслуживания, создайте backup и проверьте восстановление на отдельном стенде. Сохраните `.env` отдельно с режимом `0600`: обычный rollback-архив намеренно не содержит секретов.
2. Создайте две отдельные администраторские учётные записи, включите MFA у обеих. После обновления restore через веб требует обеих. Экстренное offline-восстановление выполняет уполномоченный root VDS при остановленных writers; это не обходной HTTP endpoint.
3. Встроенный Support Pro использует ту же ingress-сеть и доверяет только Caddy. Отдельный Support использует `172.30.85.0/29`, nginx `.2` и app `.3`; при конфликте задайте согласованные `INGRESS_SUBNET`, `NGINX_INGRESS_IP`, `APP_INGRESS_IP` в его `.env`. Убедитесь, что сеть `172.30.84.0/29` свободна. Если занята, задайте согласованные `INGRESS_SUBNET`, `CADDY_INGRESS_IP`, `BACKEND_INGRESS_IP`, `SUPPORT_INGRESS_IP`. Они должны обозначать разные адреса в одной выделенной подсети. При нестандартном ingress задайте собственный точный `TRUSTED_PROXY_CIDRS` и измените Compose override: штатный Compose явно устанавливает `/32` Caddy.
4. Проверьте `SUPPORT_PRO_SSO_SECRET`: уникальный случайный секрет минимум 32 символа; example-placeholder запрещён. В отдельном Support Pro это `SSO_SECRET`.
5. Удалите частичные настройки неиспользуемых провайдеров. Используемым нужны все credentials и webhook secrets/IDs. YooKassa дополнительно требует актуальный список официальных публичных подсетей в `YOOKASSA_WEBHOOK_IP_ALLOWLIST`.

## Применение

Используйте штатный updater или установщик из проверенного релиза. Для существующей установки `infrastructure/deployment/build-production.sh` вызывает `scripts/harden-env.py` перед проверками и пересборкой. Скрипт:

- генерирует разные случайные `REDIS_PASSWORD` и `SUPPORT_REDIS_PASSWORD`, только если отсутствуют/являются example-placeholder;
- сохраняет существующий пароль Redis, в том числе в URL; конфликт URL и отдельного параметра вызовет отказ старта;
- очищает устаревший `MOBILE_CLIENT_KEY` и задаёт `MOBILE_REQUIRE_PROOF=false`;
- разделяет старый автоматически сгенерированный список frontend origins, сохраняя неизвестные пользовательские значения для явной проверки;
- записывает `.env` атомарно с правами `0600`, не печатает секреты.

Самостоятельно применить миграцию и проверить синтаксис:

```bash
cd /opt/vpn-shop
python3 scripts/harden-env.py
docker compose config --quiet
```

Не выводите полный `docker compose config` в публичный тикет: там разворачиваются секреты. Изменение `.env` само по себе не перезапускает службы. Завершите штатное обновление, чтобы Redis и все клиенты одновременно получили новый пароль.

`volume_init` при запуске выставит владельца 10001 для media, backups, Support uploads и данных Caddy. Это может занять время на большом томе. Root-задача завершится до запуска приложений. Не удаляйте volumes для «исправления» прав. У frontend nginx UID 101, у Caddy UID 10001. Низкие порты разрешены внутри их network namespace через `ip_unprivileged_port_start=0`, без выдачи root.

Если Support Pro развёрнут отдельно: сгенерируйте `REDIS_PASSWORD` в его `.env`, пересоздайте redis/app/worker/bot, установите владельца каталога `backups` в 10001:10001. Для nginx скопируйте `nginx/main.conf`, установите приватному TLS key группу 101 и режим 0640; обновлённые `install.sh` и `scripts/renew-cert.sh` делают это автоматически. Каталоги должны разрешать проход этой группе. Не делайте ключ общедоступным.

## CORS и native

В штатной установке web использует same-origin `/api`, поэтому оба списка CORS могут быть пустыми:

```dotenv
ADMIN_CORS_ORIGINS=
CABINET_CORS_ORIGINS=
MOBILE_CLIENT_KEY=
MOBILE_REQUIRE_PROOF=false
```

Если требуется отдельный API origin: в первом списке разрешён точный `https://ADMIN_DOMAIN`, во втором — точные `https://CABINET_DOMAIN`, `https://APP_DOMAIN`, `https://MINIAPP_DOMAIN`. Не добавляйте `*`, `null`, HTTP или неизвестные домены. Native использует `https://API_DOMAIN`, а не admin/cabinet host.

Протокол native: случайный verifier 43–128 RFC 7636 символов → base64url SHA-256 challenge в `X-Shop-Code-Challenge` при входе/регистрации → `authorization_code` → POST `/api/auth/mobile/token` с JSON `code`, `code_verifier` и тем же `X-Shop-Client`. Код истекает через 120 секунд, повторное использование запрещено. Запросы с браузерным `Origin`/`Sec-Fetch-Site` отвергаются. Не логируйте code, verifier, JWT и пароли.

## Приёмка на VDS

- `docker compose ps`: приложения healthy, `volume_init` завершился с кодом 0. Проверить UID приложений через `docker compose exec -T backend id -u` и аналогично frontend/Support. Не путать UID процесса `docker exec` vendor Redis/Postgres с UID их daemon.
- `docker compose exec -T redis redis-cli ping` и аналогично `support_redis` должны вернуть `NOAUTH`. AUTH-healthcheck обоих контейнеров должен оставаться healthy. Не передавайте пароль параметром `redis-cli -a` в журналируемой команде.
- Порты 5432, 6379, 8000 не доступны с внешней машины. Только Caddy принимает HTTP(S). Внешний клиент не должен менять свой IP в rate-limit/allowlist, подставляя XFF. Если перед Caddy стоит CDN, отдельно настройте подтверждённые ingress-адреса CDN; не доверяйте любому private range.
- Проверить preflight с разрешённого admin origin и с постороннего origin. Постороннему origin нет `Access-Control-Allow-Origin`; cabinet origin не получает admin CORS. `/api/auth/mobile/token` не выдаёт CORS и отклоняет browser headers.
- Проверить вход/выход web и новых native-клиентов; неверный verifier, просроченный/повторный code должны отклоняться. Повторно войти после миграции, старые приложения заменить.
- В Support Pro открыть SSO кнопкой: новая вкладка, POST `/sso`, нет token в URL, viewer не становится admin. Повтор того же token запрещён.
- В тестовом CMS body вставить `<img src=x onerror=alert(1)>`: строка должна отображаться текстом, скрипт не выполняется. В production не проводить атаки на покупателей.
- На отдельном стенде временно остановить Redis: обычный rate limiter не превращает первый запрос каждого клиента в 429, но финансовые locks/one-time auth остаются недоступны. Затем восстановить Redis и проверить health.

## Restore с двумя администраторами

1. Первый admin нажимает «Запросить restore», вводит MFA и передаёт ID второму admin.
2. Второй admin проверяет backup ID, SHA-256, дату и последствия; нажимает «Подтвердить restore», вводит ID и собственную MFA.
3. Первый admin в течение 10 минут нажимает Restore, вводит тот же ID и свежую MFA, подтверждает перезапись. Повторное применение/самоподтверждение/смена checksum запрещены. При ошибке требуется новый запрос.

API: POST `/api/admin/backups/{id}/restore/request` (`otp`), `/restore/approve` (`approval_id`, `otp`), `/restore` (`approval_id`, `otp`, `confirm: "RESTORE"`). Параметры — JSON body; стандартные admin session и CSRF сохраняются. Записи находятся в `audit_logs`, `BACKUPS_DIR/restore-audit.jsonl` и stdout; отправляйте журналы на отдельный сервер.

Реальные платежи по-прежнему закрыты production gate до полноценного E2E v2. Не подменяйте доказательства и не изменяйте gate напрямую в БД.
