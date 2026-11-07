# Corgi Lucy — a VPN subscription shop on Remnawave

[Русский](README.md) · **English** · [Українська](README.uk.md)

> [!WARNING]
> ‼️ **This project is for educational and informational purposes only.** ‼️
> The code and documentation are published for study and demonstration. If you use them, you alone are responsible for complying with the laws of your country and for the security of your servers and customer data. The author gives no warranty and accepts no liability for any use.


> **v28.94.0** — current stable release. Runtime/API `21.5.1`, shop migration `0094_store_subscriptions`.

**What it is.** The shop sells VPN subscriptions and grants access in your own Remnawave panel. It:
- takes payments (SBP, cards, crypto, Telegram Stars);
- renews subscriptions and counts traffic and devices;
- runs a Telegram bot, a Mini App, a web cabinet and Android and iOS apps.

Everything is managed from one admin panel, including installing Remnawave and its nodes on your servers.

| | |
| --- | --- |
| ![Admin dashboard](screenshots/admin_panel/02_dashboard.png) | ![Customer cabinet](screenshots/storefront_user/03_overview.png) |
| ![Android app](screenshots/mobile/android-vpn.png) | ![iOS app](screenshots/mobile/ios-vpn.png) |

## Start here

**Download for Android (signed with the shop key):** [customer app — APK](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android.apk) · [«Corgi Lusi: client» — a VPN for any subscription, APK](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.apk) · [admin app — APK](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android-admin.apk). The links always point to the latest release.

| Task | Document |
| --- | --- |
| Install Remnawave and set up domains | [Owner setup guide](docs/en/OWNER_SETUP_GUIDE.md) |
| Deploy the shop | [Deployment](docs/en/DEPLOYMENT.md) |
| Payments | [Payments](docs/en/PAYMENTS.md) |
| All documentation | [Documentation index](docs/en/DOCUMENTATION.md) · [Wiki](docs/wiki/en/Home.md) |
| What changed | [CHANGELOG](CHANGELOG.md) (Russian) |

Detailed guides in English — [installation, admin panel, Remnawave, Android apps](docs/en/guides/README.md). The full Russian set: [DOCUMENTATION_RU](DOCUMENTATION_RU.md).

## 🐣 For beginners: from an empty server to the first sale

Ten steps. Nothing to know in advance: where a command is needed it is given in full, where a button is needed the admin section is named. Every step says what you should see; if you don't, it says where to look.

<details>
<summary><b>Step 1. Buy a server and a domain</b></summary>

- **Shop server (VDS):** Ubuntu 24.04 or Debian 12, 4 cores, 8 GB RAM, 40 GB disk. Any hosting will do.
- **Domain:** any, e.g. `myvpn.com`. At the registrar create five **A** records pointing to the server's IP: `api`, `admin`, `app`, `cabinet`, `support`.
- **You should see:** `ping api.myvpn.com` on your computer shows the server's IP. DNS can take up to an hour — that is normal.
</details>

<details>
<summary><b>Step 2. Create a Telegram bot</b></summary>

- Send [@BotFather](https://t.me/BotFather) the command `/newbot`, pick a name and an address.
- BotFather sends a **token** like `123456:ABC…` — keep it for step 3 and never share it.
</details>

<details>
<summary><b>Step 3. Install the shop with one command</b></summary>

Connect to the server (Windows — PowerShell, macOS and Linux — Terminal): `ssh root@SERVER_IP`. Then:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.94.0/install.sh -o /root/shop-install.sh \
  && BRANCH=v28.94.0 bash /root/shop-install.sh
```

The installer asks for the domain, the bot token and prices, installs Docker, creates random passwords and starts everything (5–15 minutes).

- **You should see:** at the end the installer prints the admin address and login; `bash /opt/vpn-shop/scripts/doctor.sh` shows green lines.
</details>

<details>
<summary><b>Step 4. Sign in to the admin panel and turn on 2FA</b></summary>

- Open `https://admin.YOUR_DOMAIN` and sign in with the login from step 3.
- **«Безопасность → Защита и 2FA»** (Security → Protection and 2FA): turn on two-factor protection (an authenticator app or a passkey). Dangerous actions (removal, downloading copies) need it.
</details>

<details>
<summary><b>Step 5. Install the VPN panel and the first node — no console</b></summary>

- **«Серверы → Установка Remnawave» → «Добавить сервер»** (Servers → Remnawave installer → Add a server): your VPN server's IP and an SSH key or password. The shop checks the server.
- In the wizard pick «Панель и нода на одном сервере» (panel and node on one server), enter the panel domain (`panel.YOUR_DOMAIN`, an A record to that server). «Составить план» → read the steps → «Запустить».
- **You should see:** every step green, the shop connected to the panel. If a step failed, the changes were rolled back and the reason is in the log.
</details>

<details>
<summary><b>Step 6. Hide the node behind an ordinary website (SelfSteal)</b></summary>

- When adding a node enter the **node's domain** (`node1.YOUR_DOMAIN`) and pick a site template — or later in **«Серверы → SelfSteal» → «Сменить сайт»**.
- **«Проверить»** in the same section looks at the node like a stranger would: 11 points. Aim for «в порядке» (all fine).
- **«Серверы → Установка»** (Servers → Install): every protocol on one node, panel-only node port, node guard — one button each, with a plan and rollback.
</details>

<details>
<summary><b>Step 7. Connect payments</b></summary>

- **«Тарифы и оплата → Платёжные агенты»** (Plans and payments → Payment agents): pick a provider (YooKassa, CryptoBot, Telegram Stars and others), paste the keys, press «Проверить».
- Buy a plan yourself in the bot: `/start` → «Купить» → the provider's test card. Details: [payment checklist for beginners](docs/ru/ALL_PAYMENT_PROVIDERS_BEGINNER_CHECKLIST.md).
</details>

<details>
<summary><b>Step 8. Set up plans</b></summary>

- **«Тарифы и оплата → Тарифы»**: period, price, traffic, devices; the trial is there too.
- **«Бот и кабинет»** (Bot and cabinet): texts, menu buttons, banners — all without a restart.
</details>

<details>
<summary><b>Step 9. Turn on backups</b></summary>

- **«Безопасность → Резервные копии»** (Security → Backups): set the encryption password and turn on the Telegram copy — the shop's database comes to your private chat every night.
- **«Серверы → Установка» → snapshots:** «Каждый день» — the panel's database and the nodes' files.
</details>

<details>
<summary><b>Step 10. Update with one button</b></summary>

- Shop: **«Система → Обновления»** (System → Updates) shows a new release; one button, a copy is taken first.
- Panel and nodes: **«Автообновление Remnawave»** in the same section — on a schedule, with a copy and rollback.
- Third-party libraries are updated by Dependabot: small fixes merge themselves after green checks.
</details>

Stuck? See the [installation guide](docs/en/guides/INSTALLATION.md) and the [admin panel guide](docs/en/guides/ADMIN_PANEL.md).

## Contributing and security

[CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md) · [LICENSE](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
