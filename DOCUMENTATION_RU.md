> Актуальный дистрибутив: `v28.47.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# Полная документация на русском

Начните с [актуального указателя](DOCUMENTATION.md). Для дистрибутива v28.47.0 с runtime/API v21.5.1 используйте руководства `WORKSPACE_*` и [отчёт выпуска](docs/ru/RELEASE_V28_20_0.md). Порядок установки: [INSTALL_STEPS.md](INSTALL_STEPS.md). Каждая область описана в [FUNCTIONS.md](FUNCTIONS.md); открытые пункты и их критерии собраны в [матрице завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md).

Магазин использует единые финансовые операции для кабинета, Mini App и бота. Отдельные мобильные приложения клиента и администратора остаются в исходниках. Старые платёжные адаптеры нужны для исторической сверки и не расширяют список новых покупок. Новые агенты: YooKassa, RollyPay, Platega. Производственный допуск закрыт до полного внешнего application E2E v2.

[Архитектура](docs/ru/WORKSPACE_ARCHITECTURE.md), [состав компонентов](MODULES.md), [проверка полноты](docs/ru/WORKSPACE_COVERAGE.md), [лицензия](LICENSE).

Справочники: [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.

## Выпуск v28.47.0

Страница статуса и цены по странам; ранее — возвраты и автопродление через CloudPayments, здоровье касс, Tribute, кассы Cashera и ParityPay, векторная карта стран, кассы AuraPay, Anore, WATA, Antilopay, Pal24 и Mulen Pay; миграция `0082_status_subscribers`, приложения 3.4.0: [заметки](docs/ru/RELEASE_V28_47_0.md), [установка с нуля](docs/INSTALLATION.md), [архитектура модулей](docs/modules/README.md).

Ранее добавлены [настройки без перезапуска](docs/ru/RUNTIME_SETTINGS_CURRENT.md), migration head обновлён до `0082_status_subscribers`. [Полная инструкция production](docs/ru/PRODUCTION_CURRENT.md) охватывает SSH/Termius, DNS/TLS, настройку, приёмку, backup/restore, обновления и инциденты. Внешние проверки и часть матрицы остаются открытыми; production gate закрыт.
