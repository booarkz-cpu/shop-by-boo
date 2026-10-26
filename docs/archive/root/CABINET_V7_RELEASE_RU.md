# VPN Shop by Corgi — User Cabinet v7

## Что добавлено

- Отдельный веб-сервис `cabinet` в Docker Compose.
- Отдельный домен через `CABINET_DOMAIN` / `CABINET_URL`.
- Material Design + Web 3.0 visual system.
- Responsive desktop/tablet/mobile layout.
- Sticky glass sidebar на desktop.
- Mobile navigation pills.
- Отдельный authentication experience.
- Регистрация по Email + пароль.
- Вход/регистрация через VK ID при включённом `VK_CLIENT_ID`/`VK_CLIENT_SECRET`.
- Вход/регистрация через Yandex ID при включённом `YANDEX_CLIENT_ID`/`YANDEX_CLIENT_SECRET`.
- OAuth state validation и short-lived exchange code остаются на backend.
- Dashboard, subscriptions, plans, trial, connection, servers, devices, Smart Routing и support.
- PWA manifest и существующий cabinet deployment сохранены.

## OAuth configuration

В `.env`:

```env
CABINET_DOMAIN=cabinet.example.com
CABINET_URL=https://cabinet.example.com

VK_CLIENT_ID=
VK_CLIENT_SECRET=
VK_REDIRECT_URI=https://api.example.com/api/auth/vk/callback

YANDEX_CLIENT_ID=
YANDEX_CLIENT_SECRET=
YANDEX_REDIRECT_URI=https://api.example.com/api/auth/yandex/callback
```

Если provider не настроен, его кнопка не показывается пользователю.

## Security

- HttpOnly auth cookies.
- CSRF для state-changing API requests.
- OAuth state cookie + signed state.
- Short-lived OAuth exchange code.
- Не передаются provider secrets во frontend.
- Cabinet API проксируется через Caddy.
- Security headers и CSP остаются включены.

## Проверка

`tsc` в sandbox может сообщать только об отсутствующих `node_modules` (`react`, `react-dom`); JSX/TSX parser проходит до этих module-resolution ошибок. Полный Vite build должен выполняться после `npm ci` в build/runtime окружении.
