<div align="center">

![Corgi Lusi](docs/img/hero.jpg)

# 🐶 Corgi Lucy — a VPN subscription shop on Remnawave

[Русский](README.md) · **English** · [Українська](README.uk.md)

### Your own turnkey VPN service on top of the Remnawave panel

Telegram bot and Mini App · web cabinet · Android and iOS apps · «Corgi Lusi: client» VPN app · admin panel · support · payments

[![CI](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml)
[![Android client](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/android-client.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/android-client.yml)
[![Release](https://img.shields.io/github/v/release/booarkz-cpu/shop-by-boo?display_name=tag&color=3b82f6)](https://github.com/booarkz-cpu/shop-by-boo/releases/latest)

**[🚀 Install in 15 minutes](#-installation-step-by-step-for-first-timers)** · [👀 What it looks like](#-what-it-looks-like) · [🧭 The customer's path](#-the-customers-path-from-start-to-connected) · [❓ FAQ](#-beginners-faq) · [📚 Docs](#-documentation)

</div>

> [!WARNING]
> ‼️ **This project is for educational and informational purposes only.** ‼️
> The code and documentation are published for study and demonstration. If you use them, you alone are responsible for complying with the laws of your country and for the security of your servers and customer data. The author gives no warranty and accepts no liability for the consequences of use.

> **v28.142.0** — current stable release. Runtime/API `21.5.1`, shop migration `0094_store_subscriptions`, «Corgi Lusi: client» `1.9.0`.

## 🐶 What it is, in plain words

Think of an online shop that sells **VPN access** instead of goods. A customer opens your Telegram bot (or the website, or the app), picks a plan — say «1 month for 199 ₽» — pays by card, SBP, crypto or Telegram Stars, and **seconds later** gets a ready-to-use connection link. A month later the shop reminds them to renew, renews from the balance if they allowed it, and turns access off if nobody paid.

You are the owner. You don't hand out keys, count days or answer «where is my subscription» — the program does it. You open the **admin panel** in a browser and see today's sales, customers, servers and support requests. Prices, bot texts, pictures, plans and payment providers are changed there with buttons, **no programmer needed**.

The VPN itself (the servers customers' traffic goes through) runs on the free **[Remnawave](https://github.com/remnawave/panel)** panel. The shop sits on top: it sells, Remnawave grants access. No Remnawave yet? The shop **installs it for you** from the admin panel — no console.

| Part | What it is | Who uses it |
| --- | --- | --- |
| 🤖 **Telegram bot** | Greeting, plans, payment, «my key», support | Customers |
| 📱 **Mini App** | A small site that opens inside Telegram from the bot's button | Customers |
| 🌐 **Web cabinet** | A website: sign in by e-mail or Telegram; subscription, payments, devices | Customers |
| 📲 **Android and iOS apps** | Buy, renew and connect with one button | Customers |
| 🐾 **«Corgi Lusi: client»** | A standalone Android VPN client for any subscription; updates itself | Anyone |
| 🎛 **Admin panel** | For you: sales, customers, plans, providers, servers, texts, backups | You and your staff |
| 🛰 **Remnawave + nodes** | The VPN panel and the servers that carry the traffic | The shop, automatically |

Everything installs with **one command** (Docker on one server) and updates with **one button** in the admin panel.

## 👀 What it looks like

Real screens of the current version, captured automatically.

<table>
<tr>
<td width="25%" align="center"><b>Telegram bot</b><br><img src="docs/img/bot-start.png" alt="Bot: greeting and prices" width="220"></td>
<td width="25%" align="center"><b>Mini App</b><br><img src="docs/img/miniapp-overview.png" alt="Mini App: home" width="220"></td>
<td width="25%" align="center"><b>Android app</b><br><img src="screenshots/mobile/android-vpn-on.png" alt="Android: VPN on" width="220"></td>
<td width="25%" align="center"><b>iOS app</b><br><img src="screenshots/mobile/ios-vpn-on.png" alt="iOS: VPN on" width="220"></td>
</tr>
</table>

| Admin panel: home | Customer cabinet |
| --- | --- |
| ![Admin dashboard](screenshots/admin_panel/02_dashboard.png) | ![Customer cabinet](screenshots/storefront_user/03_overview.png) |

**«Corgi Lusi: client»** — a separate Android VPN app for any subscription (not only your shop's): the mascot sleeps, runs and cheers with the connection; traffic statistics and a speed test through the tunnel; a log of where every domain went; a raw Xray JSON editor for experts.

| Home | Statistics and speed | Network log | Geek Mode |
| :---: | :---: | :---: | :---: |
| ![Client: home with the mascot](screenshots/client/home.png) | ![Client: traffic and speed test](screenshots/client/stats.png) | ![Client: network log](screenshots/client/netlog.png) | ![Client: raw Xray JSON editor](screenshots/client/geek.png) |

The admin panel is in Russian; menu names below are given in Russian with an English translation in brackets.

## 🧾 What you need before you start

| # | What | Why | Roughly |
| --- | --- | --- | --- |
| 1 | **A server (VDS)** for the shop: Ubuntu 24.04 or Debian 12, **4 cores, 8 GB RAM, 40 GB disk** | The shop, bot and admin panel live here | from $10–15/month |
| 2 | **A VPN server** (a second one, or the same) — 1–2 cores, 1–2 GB RAM, in the country you want to exit from | Customers' traffic goes through it | from $4–6/month |
| 3 | **A domain**, e.g. `myvpn.com` | Addresses of the admin panel, cabinet and bot | from $2/year |
| 4 | **A Telegram account** | To create the bot and receive alerts | free |
| 5 | **A payment provider** — YooKassa, CryptoBot, Telegram Stars or another | To take payments | a fee per payment |
| 6 | **A computer with a terminal** (Windows PowerShell, macOS/Linux Terminal) | To log in to the server once and run the installer | — |

> [!TIP]
> **Never used a terminal?** It is just a window where you paste a command and the server runs it. Windows: press **Start**, type `PowerShell`, open it. macOS: **Applications → Utilities → Terminal**.

## 🚀 Installation step by step (for first-timers)

Twelve steps. Each one says **what to do**, **what you will see** when it worked and **what to do if it didn't**. Don't skip steps or change their order.

### Step 1. Buy a server and write down three things

1. Order a VDS: **Ubuntu 24.04**, 4 cores, 8 GB RAM.
2. The hosting sends an e-mail. Write down the server's **IP address** (four numbers, e.g. `203.0.113.10`), the **login** (almost always `root`) and the **password**.

✅ **Worked if:** you have the IP, login and password. ❌ **No e-mail?** Look in the hosting's control panel under «Servers».

### Step 2. Buy a domain and point it at the server

At your registrar open **DNS** and create **five A records**, each pointing to the server's IP: `api`, `admin`, `app`, `cabinet`, `support`.

✅ **Worked if:** in 5–30 minutes `ping api.myvpn.com` shows your server's IP. ❌ **«Could not find host»?** Wait — DNS can take up to an hour. Check the record's name is just `api`.

### Step 3. Create a Telegram bot

1. Open **[@BotFather](https://t.me/BotFather)**, press **Start**, send `/newbot`.
2. Choose a **name** and an **address** ending in `bot`.
3. BotFather sends a **token** like `1234567890:AAH…` — copy and keep it. ⚠️ Never share it; if it leaks, send `/revoke`.

### Step 4. Log in to the server

In PowerShell or Terminal (replace `SERVER_IP` with yours):

```bash
ssh root@SERVER_IP
```

Answer `yes` to the fingerprint question, then type the password — **the characters are not shown, that is normal**.

✅ **Worked if:** the prompt changes to something like `root@server:~#`. ❌ **`Permission denied`** — wrong password. **`Connection timed out`** — wrong IP or the server is still being created.

### Step 5. Run the installer — one command

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.142.0/install.sh -o /root/shop-install.sh \
  && BRANCH=v28.142.0 bash /root/shop-install.sh
```

| Question | Answer |
| --- | --- |
| Domain | your domain from step 2, without `https://` |
| Bot token | the token from step 3 |
| Administrator e-mail | your e-mail — your admin login |
| Plan prices | press Enter — change them later in the admin panel |

The installer does the rest: Docker, random strong passwords, HTTPS certificates, start-up. **5–15 minutes** — keep the window open.

✅ **Worked if:** at the end it prints the admin address, the login and the **admin password — save it!** `bash /opt/vpn-shop/scripts/doctor.sh` shows green lines.
❌ **Certificate error** — DNS has not spread yet; wait 15 minutes and run the same command again.

### Step 6. Sign in to the admin panel and turn on 2FA

Open `https://admin.YOUR_DOMAIN`, sign in. Then **«Безопасность → Защита и 2FA»** (Security → Protection and 2FA) → **«Включить 2FA»**: scan the QR code with any authenticator app and enter the 6 digits.

| Sign-in | Protection and 2FA |
| --- | --- |
| ![Admin sign-in](screenshots/admin_panel/01_login.png) | ![Security: 2FA](screenshots/admin_panel/66_security.png) |

💡 Without 2FA dangerous actions (removal, downloading database copies) are refused.

### Step 7. Install Remnawave and the first VPN server — with buttons

1. **«Серверы → Установка Remnawave»** (Servers → Remnawave installer) → **«Добавить сервер»** (Add a server): the VPN server's IP, `root` and its password or SSH key → **«Проверить»** (Check).
2. Choose **«Панель и нода на одном сервере»** (panel and node on one server) and enter the panel domain, e.g. `panel.YOUR_DOMAIN` (an A record to the VPN server).
3. **«Составить план»** (Make a plan) → read the steps → **«Запустить»** (Run).

![Remnawave installer](screenshots/admin_panel/77_rwInstaller.png)

✅ **Worked if:** every step is green. ❌ **A step turned red?** Its changes were **rolled back automatically**; the reason is in the log under the step. Fix it and press «Запустить» again.

### Step 8. Disguise the VPN server as an ordinary website

1. **«Серверы → SelfSteal»**: pick a site template from the catalogue (22 of them) or upload your own site as an archive.
2. **«Проверить»** (Check) looks at the server like a stranger would — 11 points. Aim for «в порядке» (all fine).
3. **«Серверы → Установка»** (Servers → Install) — a catalogue of operations with a plan and rollback: every protocol on one node, node guard, MTProto proxy for Telegram, Russian routing lists, Cloudflare CDN, your own Psiphon server.

| SelfSteal | Install catalogue |
| --- | --- |
| ![SelfSteal](screenshots/admin_panel/93_selfsteal.png) | ![Install](screenshots/admin_panel/92_install.png) |

### Step 9. Connect payments

1. Sign up with a provider. The easiest start is **Telegram Stars** (only the bot is needed) or **CryptoBot**; cards and SBP — **YooKassa**.
2. **«Тарифы и оплата → Платёжные агенты»** (Plans and payments → Payment agents) → choose the provider → paste the keys → **«Проверить»**.
3. Buy a plan yourself: `/start` in your bot → «Купить» → the provider's test card.

![Payment agents](screenshots/admin_panel/21_providers.png)

✅ **Worked if:** the bot sent a subscription link and the payment is listed in **«Тарифы и оплата → Платежи»** (Payments). Details: [payment checklist](docs/ru/ALL_PAYMENT_PROVIDERS_BEGINNER_CHECKLIST.md) (Russian).

### Step 10. Plans, texts and pictures

**«Тарифы и оплата → Тарифы»** (Plans): name, period, price, devices, traffic; the trial is there too. **«Бот и кабинет»** (Bot and cabinet): bot greeting, menu buttons, section banners, cabinet texts — no restart needed.

| Plans | Bot banners |
| --- | --- |
| ![Plans](screenshots/admin_panel/15_plans.png) | ![Bot banners](screenshots/admin_panel/41_botBanners.png) |

### Step 11. Backups

**«Безопасность → Резервные копии»** (Security → Backups): set an **encryption password** (keep it separately!) and turn on the Telegram copy — the database comes to your private chat every night. **«Серверы → Установка» → snapshots → «Каждый день»** (daily) — the Remnawave panel and the nodes' files.

![Backups](screenshots/admin_panel/72_backups.png)

### Step 12. Updates — one button

**«Система → Обновления»** (System → Updates) shows a new release; one button updates the shop, taking a copy first and rolling back on failure. **«Автообновление Remnawave»** in the same section updates the panel and nodes at night.

![Updates](screenshots/admin_panel/62_releases.png)

🎉 **Done!** Give the bot's link to your first customer.

## 🧭 The customer's path: from `/start` to connected

| 1. Opens the bot | 2. Picks a plan | 3. Pays | 4. Subscription in the Mini App |
| :---: | :---: | :---: | :---: |
| ![Bot: /start](docs/img/bot-start.png) | ![Bot: plans](docs/img/bot-buy.png) | ![Mini App: top-up](docs/img/miniapp-wallet.png) | ![Mini App: home](docs/img/miniapp-overview.png) |
| **5. Installs the app** | **6. One button** | **7. Servers by country** | **8. Support** |
| ![Android: VPN](screenshots/mobile/android-vpn.png) | ![Android: VPN on](screenshots/mobile/android-vpn-on.png) | ![Mini App: servers](docs/img/miniapp-servers.png) | ![Mini App: support](docs/img/miniapp-support.png) |

The bot reminds the customer before the subscription ends (3 days by default) and renews it on payment.

## 📅 Every day: what the owner does

About **10 minutes a day**: **«Главная»** (Home) — sales and revenue; **«Пользователи → Обращения клиентов»** (Users → Customer requests) — answer them; **«Серверы → Серверы»** — are all nodes online; **«Тарифы и оплата → Платёжные агенты»** — provider failures; **«Аналитика → Состояние системы»** (System health) — warnings with a hint how to fix.

## ❓ Beginner's FAQ

<details>
<summary><b>Can the shop and the VPN share one server?</b></summary>

Yes — choose «panel and node on one server» in step 7. Two servers are more robust: if the VPN server gets blocked, the shop keeps working and you just add a new node.
</details>

<details>
<summary><b>The bot doesn't answer /start.</b></summary>

Check the token in **«Бот и кабинет → Telegram-бот»**; on the server run `bash /opt/vpn-shop/scripts/doctor.sh`. If you revoked the token in @BotFather, enter the new one.
</details>

<details>
<summary><b>A customer paid but got no subscription.</b></summary>

Find the payment in **«Тарифы и оплата → Платежи»**. If it is paid but delivery failed (usually Remnawave was unreachable), the shop retries on a schedule; check that the panel is online in **«Серверы → Remnawave: панель»**.
</details>

<details>
<summary><b>The VPN server got blocked.</b></summary>

Add a new node in another country (**«Серверы → Установка Remnawave»**, node only), then run the SelfSteal check. Most VPN clients refresh the subscription themselves and get the new server.
</details>

<details>
<summary><b>How do I know everything works?</b></summary>

`bash /opt/vpn-shop/scripts/doctor.sh` on the server — all lines green; in the admin panel **«Аналитика → Состояние системы»** checks the database, bot, providers, Remnawave and background workers.
</details>

## 📥 Downloads

**Download for Android (signed with the shop key):** [customer app — APK](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android.apk) · [«Corgi Lusi: client» — a VPN for any subscription, APK](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.apk) · [admin app — APK](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android-admin.apk). The links always point to the latest release. «Corgi Lusi: client» updates itself: once a day on Wi-Fi it downloads a newer version, checks its SHA-256 and offers to install it.

## 📚 Documentation

| Task | Document |
| --- | --- |
| Install Remnawave and set up domains | [Owner setup guide](docs/en/OWNER_SETUP_GUIDE.md) |
| Deploy the shop | [Deployment](docs/en/DEPLOYMENT.md) |
| Payments | [Payments](docs/en/PAYMENTS.md) |
| All documentation | [Documentation index](docs/en/DOCUMENTATION.md) · [Wiki](docs/wiki/en/Home.md) |
| What changed | [CHANGELOG](CHANGELOG.md) (Russian) |

Detailed guides in English — [installation, admin panel, Remnawave, Android apps](docs/en/guides/README.md). The full Russian set: [DOCUMENTATION_RU](DOCUMENTATION_RU.md); every admin section with a screenshot — [README (Russian)](README.md#-скриншоты).

## Contributing and security

[CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md) · [LICENSE](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
