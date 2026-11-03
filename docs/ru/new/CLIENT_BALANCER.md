# Клиентский балансировщик

С v28.69.0 (этап 12). «Серверы → Расширения Remnawave → Страница подписки и шаблоны». Идея — `client_balancer` из `eGamesAPI/remnawave-reverse-proxy` (MIT, Copyright (c) 2025 eGames): у клиента одна запись в подписке вместо списка серверов, и Xray у клиента сам выбирает самую быструю ноду.

## 1. Как устроено

Балансировщик — часть шаблона подписки **Xray JSON** панели. Магазин добавляет в шаблон фрагмент:

```json
{
  "observatory": {"subjectSelector": ["proxy"], "probeUrl": "https://www.gstatic.com/generate_204", "probeInterval": "1m", "enableConcurrency": true},
  "routing": {
    "balancers": [{"tag": "Balancer", "selector": ["proxy"], "strategy": {"type": "leastPing"}, "fallbackTag": "direct"}],
    "rules": [{"network": "tcp,udp", "balancerTag": "Balancer"}]
  }
}
```

- `observatory` раз в минуту проверяет каждый сервер с тегом, начинающимся на `proxy`;
- балансировщик направляет трафик на сервер с наименьшей задержкой;
- если все серверы недоступны — `direct`.

Теги исходящих (`proxy…`) задаёт шаблон Xray JSON панели. Если в вашем шаблоне теги другие, поправьте `subjectSelector` и `selector`.

## 2. Как включить

1. «Новый шаблон» с типом `XRAY_JSON` или откройте существующий шаблон Xray JSON.
2. «Добавить клиентский балансировщик» — фрагмент добавляется в шаблон.
3. В правилах подписки ([SUBSCRIPTION_RULES](SUBSCRIPTION_RULES.md)) клиентам, которые понимают Xray JSON (Happ, v2RayTun, Streisand), отдайте ответ `XRAY_JSON`.

Клиенты со ссылками в Base64 (список серверов) балансировщика не получают: в этом формате его нет.

## 3. Проверено

- `tests/live/test_remnawave_live.py::test_extensions_plugins_srr_pages_and_templates` — настоящая панель принимает шаблон Xray JSON с балансировщиком.
- Выбор сервера у клиента — BLOCKED_EXTERNAL: нужны две ноды и клиент.
