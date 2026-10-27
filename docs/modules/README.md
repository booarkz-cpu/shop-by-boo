# Архитектура модулей

Технические описания для разработчика: бизнес-логика, схемы данных, контракты API и диаграммы. Инструкции для владельца магазина по каждому разделу админки — [30 модулей](../ru/modules/README.md), установка — [INSTALLATION.md](../INSTALLATION.md).

| Документ | О чём |
| --- | --- |
| [bot_auth_and_routing.md](bot_auth_and_routing.md) | Вход клиентов и администраторов (Telegram, OAuth, сессии, PKCE для приложений, 2FA), команды бота и маршрутизация запросов |
| [billing_and_taxes.md](billing_and_taxes.md) | Оплата: checkout, webhook, выдача, возвраты, возврат в приложение; чеки в налоговую и сверка «Мой налог» |
| [remnawave_integration.md](remnawave_integration.md) | Клиент Remnawave, задания выдачи и пробного периода, повторы и идемпотентность, вебхуки панели |
| [android_architecture.md](android_architecture.md) | Клиентское приложение Android: макет из админки, встроенный VPN, батарея, push, вход, оплата |
| [ios_architecture.md](ios_architecture.md) | Клиентское приложение iOS: Network Extension, push с картинками, подпись и встраивание расширений |
| [analytics.md](analytics.md) | События приложений, воронка, push-кампании по расписанию и A/B-тесты |
| [auto_update_and_rollback.md](auto_update_and_rollback.md) | Автообновление с GitHub: агент на сервере, связь с админкой, снимки, откат, правила повторов |
| [zero_downtime.md](zero_downtime.md) | Обновление backend без простоя: standby-контейнер, Caddy `lb_policy first`, ограничения миграций |
| [redis_and_postgres.md](redis_and_postgres.md) | Что хранится в PostgreSQL и в Redis: очередь заданий, блокировки, кеш нод, FSM бота, лимиты |
| [account_sync.md](account_sync.md) | Единое состояние аккаунта для бота, Mini App, кабинета и приложений (`/api/me/sync`) |
| [anti_blocking.md](anti_blocking.md) | Ротация адресов API: подписанный список зеркал, доверие при первом входе, Gist |
| [split_tunneling.md](split_tunneling.md) | Российские сайты и приложения мимо VPN, управляемый список доменов, «Авто» по пингу |
| [i18n.md](i18n.md) | Языки бота, кабинета, админки и приложений; где строки и как выбирается язык |
| [ai_support.md](ai_support.md) | ИИ-черновики ответов поддержки по базе знаний: модель, запасной режим, API |
| [in_app_diagnostics.md](in_app_diagnostics.md) | Кнопка «Не работает VPN» в приложениях: проверки с телефона, причина и подсказки, тикет с отчётом |
| [unit_economics.md](unit_economics.md) | Источник привлечения клиента, расходы на рекламу, CAC и ROMI по источникам |

Общая схема:

```mermaid
flowchart TB
    subgraph clients["Клиенты"]
        BOT["Telegram-бот"]
        MA["Mini App"]
        CAB["Кабинет"]
        AND["Android"]
        IOS["iOS"]
    end
    subgraph backend["backend (FastAPI)"]
        AUTH["auth_api · admin_auth_api · app_login · cabinet_api"]
        PAY["payments_api · fiscal"]
        GROW["app_growth · app_funnel · push_campaigns · push"]
        RWC["remnawave · remnawave_events"]
        MAIN["main.py: ядро, общие помощники, остальные разделы"]
    end
    WORKER["worker.py: run_next_job, fiscal_scheduler, campaign_scheduler, push_scheduler"]
    DB[("PostgreSQL 18")]
    REDIS[("Redis 7")]
    RW["Remnawave"]
    PROV["ЮKassa · Platega · RollyPay · Stars"]
    TAX["«Мой налог» · АТОЛ · ЮKassa-чеки"]
    clients --> AUTH
    clients --> PAY
    AND --> GROW
    IOS --> GROW
    PAY --> PROV
    PROV -->|webhook| PAY
    PAY --> DB
    WORKER --> DB
    WORKER --> RW
    WORKER --> TAX
    RWC --> RW
    RW -->|webhook| RWC
    backend --> REDIS
```

Код backend: `main.py` — ядро и общие помощники; разделы вынесены в модули, которые читают имена ядра через `shop.<имя>` во время вызова (тесты и операторы, подменяющие `app.main`, продолжают на них влиять). Модуль, импортированный раньше `main`, передаёт свои имена в `main`, когда загрузится (`tests/test_main_split.py`).
