# VPN Shop by Corgi v8 — Mobile Release

## Приложения
- Corgi VPN — Android user
- Corgi VPN — iOS user
- Corgi Admin — Android admin
- Corgi Admin — iOS admin

## User mobile
- отдельный Material 3 / Web 3.0 UI;
- email auth;
- biometric/device-credential unlock;
- subscription QR/deep links;
- Smart Routing recommendation;
- device management;
- in-app notification center;
- mark-as-read;
- quick connect via subscription clients;
- security screen;
- `corgi://connect` и `corgi://support` deep links.

## Admin mobile
- отдельное admin-приложение;
- biometric unlock после сессии;
- monitoring;
- payments;
- plans;
- support;
- broadcasts;
- platform/fraud;
- mobile operations snapshot: critical events, stale agents, agent health;
- deep links.

## Backend mobile API
- `/api/me/mobile/bootstrap`
- `/api/me/mobile/notifications`
- `/api/me/mobile/notifications/{id}/read`
- `/api/admin/mobile/ops`

## Push strategy
Внутренний notification center остаётся источником истины. Production FCM/APNs credentials подключаются через provider adapters; без них приложения используют безопасный in-app polling, чтобы не заявлять ложную доставку push.

## Validation
- Python compileall: PASS
- static audit: PASS
- Swift parse user: PASS
- Swift parse admin: PASS
- Android Gradle: BLOCKED BY ENVIRONMENT — wrapper требует скачивание Gradle из `services.gradle.org`, внешний DNS/network недоступен в sandbox.
