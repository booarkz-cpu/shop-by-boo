# Этап 1 — перепроверка инвентаризации (2026-11-02)

Этап 1 был выполнен 2026-11-01 (`docs/REFERENCE_REPOSITORIES.md`, `docs/CODE_REUSE_REGISTER.md`, `docs/TECH_STACK.md`, `docs/PROJECT_INVENTORY.md`, `docs/PROJECT_ARCHITECTURE.md`). Перепроверка: пять репозиториев заново склонированы во временную папку вне проекта (оригиналы не изменялись, код не запускался), выводы сверены с исходниками и с нашим кодом.

## Подтверждено

| Проверка | Результат |
| --- | --- |
| Доступность пяти репозиториев | все клонируются; HEAD совпадает с записанными в документе (`72bf224`, `93e6631`, `1a2d310`, `c9d3e41`, `9a8072e`) |
| Число файлов | 1397 / 252 / 2008 / 1104 / 146 — совпадает |
| `remnawave-admin` | AGPL-3.0 + §7 Plugin Exception; README: «теперь платный», последняя бесплатная версия 5.2.0 (`VERSION` = 5.2.0); CLA для двойного лицензирования |
| `remnawave-reverse-proxy` | MIT, Copyright (c) 2025 eGames; README: «NOT FOR PRODUCTION», «исключительно образовательные цели»; тестов нет |
| `bedolaga-bot` | Commons Clause v1.0 поверх MIT, Licensor Fr1ngg (`pyproject.toml`: `MIT` — без учёта Commons Clause) |
| `bedolaga-cabinet` | `package.json`: `AGPL-3.0` |
| `subscription-middleware` | файла лицензии для собственного кода нет; есть только лицензии сторонних ассетов (`admin/assets/LICENSE-qrcode.txt` и др.) |
| 33 функции «уже есть у нас» | все 33 найдены в нашем коде (модули, маршруты, разделы админки); 4 ссылки на файлы были неточными — исправлены |
| Переноса стороннего кода нет | подтверждено |

## Исправлено

| Где | Было | Стало (по факту) |
| --- | --- | --- |
| REFERENCE_REPOSITORIES, middleware | «тестов нет», «0» | 11 сценариев `tools/tests/t_*.php` + самотесты, запуск `php tools/test.php`, вне CI |
| REFERENCE_REPOSITORIES, remnawave-admin | 267 тестовых файлов | 270 (215 `test_*.py` + 55 `*.test/spec.ts(x)`) |
| REFERENCE_REPOSITORIES, remnawave-admin | только AGPL | README: версии ≤ 2.15.x остаются под MIT (устарели, не нужны) |
| REFERENCE_REPOSITORIES, bedolaga-cabinet | «AGPL-3.0 (Version 1, 14 January 2025)» как будто это версия AGPL | тело — стандартный AGPL v3, заголовок изменён автором; трактуем как AGPL-3.0 |
| REFERENCE_REPOSITORIES, вывод | «не может быть перенесена» ни одна строка | юридически возможно из reverse-proxy (MIT) и admin ≤ 2.15.x (MIT), но не нужно |
| REFERENCE_REPOSITORIES, PROJECT_INVENTORY | наш backend: 216 файлов, 1833 / 1825 тестов | 220 файлов, 2534 теста (`pytest --collect-only`) |
| CODE_REUSE_REGISTER | OAuth в `auth_api.py` | Яндекс — `main.py`, VK — `cabinet_api.py`, Google — `app_login.py` |
| CODE_REUSE_REGISTER | ограничение скорости в `node_terminal.py` | `scripts/node-agent.py` (`tc`, только при `AGENT_APPLY_TC=1`) |
| CODE_REUSE_REGISTER | мониторинг в каталоге `monitoring` (его нет) | `operations_api.py`, `ops_alerts.py`, `deploy/prometheus`, `deploy/grafana` |
| CODE_REUSE_REGISTER | S3 в `backup_verify.py` | `backups_api.py` (`boto3`) |

## Не проверялось

| Что | Почему |
| --- | --- |
| Запуск референсных проектов | не нужен для решения о переносе; root-скрипты reverse-proxy без аудита не запускаются по заданию |
| Код `remnawave-admin` ≤ 2.15.x | клон неглубокий; переносить его не планируется |

Итог: этап 1 — **PASS** (выводы о лицензиях и переносе подтверждены по исходникам; неточности в числах и путях исправлены).
