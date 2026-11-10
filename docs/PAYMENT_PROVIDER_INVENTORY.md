# Платёжные провайдеры: список владельца и код

<!-- Файл создаёт scripts/audit/check_payment_provider_registry.py. Не править руками. -->

Таблица собрана из исходного кода: `backend/app/payment_policy.py` (очередь касс, автопродление, возвраты),
`backend/app/payment_methods.py` (способы оплаты) и модулей платформ. Список владельца — из мастер-промпта
(`docs/prompts/MASTER_PROMPT_V6.md`, строки 256–346).

**Что таблица доказывает и чего нет.** «Есть в коде» значит: адаптер написан и проверяется тестами с подменой
кассы. Работа с настоящими деньгами не проверена ни для одной кассы: нужны тестовые ключи владельца
(пункт O7 в [BACKLOG.md](ru/new/BACKLOG.md)).

Статус — по шкале владельца. `IMPLEMENTED`: адаптер есть и покрыт тестами. До `CONFIGURED`, `SANDBOX_VERIFIED`
и `PRODUCTION_VERIFIED` не дошла ни одна касса: для них нужны ключи. Прочерк — адаптера нет.

Из 35 названий владельца в коде есть **25**, нет **10**: Heleket, Kassa AI, RioPay, SeverPay, Overpay, Etoplatezhi, Jupiter, Donut, CisPay, TabPay.

