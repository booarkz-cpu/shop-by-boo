# Плагины нод

С v28.69.0 (этап 12). Плагины — функция панели Remnawave 3.x (`/api/node-plugins`): панель хранит конфигурацию и отдаёт её нодам. Магазин управляет ими из «Серверы → Расширения Remnawave → Плагины нод». Общая схема — [REMNAWAVE_EXTENSIONS](REMNAWAVE_EXTENSIONS.md).

## 1. Что умеют

| Плагин | Ключ | Что делает | Основные поля |
| --- | --- | --- | --- |
| TorrentBlocker | `torrentBlocker` | Блокирует пользователя, у которого Xray заметил BitTorrent, на заданное время | `enabled`, `blockDuration` (секунды), `ignoreLists` (адреса-исключения), `includeRuleTags`, `webhookUrl` |
| Ingress Filter | `ingressFilter` | Не пускает к ноде соединения с перечисленных адресов | `enabled`, `blockedIps` (IP, CIDR или общий список `ext:…`) |
| Egress Filter | `egressFilter` | Не выпускает трафик к адресам и портам | `enabled`, `blockedIps`, `blockedPorts` (например 25, 465, 587 против спама) |
| Connection Drop | `connectionDrop` | Сбрасывает соединения пользователей, кроме белого списка | `enabled`, `whitelistIps` |

Схему конфигурации задаёт панель (`NodePluginEditorSchema` в remnawave/backend) и сама проверяет каждое сохранение. Ошибку проверки администратор видит в разделе.

## 2. Как пользоваться

1. «Создать плагин» — панель создаёт плагин с примером конфигурации, все функции выключены.
2. Флажки включают функции. Подробные поля — в JSON конфигурации плагина.
3. Флажки нод привязывают плагин к нодам (`activePluginUuid`). У ноды — один плагин; снять флажок — отвязать.
4. Удалить — плагин исчезает из панели.

Готовые фрагменты конфигурации — `GET /api/admin/rw/extensions/presets` → `plugins`.

## 3. Связь с другими функциями магазина

- «Торренты на узлах» (`backend/app/torrent_detection.py`, раздел «Торренты на узлах») — счётчики магазина без адресов пользователей. TorrentBlocker — блокировка на самой ноде. Их можно использовать вместе.
- Отчёты TorrentBlocker хранит панель (`/api/node-plugins/torrent-blocker`); вывод их в магазин — вместе с мониторингом на этапе 16.

## 4. Проверено

- `tests/test_rw_extensions.py` — тела запросов и привязка к ноде.
- `tests/live/test_remnawave_live.py::test_extensions_plugins_srr_pages_and_templates` — настоящая панель: создание, включение TorrentBlocker, отказ панели на неверное значение, привязка к ноде и отвязка, удаление.
- Работа плагина на ноде с живым трафиком — BLOCKED_EXTERNAL (нужен VPS).
