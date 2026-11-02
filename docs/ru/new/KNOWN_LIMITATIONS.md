# Известные ограничения

Что не может быть проверено или выполнено в текущей среде. Обновляется на каждом этапе.

| Ограничение | Причина | Статус | Что нужно |
| --- | --- | --- | --- |
| Живой Remnawave | нет `REMNAWAVE_URL` / `REMNAWAVE_TOKEN` | BLOCKED_SECRETS | Доступ к панели |
| Установка Remnawave на VPS | нет VPS и SSH-доступа | BLOCKED_EXTERNAL | VPS с SSH-ключом |
| Домены и TLS | нет домена и DNS | BLOCKED_EXTERNAL | Домен с управлением DNS |
| Telegram-бот и Mini App вживую | нет `BOT_TOKEN` | BLOCKED_SECRETS | Токен тестового бота |
| Живые платежи | нет ключей провайдеров; реальные деньги — только с разрешения владельца | BLOCKED_SECRETS | Ключи и разрешение |
| OAuth (Яндекс, VK, Google) вживую | нет client id / secret | BLOCKED_SECRETS | Ключи приложений |
| Сборка Android и iOS | нет Android SDK и Xcode в среде; сборки идут в CI | BLOCKED_EXTERNAL | — (CI) |
| Скачивание артефактов CI | хранилище артефактов GitHub закрыто политикой среды | BLOCKED_PERMISSIONS | — |
| Удаление и создание git-ссылок (теги, удаление веток) | закрыто политикой среды | BLOCKED_PERMISSIONS | Выполняет владелец |
