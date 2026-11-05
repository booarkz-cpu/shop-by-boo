# Платёжная система: что реализовано (этап 14)

Состояние на 2026-11-04, выпуск v28.85.0. Проверено по коду, а не по списку. Живые платежи не проводились: ключей sandbox нет, реальные деньги — только с разрешения владельца. Поэтому у каждой кассы живая проверка — `BLOCKED_SECRETS`.

## Как устроен платёж

1. **Заказ.** `POST /api/payments/create` (`payments_api.py`) сначала проверяет:
   - тариф и цену страны;
   - промокод или акцию и скидку уровня;
   - оценку риска.

   Затем записывает `Payment` со статусом `creating` и уникальным `order_id` и только после этого вызывает кассу. Если касса не ответила, заказ остаётся `creating` / `creation_unknown`, а сверка решает его судьбу. Повторное создание с тем же `Idempotency-Key` возвращает тот же заказ.
2. **Очередь касс.** Касс несколько, у каждой свой приоритет («Кассы»). Касса без ключей в очереди просто пропускается, остальные работают (`configured_map`, `payment_policy.routing_names`). Касса, которая не прошла пробу или отказала несколько раз подряд, временно выводится из очереди (`gateway_ops.py`, `PaymentProviderHealth.circuit_open_until`).
3. **Уведомление.** Это только подсказка. Каждый обработчик сначала проверяет подпись или секрет уведомления, затем сверяет:
   - касса заказа совпадает;
   - сумма совпадает с суммой заказа;
   - касса подтверждает оплату при повторном запросе к её API (`verify_succeeded`: статус, сумма, валюта, номер заказа).

   Без подтверждения ответ 503, и касса пришлёт уведомление снова.
4. **Один раз.** Событие кассы регистрируется в `payment_provider_events` (`register_provider_event`, уникальность «касса + событие»). Повторное и запоздавшее уведомление ничего не выдаёт второй раз. Неудачная выдача остаётся `retry` и берётся при следующем уведомлении.
5. **Выдача.** `_confirm_and_fulfill_payment` под блокировкой пользователя создаёт или продлевает пользователя в Remnawave. Затем она записывает финансовый журнал, чек (54-ФЗ, `fiscal.py`), реферальные начисления и уровень лояльности.
6. **Сверка.** `/api/admin/payments/reconcile` и фоновые задачи перечитывают зависшие заказы у касс. Отчёт «уведомление не пришло» показывает оплаты, которые нашла сверка, а касса о них не сообщила.
7. **Отмена, истечение, ошибка.** Неоплаченные заказы закрываются по статусу кассы, подписка не выдаётся.
8. **Возврат.** Возврат через API кассы есть там, где касса его даёт (см. таблицу), иначе он делается в кабинете кассы. Возврат, сделанный в кабинете кассы, магазин перечитывает и отзывает доступ (`_external_refund`). Неполный возврат доступ не отзывает, а записывается для оператора.

## Кассы и способы оплаты

