# Что может сделать только владелец магазина

Эти шаги нельзя выполнить из кода: нужны ваши ключи, договоры или серверы. Всё остальное подготовлено, и после каждого шага проверка запускается одной кнопкой или одной командой.

## 1. Подпись приложений Android и iOS

Без подписи к выпуску прикладываются неподписанные APK, AAB и IPA: для проверки они годятся, для магазинов приложений нет.

**Где добавить:** GitHub → репозиторий → Settings → Secrets and variables → Actions → New repository secret.

| Секрет | Что это |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | файл ключа `.jks` в base64: `base64 -w0 release.jks` |
| `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` | пароль хранилища, имя и пароль ключа |
| `IOS_CERTIFICATE_BASE64`, `IOS_CERTIFICATE_PASSWORD` | сертификат Apple Distribution (`.p12` в base64) и его пароль |
| `IOS_TEAM_ID` | Team ID из Apple Developer |
| `IOS_USER_PROFILE_BASE64`, `IOS_USER_TUNNEL_PROFILE_BASE64`, `IOS_USER_PUSH_PROFILE_BASE64`, `IOS_ADMIN_PROFILE_BASE64` | профили распространения приложения, расширения VPN, расширения уведомлений и админ-приложения |

**Проверка:** Actions → «Mobile packages» → Run workflow на `main`. Подписанные файлы появятся в последнем выпуске. Подробно — [STORE_PUBLISHING.md](STORE_PUBLISHING.md).

## 2. Автомасштабирование в Hetzner Cloud

1. Получите токен: Hetzner Cloud Console → проект → Security → API tokens, права Read & Write.
2. Добавьте его секретом `HETZNER_API_TOKEN` в GitHub Actions.
3. Запустите Actions → «Hetzner live» → Run workflow.

Проверка создаёт самый маленький сервер, убеждается, что у него есть адрес и метка магазина, и удаляет его. Вы платите за час самого маленького сервера.

Для работы на сервере магазина впишите тот же токен в `.env` (`HETZNER_API_TOKEN=`) и включите режим «Авто» в «Серверы → Автомасштабирование».

## 3. Учебное переключение на резервный сервер

Нужны два сервера с установленным магазином. Еженедельные учения на копии идут сами; полное переключение — так:

```bash
# на основном (STANDBY_IP — адрес резерва)
sudo bash /opt/vpn-shop/scripts/hot-standby.sh primary STANDBY_IP
# на резерве (PRIMARY_IP — адрес основного)
sudo bash /opt/vpn-shop/scripts/hot-standby.sh standby PRIMARY_IP
sudo bash /opt/vpn-shop/scripts/hot-standby.sh status        # отставание — секунды
# учебное переключение: остановите магазин на основном, затем на резерве
sudo bash /opt/vpn-shop/scripts/hot-standby.sh promote
# вернувшийся старый основной — сразу
sudo bash /opt/vpn-shop/scripts/hot-standby.sh demote
```

Перед `promote` прочитайте [hot_standby.md](../modules/hot_standby.md): два основных сервера одновременно теряют данные.

## 4. Новые кассы (CloudPayments, Lava, Pal24, Mulen Pay, WATA, Antilopay, AuraPay, Anore и следующие)

Заключите договор, получите ключи и впишите их в «Настройки → Платёжные агенты» или в `.env`. Адреса уведомлений — в [billing_and_taxes.md](../modules/billing_and_taxes.md#cloudpayments-и-lava-v2838) [Pal24 и Mulen Pay](../modules/billing_and_taxes.md#pal24-и-mulen-pay-v2839), [WATA и Antilopay](../modules/billing_and_taxes.md#wata-и-antilopay-v2840) и [AuraPay и Anore](../modules/billing_and_taxes.md#aurapay-и-anore-v2841). Для Antilopay сгенерируйте пару RSA-ключей в кабинете: закрытый ключ магазина — в `ANTILOPAY_PRIVATE_KEY`, открытый ключ Antilopay — в `ANTILOPAY_PUBLIC_KEY`.

**Проверка:** «Платёжные агенты → Очередь касс» показывает кассу как «принимает». Затем пробная оплата на минимальную сумму и возврат в кабинете кассы.

## 5. Домен зеркала подписки

Если домен подписки панели плохо открывается у клиентов:
1. Заведите домен с A-записью на сервер магазина.
2. Впишите его в `SUB_PROXY_DOMAINS` в `.env`.
3. Перезапустите Caddy: `docker compose up -d caddy`.
4. Включите «Серверы → Прослойка подписки».

Подробно — [subscription_proxy.md](../modules/subscription_proxy.md).
