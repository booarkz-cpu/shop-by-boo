#!/usr/bin/env node
/**
 * Screenshots of the Telegram Mini App with a mocked API and Telegram WebApp.
 *
 *   (cd cabinet && npm run build:miniapp)
 *   node scripts/screenshots/miniapp.mjs [out-dir]      # default: docs/img
 *
 * Serves cabinet/dist, answers /api/* from cabinet/src/mock-config.json and demo data,
 * fakes window.Telegram.WebApp (so the Mini App surface and greeting are used) and saves
 * one 390×844 PNG per section: miniapp-<section>.png.
 */
import {createServer} from "node:http";
import {readFile} from "node:fs/promises";
import {existsSync, mkdirSync} from "node:fs";
import {extname, join, resolve} from "node:path";
import {createRequire} from "node:module";

const root = resolve(new URL("../..", import.meta.url).pathname);
const dist = join(root, "cabinet/dist");
const out = resolve(process.argv[2] || join(root, "docs/img"));
if (!existsSync(join(dist, "index.html"))) { console.error("Build first: (cd cabinet && npm run build:miniapp)"); process.exit(2); }
mkdirSync(out, {recursive: true});
const require = createRequire(import.meta.url);
let chromium;
try { ({chromium} = require("playwright")); } catch { ({chromium} = require(join(root, "admin/node_modules/playwright"))); }

const config = JSON.parse(await readFile(join(root, "cabinet/src/mock-config.json"), "utf8"));
const days = (n) => new Date(Date.now() + n * 86400000).toISOString();
const live = {...config, version: "screenshots", offline: false, viewer: {first_name: "Артём", username: "artem", language: "ru"},
  promos: [{id: "autumn", title: "Осенняя скидка", text: "Год VPN по цене девяти месяцев", discount: "-25%", ends_at: days(3), button_text: "Выбрать тариф", link: "#plans"}],
  wallet: {...config.wallet, methods: [
    {id: "sbp", title: "СБП", icon: "sbp", provider: "yookassa", yookassa_method: "sbp", available: true},
    {id: "card", title: "Банковская карта", icon: "card", provider: "yookassa", yookassa_method: "bank_card", available: true},
    {id: "crypto", title: "Криптовалюта", icon: "crypto", provider: "rollypay", yookassa_method: "", available: true},
    {id: "stars", title: "Telegram Stars", icon: "star", provider: "telegram_stars", yookassa_method: "", available: true}],
    stars: {enabled: true, rate: "1.5", min_stars: 50}},
  support: {ticket_form: true, buttons: [{title: "Написать в Telegram", icon: "send", link: "https://t.me/corgi_lusi_bot"}, {title: "Частые вопросы", icon: "help", link: "#info"}, {title: "Почта", icon: "mail", link: "https://example.com/support"}]},
  navigation: [...config.navigation.filter((n) => n.kind !== "info"),
    {slug: "wallet", title: "Кошелёк", kind: "wallet", icon: "wallet", banner: "/assets/banners/topup.jpg"},
    {slug: "referral", title: "Пригласи друзей", kind: "referral", icon: "users", banner: "/assets/banners/referral.jpg"},
    {slug: "servers", title: "Серверы", kind: "servers", icon: "server", banner: "/assets/banners/servers.jpg"},
    {slug: "info", title: "Информация", kind: "info", icon: "info", banner: "/assets/banners/info.jpg"}]};
const nodes = [["Frankfurt #1", "DE", 41], ["Amsterdam", "NL", 33], ["Helsinki", "FI", 12], ["Москва · белые списки", "RU", 57], ["New York", "US", 8]]
  .map(([name, country, users]) => ({name, country, status: "online", users_online: users}));
