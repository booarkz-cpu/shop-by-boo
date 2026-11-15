# Android: архитектура

Подробное описание — [android_architecture](../../modules/android_architecture.md), инструкция владельцу — [модуль 16](../modules/16-mobile-apps.md). Здесь — сводка для этапа 17.

| Приложение | Каталог | Пакет |
| --- | --- | --- |
| Lucy VPN (клиент) | `apps/vpn-shop/android` | `shop.remnawave.user` |
| Админ | `apps/lucy-admin/android` | `shop.remnawave.admin` |

**Функции клиента:**
- вход — пароль, бот, Яндекс, VK, Google, ключ доступа; PKCE ([MOBILE_API](MOBILE_API.md));
- профиль, подписки, продление, кошелёк, семья, подарки;
- выбор сервера и рекомендация маршрута;
- подключение встроенным движком Xray (`CorgiVpnService`, [VPN_ENGINE](VPN_ENGINE.md)) или передача подписки в совместимый клиент;
- QR подписки, уведомления (FCM, стиль из админки), обновление конфигурации (`/api/me/sync`), диагностика и проверка скорости.

**Из веб-админки управляется:**
- макет экранов, кнопки, баннеры и тексты («Приложения: экраны и кнопки»);
- стиль push и кампании;
- резервные адреса API и сайты напрямую;
- карточки сборок.

**Сборка — только в CI:** «Android • PKCE build», «embedded VPN engine», «UI tests»; подписанные APK/AAB — `mobile-release.yml` с ключами владельца.

**Проверено:**
- PASS (CI): сборка, UI-тесты на эмуляторе, сценарии Maestro (`mobile-screenshots.yml`).
- BLOCKED_EXTERNAL: туннель на устройстве с настоящей нодой.
