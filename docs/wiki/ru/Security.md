# Безопасность

- **2FA и подтверждение опасных действий.** Восстановление копий, администраторы, возвраты, терминал ноды, применение настроек и другие опасные действия требуют свежего кода 2FA (или пароля) — 10 минут, одна сессия.
- **История безопасности** — «Сессии → История безопасности»: входы, неудачные попытки с IP, подтверждения, смены ключей.
- **Секреты** не показываются после сохранения; SSH-ключи серверов магазин создаёт сам и может сменить кнопкой.
- **Журналы контейнеров** в браузере — секреты из `.env` заменены на `***`.
- **Мониторинг:** метрики безопасности в `/metrics` и правила Prometheus.

Подробно: [аудит безопасности](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/SECURITY_AUDIT.md), [секреты](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/SECRETS_MANAGEMENT.md), [реагирование на инциденты](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/INCIDENT_RESPONSE.md), [роли](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/RBAC.md).
