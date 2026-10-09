# Диагностика и мониторинг нод Remnawave

## Быстрая проверка

1. Откройте админ-панель → «Ноды» и проверьте `online`, latency, CPU/RAM и последнее успешное измерение.
2. Сверьте очередь provisioning: зависшие операции должны иметь retry state и correlation ID.
3. Проверьте события audit и worker alerts за тот же интервал.
4. Не выдавайте новую подписку на ноду в состоянии `offline` или `degraded`, пока health-check не восстановлен.

## CLI-проверка окружения

```bash
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 worker
bash scripts/test-up.sh
```

## Классификация инцидентов

| Сигнал | Действие |
| --- | --- |
| `offline` | остановить маршрутизацию новых entitlement-операций, отправить alert владельцу |
| `degraded` | сохранить ноду для существующих клиентов, ограничить новые выдачи и наблюдать retry |
| рост latency | проверить сеть, нагрузку и лимиты Remnawave; не удалять ноду автоматически |
| webhook error | проверить подпись, идемпотентный ключ и ledger; повторить только безопасный replay |
| worker backlog | проверить Redis/DB, возраст oldest job и lock timeout; не очищать очередь вручную |

## Эскалация

Сохраняйте timestamp, node ID, operation ID, HTTP status, correlation ID и audit event. Секреты, токены и полные конфиги в тикет не копируйте.

