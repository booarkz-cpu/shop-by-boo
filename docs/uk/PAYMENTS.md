> Актуальный дистрибутив: `v28.1.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# VPN Shop — v21.5.1

Поточне стабільне ядро: API, адмінка, кабінет/Mini App, бот, Support Pro і мобільні вихідні коди. Міграція магазину: `0062_support_delivery_identity`; Support Pro: `0006`. Додано багаторівневі реферали зі знімками умов та приватним графом, узгоджені зашифровані CLI-копії двох баз і файлів.

Справжні платежі залишаються закритими до завершення application E2E v2. Повне перенесення функцій та підписані APK/IPA ще не завершено. Stable визначає канал поточного ядра.

[Поточна документація оператора (російською)](../../DOCUMENTATION.md), [SSH/Termius](../ru/DEPLOYMENT_CURRENT.md), [оновлення](../ru/WORKSPACE_UPGRADE.md), [резервування](../ru/BACKUP_CURRENT.md), [реферали](../ru/REFERRALS_CURRENT.md), [мобільні застосунки](../../MOBILE.md), [API](../API_ENDPOINTS.md), [ліцензія](../../LICENSE).

Для локального тесту клонуйте тег `v21.5.1` і виконайте `bash scripts/test-up.sh`. Loopback-порти: API 18080, адмінка 18081, кабінет 18082, Mini App 18083. Sandbox-підписка не створює VPN-тунель.

Нова установка через root SSH/Termius:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v21.5.1/install.sh -o /root/shop-install.sh && BRANCH=v21.5.1 bash /root/shop-install.sh
```

Для чинного магазину використовуйте регламент оновлення, збережіть секрети й перевірте узгоджену копію.
