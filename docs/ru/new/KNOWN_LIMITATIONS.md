# Известные ограничения

Что не может быть проверено или выполнено в текущей среде. Обновляется на каждом этапе.

| Ограничение | Причина | Статус | Что нужно |
| --- | --- | --- | --- |
| Живой Remnawave | нет `REMNAWAVE_URL` / `REMNAWAVE_TOKEN` | BLOCKED_SECRETS | Доступ к панели |
| Установка Remnawave на VPS | нет VPS и SSH-доступа. Мастер (v28.66.0) проверен на поддельном SSH-сервере и на сервере CI | BLOCKED_EXTERNAL | VPS с SSH-ключом и домен |
| Домены и TLS | нет домена и DNS. On-demand TLS (v28.67.0) проверен в CI с внутренним CA Caddy; DNS-01 не поддерживается стандартным образом Caddy | BLOCKED_EXTERNAL | Домен с управлением DNS (лучше Cloudflare с токеном) |
| Telegram-бот вживую в CI | токен получен, но секрет `TELEGRAM_TEST_BOT_TOKEN` в GitHub Actions агенту недоступен для записи | BLOCKED_SECRETS | Владелец добавляет секрет: Settings → Secrets and variables → Actions |
| Живые платежи | нет ключей провайдеров; реальные деньги — только с разрешения владельца | BLOCKED_SECRETS | Ключи и разрешение |
| OAuth (Яндекс, VK, Google) вживую | нет client id / secret | BLOCKED_SECRETS | Ключи приложений |
| Сборка Android и iOS | нет Android SDK и Xcode в среде; сборки идут в CI | BLOCKED_EXTERNAL | — (CI) |
| Скачивание артефактов CI | хранилище артефактов GitHub закрыто политикой среды | BLOCKED_PERMISSIONS | — |
| Удаление и создание git-ссылок (теги, удаление веток) | закрыто политикой среды | BLOCKED_PERMISSIONS | Выполняет владелец |
