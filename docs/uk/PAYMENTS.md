> Поточний дистрибутив: `v28.4.0`; runtime/API: `21.5.1`. Точні межі готовності наведені в актуальній матриці покриття.

# VPN Shop — v28.4.0 (runtime 21.5.1)

Поточне стабільне ядро: API, адмінка, кабінет/Mini App, бот, Support Pro і мобільні вихідні коди. Міграція магазину: `0065_history_import`; Support Pro: `0006`. v28.4.0 переносить адмінку, кабінет і Telegram Mini App на Next.js у дизайні Remna Dark, додає звірений імпорт історії підписок і платежів із відкатом та API профілю клієнта. v28.3.0 додав 96 типізованих live-налаштувань із шифруванням секретів, staged apply, аудитом, збіжністю процесів і rollback; 46 restart-bound полів та 2 workflow-поля класифіковані окремо.

Справжні платежі залишаються закритими до завершення application E2E v2. Повне перенесення функцій та підписані APK/IPA ще не завершено. Stable визначає канал поточного ядра.

[Поточна документація оператора (російською)](../../DOCUMENTATION.md), [live-налаштування](../ru/RUNTIME_SETTINGS_CURRENT.md), [SSH/Termius](../ru/DEPLOYMENT_CURRENT.md), [оновлення](../ru/WORKSPACE_UPGRADE.md), [резервування](../ru/BACKUP_CURRENT.md), [реферали](../ru/REFERRALS_CURRENT.md), [мобільні застосунки](../../MOBILE.md), [API](../API_ENDPOINTS.md), [ліцензія](../../LICENSE).

Для локального тесту клонуйте тег `v28.4.0` і виконайте `bash scripts/test-up.sh`. Loopback-порти: API 18080, адмінка 18081, кабінет 18082, Mini App 18083. Sandbox-підписка не створює VPN-тунель.

Нова установка через root SSH/Termius:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.4.0/install.sh -o /root/shop-install.sh && BRANCH=v28.4.0 bash /root/shop-install.sh
```

Для чинного магазину використовуйте регламент оновлення, збережіть секрети й перевірте узгоджену копію.
