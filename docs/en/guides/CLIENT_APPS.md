# Android apps for customers

The shop has two Android apps for customers. Both are signed with the `corgi` key and attached to every release under permanent names.

| | Shop app | «Корги Люси: клиент» (Corgi Lucy client) |
| --- | --- | --- |
| What it is | The customer's account in the shop: sign-in, plans, payment, subscription, support, the built-in VPN | A VPN client for any subscription, not only the shop's |
| Folder | `mobile/android-user` (`shop.remnawave.user`) | `mobile/android-client` (`shop.corgi.client`) |
| Download | [corgi-lusi-android.apk](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android.apk) | [corgi-lusi-client.apk](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.apk) |

Russian originals: [ANDROID_ARCHITECTURE](../../ru/new/ANDROID_ARCHITECTURE.md), [ANDROID_CLIENT_APP](../../ru/new/ANDROID_CLIENT_APP.md). Other guides: [index](README.md).

## Shop app

- **Sign-in:** e-mail and password, passkey, Telegram, Yandex ID, VK ID, Google (the ones the shop enabled). The shop's address is built into the app.
- **Account:** plans and the plan builder, payment (including from the balance), promo codes, subscription status, devices, support, referrals; every text and screen block can be changed from the admin panel («Android and iOS»).
- **Built-in VPN** (Xray-core): imports the shop subscription — share links or Remnawave's Xray JSON, including Hysteria2 — and connects with one button; the fastest server is chosen automatically unless you pick one.
- **What works without VPN** (the «split» dialog):
  - apps that go online directly;
  - Russian sites (.ru, .рф, .su) directly;
  - **your own rules** (v28.87.0): a site or an address — `example.com`, `full:api.example.com`, `keyword:ads`, `regexp:…`, `10.0.0.0/8` — goes **through VPN**, **direct** or is **blocked**. Your rules come before the subscription's own routing. «Through VPN» follows the chosen server or the automatic choice. `geosite:`/`geoip:` lists are not accepted: the app carries no geo files and Xray would refuse the whole config;
  - **TLS fragmentation** (v28.87.0): splits the start of a TLS connection (ClientHello, or packets 1–3 / 1–5) — helps when the provider interferes. Only for TLS servers; REALITY servers are not touched.
  - Changes apply at the next connection; closing the dialog reconnects.
- Without the built-in engine the app hands the subscription to Happ, v2rayNG or Hiddify.

## «Корги Люси: клиент»

A separate app for any subscriptions (links, QR, «Share», full Xray JSON), written from scratch on our Xray-core engine.

| Area | What it has |
| --- | --- |
| Home | A large connect button, the selected server's card opens the list of servers with ping; provider card with traffic, expiry, support and site links from the subscription headers |
| Servers | Several providers, search, protocol filter, sorting, ping of all, «Auto» (observatory + leastPing), flags |
| Protocols | VLESS (REALITY, TLS, Vision), VMess, Trojan, Shadowsocks, SOCKS5, WireGuard, Hysteria2; transports tcp, ws, grpc, xhttp, httpupgrade |
| Routing | Everything through VPN, everything except the local network, Russian sites direct, your own rules (domain, IP/CIDR, `geosite:`, `geoip:` with your geo files); named routing profiles |
| Tunnel | TUN or proxy only; TLS fragmentation, noises, Mux, sniffing, UDP block, DNS (IP/DoH/DoT), MTU, excluded routes |
| Connection | Per-app proxy, quick settings tile, kill switch through the system settings, LAN, hotspot access to SOCKS5/HTTP with a password, autoconnect |
| Other | Widget, Android TV and «subscription to TV from the phone», backups (file, QR, link), `corgi://` URL schemes, tunnel logs, three app icons, RU/EN/UK |

Updates: the app checks `corgi-lusi-client.json` of the latest release; or add the repository to [Obtainium](https://github.com/ImranR98/Obtainium) with the APK filter `^corgi-lusi-client\.apk$`. Since v28.126.0 every new client version also gets its own release `client-v<version>` (never «latest»): add the release-name filter `^client-v` in Obtainium to follow the client alone.

## Verification

Unit tests (JUnit) of both apps, Compose UI tests and VPN tests on an emulator with a local Xray run in CI. Tests on a real phone and TV are BLOCKED_EXTERNAL.