| Касса | Код | Подпись уведомления | Подтверждение перед выдачей | Возврат через API | Автоплатёж | Sandbox | Тесты | Живая проверка |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| YooKassa | `payments.py` | список IP ЮKassa | `GET /payments/{id}` | да | да | тестовый магазин (свои shop_id и ключ) | `test_behaviour_payments*`, `test_money_review` | BLOCKED_SECRETS |
| Platega | `payments.py` | X-MerchantId + X-Secret | API статуса | да | нет | нет (по документации кассы) | `test_behaviour_payments*` | BLOCKED_SECRETS |
| RollyPay | `payments.py` | X-Signature (HMAC) + время | API статуса | да | нет | `ROLLYPAY_TEST_MODE` (только не в production) | `test_behaviour_payments*` | BLOCKED_SECRETS |
| CryptoBot | `payments.py` | crypto-pay-api-signature (HMAC-SHA256) | `getInvoices` | нет | нет | сеть `testnet` в настройках | `test_cryptobot.py` | BLOCKED_SECRETS |
| Freekassa | `payments.py` | MD5-подпись + список IP | API заказа | нет | нет | нет | `test_behaviour_payments*` | BLOCKED_SECRETS |
| Crypto (шлюз) | `payment_platform.py` | X-Signature + X-Timestamp | API шлюза | нет | нет | — | `test_behaviour_store_and_webhooks.py` | BLOCKED_SECRETS |
| CloudPayments | `gateways/cloudpayments.py` | Content-HMAC (HMAC-SHA256) | `POST /payments/find` | да | да (токен карты) | тестовый сайт CloudPayments | `test_payments_extra.py`, `test_cloudpayments_refund_recurring.py`, `test_payment_contract.py` | BLOCKED_SECRETS |
| Lava | `gateways/lava.py` | Authorization (HMAC-SHA256) | `POST /business/invoice/status` | нет | нет | нет | `test_payments_extra.py`, `test_payment_contract.py` | BLOCKED_SECRETS |
| Pal24 | `gateways/pal24.py` | SignatureValue (MD5) | `GET /bill/status` | нет | нет | нет | `test_payments_pal24_mulenpay.py`, контракт | BLOCKED_SECRETS |
| Mulen Pay | `gateways/mulenpay.py` | sign (SHA-1) | `GET /v2/payments/{id}` | нет | нет | нет | `test_payments_pal24_mulenpay.py`, контракт | BLOCKED_SECRETS |
| WATA | `gateways/wata.py` | X-Signature (RSA SHA-512) | `GET /transactions?orderId=` | нет | нет | нет | `test_payments_wata_antilopay.py`, контракт | BLOCKED_SECRETS |
| Antilopay | `gateways/antilopay.py` | X-Apay-Callback (RSA SHA-256) | `POST /payment/check` | нет | нет | нет | `test_payments_wata_antilopay.py`, контракт | BLOCKED_SECRETS |
| AuraPay | `gateways/aurapay.py` | X-SIGNATURE (HMAC значений) | `POST /invoice/status` | нет | нет | нет | `test_payments_aurapay_anore.py`, контракт | BLOCKED_SECRETS |
| Anore | `gateways/anore.py` | Anore-Signature (HMAC-SHA256) | `GET /payments/{id}` | нет | нет | нет | `test_payments_aurapay_anore.py`, контракт | BLOCKED_SECRETS |
| Cashera | `gateways/cashera.py` | X-Api-Key + X-Secret | `GET /integration/transactions/{uuid}` | нет | нет | нет | `test_payments_cashera_paritypay.py`, контракт | BLOCKED_SECRETS |
| ParityPay | `gateways/paritypay.py` | X-SIGNATURE (HMAC значений) | `GET /v2/invoice/status` | нет | нет | нет | `test_payments_cashera_paritypay.py`, контракт | BLOCKED_SECRETS |
| Tribute | `tribute.py` | подпись Tribute | — (донат пополняет баланс) | нет | нет | — | `test_tribute.py` | BLOCKED_SECRETS |
| Telegram Stars | `telegram_stars.py`, `bot.py` | Telegram (`pre_checkout_query` + `successful_payment`, сверка суммы XTR и заказа) | ответ Telegram | `refundStarPayment` | подписка Stars на 30 дней | тестовая среда Telegram | `test_growth.py`, `test_single_business_logic.py` | BLOCKED_SECRETS |
| Stripe, PayPal | `payment_platform_api.py` | подпись Stripe / проверка PayPal API | API платёжной системы | — | — | test mode | `test_behaviour_store_and_webhooks.py` | BLOCKED_SECRETS |
| Apple IAP, Google Play | `payment_platform_api.py` | — | — | — | — | — | `test_behaviour_store_and_webhooks.py` | NOT_APPLICABLE: приём закрыт ответом 410, оплата идёт через кабинет |
| Sandbox магазина | `payments.py` (`SandboxProvider`) | — | только при `PAYMENTS_SANDBOX=true` и не в production | да | да | сам и есть sandbox | `test_sandbox_*` | PASS (CI) |

«Контракт» — `tests/test_payment_contract.py` (v28.75.0). Он прогоняет каждую кассу реестра `gateways.GATEWAYS` через общую выдачу и проверяет:
- заказ другой кассы и другая сумма — отказ;
- касса не подтвердила оплату — 503, выдачи нет;
- подтверждённая оплата выдаётся ровно один раз;
- повторное уведомление — `duplicate`;
- неизвестный заказ игнорируется;
- неудачная выдача остаётся `retry` и выдаётся при следующем уведомлении.

## Управление из админки

| Что | Где |
| --- | --- |
| Включить и выключить способ оплаты, порядок касс | «Кассы → Способы оплаты», «Очередь касс» |
| Ключи касс | «Настройки без перезапуска» (хранятся зашифрованными) |
| Sandbox и production | «Проверка платежей» (production gate), `PAYMENTS_SANDBOX`, режимы касс выше |
| Проверка ключей кассы | «Кассы → Здоровье касс → Проверить кассы сейчас» |
| Журнал уведомлений (новое в v28.73.0) | «Кассы → Журнал уведомлений»: принятые события с заказом, суммой и ошибкой, отклонённые уведомления (подпись, сумма, касса не подтвердила) |
| История и возвраты | «Платежи», «Возвраты», финансовый журнал |
| Мобильные админки | карточки «Кассы», «Уведомления касс», «Возвраты» |

## Что не сделано и почему

- **Живые платежи** у всех касс — `BLOCKED_SECRETS`. Нужны sandbox-ключи и разрешение владельца на тестовые платежи. Как проверить — в [PAYMENT_TESTING.md](PAYMENT_TESTING.md).
- **Возвраты через API у Lava, Pal24, Mulen Pay, WATA, Antilopay, AuraPay, Anore, Cashera и ParityPay.** Подтверждённого метода возврата в документации этих касс нет: возврат делается в кабинете кассы, магазин его перечитывает.
- **Apple IAP и Google Play** закрыты (410). Покупки в приложениях идут через кабинет.
