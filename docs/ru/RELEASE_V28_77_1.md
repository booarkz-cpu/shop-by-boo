# Выпуск v28.77.1 — исправление: подписанные APK и постоянные ссылки на скачивание

Дистрибутив: `v28.77.1`. Runtime/API: `21.5.1`. Head магазина: `0093_ssh_key_rotation` (миграций нет). Support Pro: `0008` / 3.8.

## Что случилось

Выпуск v28.77.0 опубликовался без Android-приложений. Новая проверка подписи (этап 18) искала отпечаток сертификата в выводе `apksigner verify --print-certs`. Без `--verbose` новые версии apksigner отпечаток не печатают, поэтому проверка сочла APK неподписанным и остановила публикацию. Так и должно быть: лучше не выложить APK, чем выложить непроверенный.

## Что исправлено

- `scripts/build-android-apk.sh` берёт apksigner из build-tools 35.0.0 (их ставят оба workflow выпуска) и запускает `verify --verbose --print-certs`. Отпечаток ищется в строке «Signer … certificate SHA-256 digest».
- В выпуске есть подписанные APK и AAB клиента и админки, а также постоянные [corgi-lusi-android.apk](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android.apk) и [corgi-lusi-android-admin.apk](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android-admin.apk).

## Обновление

Сервер магазина не меняется. Если обновляете:

```bash
cd /opt/vpn-shop && bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.77.1 bash /opt/vpn-shop/scripts/update-from-github.sh
```