const api = {
  "/api/app-config": live,
  "/api/public/config": {app_name: "VPN Shop by Corgi Lusi", payment_providers: ["yookassa", "rollypay"], trial_days: 3, miniapp: {}, bot_username: "corgi_lusi_bot"},
  "/api/public/apps": {apps: []},
  "/api/public/cabinet-menu": live.navigation,
  "/api/tariff-constructors": [],
  "/api/public/servers": {ok: true, online: 5, total: 5, nodes},
  "/api/me/servers": {ok: true, online: 5, total: 5, nodes, subscription_active: true},
  "/api/auth/telegram": {ok: true},
  "/api/me/dashboard": {user: {username: "artem", email: "", wallet_balance: "350.00", referral_balance: "120.00", referral_code: "LUSI42"},
    subscription: {id: 1, name: "12 месяцев", status: "active", expires_at: days(214), subscription_url: "https://sub.example.com/s/demo"}},
  "/api/plans": config.plans, "/api/me/subscriptions": [{id: 1, name: "12 месяцев", is_primary: true, expires_at: days(214), status: "active"}],
  "/api/me/traffic": {available: true, traffic_used_bytes: 38e9, traffic_limit_bytes: 0, devices: 3},
  "/api/me/devices": [], "/api/me/routing/recommendation": {recommendation: {name: "Frankfurt #1", country: "DE", load: 34}},
  "/api/me/connection-info": {subscription_url: "https://sub.example.com/s/demo", platforms: {android: "", ios: ""}},
  "/api/me/wallet/history": {balance: "350.00", items: []}, "/api/me/consent": {enabled: false, accepted: true, version: "1"},
  "/api/me/referral": {code: "LUSI42", referred_count: 7, reward_total: 640, balance: 120, reward_percent: 10, level_percentages: ["10", "3"]},
  "/api/me/referral/ledger": [], "/api/me/referral/withdrawals": [], "/api/me/referral/network": {nodes: [{id: "me", parent: null, level: 0}], truncated: false, level_counts: []},
  "/api/me/support/tickets": [], "/api/me/offers": {items: [], next_offset: null}, "/api/me/billing-center": {payments: [], subscription: null}, "/api/me/auto-renew": {},
};
const types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".jpg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".json": "application/json", ".txt": "text/plain", ".webmanifest": "application/manifest+json"};
const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  if (url.pathname.startsWith("/api/")) {
    const body = api[url.pathname] ?? (url.pathname.startsWith("/api/me/") ? [] : {});
    res.writeHead(200, {"Content-Type": "application/json"}); res.end(JSON.stringify(body)); return;
  }
  let file = join(dist, decodeURIComponent(url.pathname));
  if (url.pathname.endsWith("/")) file = join(file, "index.html");
  try { const data = await readFile(file); res.writeHead(200, {"Content-Type": types[extname(file)] || "application/octet-stream"}); res.end(data); }
  catch { res.writeHead(404); res.end("not found"); }
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.E2E_CHROMIUM_PATH ? {executablePath: process.env.E2E_CHROMIUM_PATH} : {});
const page = await browser.newPage({viewport: {width: 390, height: 844}, deviceScaleFactor: 2});
await page.route("https://telegram.org/**", (route) => route.fulfill({status: 200, contentType: "text/javascript", body: ""}));
await page.addInitScript(() => {
  localStorage.setItem("rw_lang", "ru");
  const button = {show() {}, hide() {}, onClick() {}, offClick() {}, setParams() {}, showProgress() {}, hideProgress() {}, enable() {}, disable() {}};
  window.Telegram = {WebApp: {initData: "user=%7B%22first_name%22%3A%22%D0%90%D1%80%D1%82%D1%91%D0%BC%22%7D&hash=demo", initDataUnsafe: {user: {first_name: "Артём"}},
    version: "8.0", platform: "android", colorScheme: "dark", themeParams: {}, isVersionAtLeast: () => true, ready() {}, expand() {},
    setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}, disableVerticalSwipes() {}, onEvent() {}, offEvent() {},
    enableClosingConfirmation() {}, disableClosingConfirmation() {}, HapticFeedback: {impactOccurred() {}, notificationOccurred() {}, selectionChanged() {}},
    BackButton: button, MainButton: button}};
});
const sections = ["overview", "wallet", "referral", "support", "servers", "info", "plans"];
for (const section of sections) {
  page.on("console", (m) => process.env.DEBUG && console.log("console:", m.text())); page.on("pageerror", (e) => console.log("pageerror:", e.message));
  await page.goto(`${base}/?shot=${section}#${section}`);
  await page.waitForSelector(".panel", {timeout: 20000}).catch(async (e) => { await page.screenshot({path: join(out, "debug.png")}); throw e; });
  await page.waitForFunction(() => [...document.querySelectorAll("img")].every((i) => i.complete), null, {timeout: 20000});
  await page.waitForTimeout(400);
  await page.screenshot({path: join(out, `miniapp-${section}.png`)});
  console.log("saved", join(out, `miniapp-${section}.png`));
}
await browser.close();
server.close();
