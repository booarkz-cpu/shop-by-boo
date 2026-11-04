# Безпека

- **2FA і підтвердження небезпечних дій.** Відновлення копій, адміністратори, повернення коштів, термінал ноди, застосування налаштувань та інші небезпечні дії потребують свіжого коду 2FA (або пароля) — 10 хвилин, одна сесія.
- **Історія безпеки** — «Сессии → История безопасности»: входи, невдалі спроби з IP, підтвердження, зміни ключів.
- **Секрети** не показуються після збереження; SSH-ключі серверів магазин створює сам і змінює кнопкою.
- **Журнали контейнерів** у браузері — секрети з `.env` замінені на `***`.
- **Моніторинг:** метрики безпеки в `/metrics` і правила Prometheus.

Докладніше (російською): [аудит безпеки](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/SECURITY_AUDIT.md), [секрети](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/SECRETS_MANAGEMENT.md), [реагування на інциденти](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/INCIDENT_RESPONSE.md), [ролі](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/RBAC.md).