| Провайдер | ID | Статус | Где в коде | Что умеет в коде | Что ждёт владелец | Тесты |
| --- | --- | --- | --- | --- | --- | --- |
| Telegram Stars | `telegram_stars` | `IMPLEMENTED` | `backend/app/telegram_stars.py` | Счёт в боте: invoice, pre-checkout, successful_payment; подписки за Stars | — | `test_app_config.py`, `test_growth.py`, `test_single_business_logic.py` |
| Tribute | `tribute` | `IMPLEMENTED` | `backend/app/tribute.py` | Пополнение кошелька по ссылке Tribute, вебхук с подписью | — | `test_tribute.py` |
| CryptoBot | `cryptobot` | `IMPLEMENTED` | Касса в очереди оплаты | crypto | — | `test_cryptobot.py`, `test_e2e_journeys.py`, `test_payment_failover_chain.py` и ещё 2 |
| Heleket | `heleket` | — | **Нет в коде** | — | — | — |
| YooKassa | `yookassa` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp · автопродление, возврат | card; sbp | `test_admin_coverage_payments.py`, `test_admin_customer_operations.py`, `test_app_config.py` и ещё 68 |
| MulenPay | `mulenpay` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | — | `test_gateway_ops.py`, `test_payment_failover_chain.py`, `test_payments_pal24_mulenpay.py` |
| Pal24 | `pal24` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | sbp; card | `test_gateway_ops.py`, `test_payment_failover_chain.py`, `test_payments_pal24_mulenpay.py` |
| Platega | `platega` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp · возврат | динамические — проверить | `test_app_config.py`, `test_audit_v2009_runtime.py`, `test_behaviour_payments_v2.py` и ещё 16 |
| WATA | `wata` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | — | `test_gateway_ops.py`, `test_payment_contract.py`, `test_payment_failover_chain.py` и ещё 1 |
| FreeKassa | `freekassa` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | sbp; card | `test_freekassa.py`, `test_payment_contract.py`, `test_payment_failover_chain.py` и ещё 1 |
| FreeKassa SBP | `freekassa_sbp` | `IMPLEMENTED` | Способ оплаты кассы `freekassa` | sbp | — | `test_freekassa.py`, `test_payment_contract.py`, `test_payment_failover_chain.py` и ещё 1 |
| FreeKassa Card | `freekassa_card` | `IMPLEMENTED` | Способ оплаты кассы `freekassa` | card | — | `test_freekassa.py`, `test_payment_contract.py`, `test_payment_failover_chain.py` и ещё 1 |
| CloudPayments | `cloudpayments` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp · автопродление, возврат | выбор на странице провайдера | `test_cloudpayments_refund_recurring.py`, `test_gateway_ops.py`, `test_payment_failover_chain.py` и ещё 2 |
| Kassa AI | `kassa_ai` | — | **Нет в коде** | — | sbp; card; sberpay | — |
| RioPay | `riopay` | — | **Нет в коде** | — | — | — |
| SeverPay | `severpay` | — | **Нет в коде** | — | — | — |
| RollyPay | `rollypay` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp · возврат | sbp; card; crypto | `test_audit_v2009_runtime.py`, `test_behaviour_payments_yookassa.py`, `test_behaviour_public_urls.py` и ещё 11 |
| Overpay | `overpay` | — | **Нет в коде** | — | динамические — проверить | — |
| AuraPay | `aurapay` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | card; sbp | `test_gateway_ops.py`, `test_payment_failover_chain.py`, `test_payments_aurapay_anore.py` и ещё 1 |
| Etoplatezhi | `etoplatezhi` | — | **Нет в коде** | — | card; sbp | — |
| Antilopay | `antilopay` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | card; sbp; sberpay | `test_gateway_ops.py`, `test_payment_failover_chain.py`, `test_payments_wata_antilopay.py` |
| Jupiter | `jupiter` | — | **Нет в коде** | — | sbp | — |
| Donut | `donut` | — | **Нет в коде** | — | card; sbp; sbp_qr | — |
| Lava | `lava` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | card; sbp | `test_feedback_digest_cohorts.py`, `test_gateway_ops.py`, `test_payment_contract.py` и ещё 2 |
| CisPay | `cispay` | — | **Нет в коде** | — | card; sbp; crypto | — |
| Anore | `anore` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | sbp; card; yoomoney; crypto | `test_gateway_ops.py`, `test_payment_failover_chain.py`, `test_payments_aurapay_anore.py` |
| TabPay | `tabpay` | — | **Нет в коде** | — | card; sbp | — |
| ParityPay | `paritypay` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | card; sbp | `test_gateway_ops.py`, `test_payment_failover_chain.py`, `test_payments_cashera_paritypay.py` |
| Cashera | `cashera` | `IMPLEMENTED` | Касса в очереди оплаты | card; sbp | динамические — проверить | `test_gateway_ops.py`, `test_payment_failover_chain.py`, `test_payments_cashera_paritypay.py` |
| Stripe | `stripe` | `IMPLEMENTED` | `backend/app/payment_platform.py` | Класс StripePlatform | — | `test_audit_v2009_runtime.py`, `test_behaviour_store_and_webhooks.py`, `test_critical_audit_v2002.py` и ещё 5 |
| PayPal | `paypal` | `IMPLEMENTED` | `backend/app/payment_platform.py` | Класс PayPalPlatform | — | `test_app_config.py`, `test_behaviour_store_and_webhooks.py`, `test_critical_audit_v2002.py` и ещё 7 |
| Apple StoreKit | `apple` | `IMPLEMENTED` | `backend/app/payment_platform.py` | Класс AppleStorePlatform: проверка покупки на сервере | — | `test_behaviour_store_and_webhooks.py`, `test_mobile_store_expiry.py`, `test_store_billing.py` |
| Google Play Billing | `google` | `IMPLEMENTED` | `backend/app/payment_platform.py` | Класс GooglePlayPlatform: проверка покупки на сервере | — | `test_mobile_store_expiry.py`, `test_store_billing.py` |
| Crypto Gateway | `crypto` | `IMPLEMENTED` | `backend/app/payment_platform.py` | Класс CryptoGatewayPlatform | — | `test_behaviour_payments_v2.py`, `test_critical_audit_v2003.py` |
| Sandbox | `sandbox` | `IMPLEMENTED` | `backend/app/payments.py` | Класс SandboxProvider: тестовая касса без денег | — | `test_account_merge.py`, `test_app_growth.py`, `test_behaviour_plans_privacy.py` и ещё 22 |

## Расхождения по способам оплаты

Код знает три способа: `sbp`, `card`, `crypto`. Способов `sberpay`, `yoomoney`, `sbp_qr` в коде нет.

- RollyPay: владелец ждёт ещё `crypto`; в коде — `card`, `sbp`.
- Antilopay: владелец ждёт ещё `sberpay`; в коде — `card`, `sbp`.
- Anore: владелец ждёт ещё `crypto`, `yoomoney`; в коде — `card`, `sbp`.

## Чего нет и почему это не сделано сразу

Адаптер нельзя написать честно без официального описания API кассы и тестового магазина: подпись вебхука,
поля суммы и заказа, коды статусов у каждой кассы свои. Для касс из списка «нет в коде» нужно одно из двух:
ссылка на документацию API или тестовые ключи.
