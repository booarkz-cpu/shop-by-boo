# Архитектура

Набор документов, который требует мастер-промпт v6 (`REQ-ARCH-0009` – `0020`).
Документы описывают то, что есть в коде. Где требования промпта не выполнены, это названо прямо.

| Документ | О чём | Как ведётся |
| --- | --- | --- |
| [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) | Что это за система, из чего состоит, кто ею пользуется | Вручную |
| [CONTEXT_MAP.md](CONTEXT_MAP.md) | Предметные области и связи между ними | Вручную |
| [DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md) | Где проходят границы на деле и чего не хватает | Вручную |
| [CONTAINER_DIAGRAM.md](CONTAINER_DIAGRAM.md) | Службы, сети, тома | Генерируется из `docker-compose.yml` |
| [DEPLOYMENT_TOPOLOGY.md](DEPLOYMENT_TOPOLOGY.md) | Серверы и что на каком стоит | Вручную |
| [DATA_FLOW.md](DATA_FLOW.md) | Главные потоки данных | Вручную |
| [API_CATALOG.md](API_CATALOG.md) | API по областям | Генерируется из каталога маршрутов |
| [EVENT_CATALOG.md](EVENT_CATALOG.md) | События: входящие, внутренние, исходящие | Вручную |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Модель угроз | Ссылка на основной документ |
| [ADR/](ADR/README.md) | Записи архитектурных решений | По одной на решение |

Генерируемые документы проверяет CI: `python3 scripts/generate-architecture-docs.py --check`.

Более ранний обзор — [PROJECT_ARCHITECTURE.md](../PROJECT_ARCHITECTURE.md); числа в нём относятся к его дате.
