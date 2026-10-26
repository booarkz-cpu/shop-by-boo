# VPN Shop by Corgi — Mobile Apps v8

## Приложения
- Corgi VPN User — Android
- Corgi VPN User — iOS
- Corgi Admin — Android
- Corgi Admin — iOS

## Добавлено
- отдельные user/admin приложения;
- Material 3 / Web 3.0 visual language;
- biometric/device-credential unlock;
- QR onboarding и subscription deep links;
- быстрый переход в VPN-клиенты;
- Smart Routing recommendation;
- in-app notification center с mark-as-read;
- mobile operations snapshot для администратора;
- incident/agent health summary;
- Corgi deep links `corgi://connect` и `corgi://support`;
- общий signed mobile API proof;
- единый API bootstrap для mobile-first data.

## Архитектура
Мобильные приложения не содержат секретов payment/OAuth/provider. Они используют короткоживущие user/admin sessions и подписанный mobile-client proof. Разрушительные административные действия остаются за существующими permission/approval слоями.

## Push
Серверный notification center уже используется как источник истины. FCM/APNs можно подключить через provider adapters без изменения UI/API контракта; до выдачи production credentials приложения используют in-app polling, чтобы не создавать ложную гарантию доставки push.
