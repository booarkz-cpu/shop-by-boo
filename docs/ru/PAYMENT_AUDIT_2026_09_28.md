# Аудит платежного пути v20.0.18 — 28.09.2026

Проверены исходники на `main` (`10456e5f37e06d4ebf2140abbe90a669a27c78d3`), формат запросов по опубликованной документации провайдеров и локальные контрактные тесты. Фактического запуска на VDS, настоящего sandbox webhook, возврата или продакшен списания не было. «Всё проверено» на реальном окружении утверждать нельзя.

| Приоритет | Обнаружено | Место | Действие / состояние |
| --- | --- | --- | --- |
| Блокер | Нет полного E2E v2. Runner ставит `full_e2e=false`, `contract_version=1`; gate требует v2; кнопка в интерфейсе выключена. Обычный внешний checkout на staging тоже требует gate и получает 503. | `backend/app/main.py`: checkout, `_run_staging_e2e`, `production_payment_gate`; `scripts/staging-e2e.sh`; `admin/src/main_src/part-07*` | Нужна разработка v2, связанное серверное доказательство оплаты/webhook/выдачи/дубля/возврата/отзыва. Текущий запрет сохранён. |
| Высокий | Прежний runbook советовал сохранять E2E в staging админке, тогда как production gate читает **production DB**. Runner локален production backend и только часть запросов отправляет наружу на staging. | `backend/app/main.py`: `_staging_config`, `_run_staging_e2e`, `production_payments_allowed`; прежний `STAGING_VDS_E2E_OPERATOR_20_0_18.md` | Исправлена инструкция; архитектуру runner v2 нужно явно развести по средам и не применять тестовые ключи к production checkout. |
| Высокий | RollyPay использовал Bearer вместо `X-API-Key`/`X-Nonce`, ошибочные `currency`/`return_url`, не находил `pay_url`; проверка webhook подписывала только body вместо `timestamp.body`. | `backend/app/payments.py`: `RollyPayProvider`, `_checkout`, `verify_rollypay` | Исправлены create, status, verify, sandbox read/create и проверка подписи; добавлены контрактные тесты. Требуется реальный тест с терминалом. |
| Высокий | Platega create обращался к `/api/payment` с плоскими `amount`/`currency`, status и amount читались не по документированной схеме. | `backend/app/payments.py`: `PlategaProvider`, staging helpers | Исправлены create `/v2/transaction/process`, GET `/transaction/{id}`, вложенное `paymentDetails` и payload; добавлены тесты. Требуется проверка на доступном тестовом терминале. |
| Высокий | При `APP_ENV=production` конфигурация принимала `ROLLYPAY_TEST_MODE=true`: будущая открытая маршрутизация могла выдавать услугу за тестовую оплату. | `backend/app/runtime_security.py` | Production теперь отказывается запускаться с этим флагом; добавлен тест. Перед развёртыванием владельцу нужно убедиться, что флаг false. |
| Высокий | Возвраты Platega и RollyPay опираются на произвольные URL и неподтверждённую семантику. RollyPay sandbox документирован без возвратов; Platega cancel может возвращать `accepted:false` и требовать ручного действия. | `backend/app/payments.py`: `refund`, `get_refund_status`; staging config | **Открытый блокер:** не считать HTTP 200 возвратом; согласовать API и sandbox refund с провайдером, проверить end to end, реализовать корректный учёт состояний. Не вводить фиктивные URL. |
| Высокий | Webhook Platega/RollyPay и YooKassa обрабатывает успешную оплату, но не входящие refund/chargeback. При внешнем возврате доступ может остаться активен без административного запроса в магазине. | `backend/app/main.py`: webhook handlers | **Открытый блокер:** реализовать подтверждённые сценарии отзыва/сверки и тесты на возврат/оспаривание. Пока gate закрыт. |
| Средний | Тест v1 опрашивает provider и Remnawave, но не создаёт локальный `Payment`, не получает настоящий webhook, не проверяет подписку/повторную доставку/отзыв. | `scripts/staging-e2e.sh`, `backend/app/main.py` | Не считать `[PASS]` допуском; будущий v2 должен проверять полную цепочку. |

## Проверка изменений

`python -m compileall -q backend/app tests/test_provider_contract_20260928.py`; `uv run --no-project --with pytest --with pytest-asyncio --with-requirements backend/requirements.txt pytest -q tests` — 485 passed, 10 skipped (локальный прогон). Четыре старых тестовых ответа приведены к документированным полям провайдеров; ещё один тест теперь передаёт hostname в mock-запрос. Эти тесты имитируют ответы по документации и не заменяют договорный тест на реальном терминале. После публикации PR необходимо дождаться CI и устранить регрессии.

## Основание для форматов API

- YooKassa: https://yookassa.ru/developers/using-api/webhooks и https://yookassa.ru/developers/payment-acceptance/testing-and-going-live/testing
- Platega: [документация](https://docs.platega.io/) — разделы «создание платёжной ссылки без заданного метода» и «отмена транзакции» (глубокие ссылки на разделы меняются при обновлении справки, поэтому приведена точка входа)
- RollyPay: https://docs.rollypay.io/api/authentication/ , https://docs.rollypay.io/api/payments/ , https://docs.rollypay.io/api/callbacks/ , https://docs.rollypay.io/api/testing/

Пути в этом списке сверяйте с актуальной официальной документацией перед работой с деньгами; они не являются доказательством доступности конкретного тестового терминала. Пошаговые действия владельца: [PAYMENTS_VDS_BEGINNER_2026_09_28.md](PAYMENTS_VDS_BEGINNER_2026_09_28.md).
