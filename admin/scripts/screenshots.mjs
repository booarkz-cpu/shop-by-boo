// Documentation screenshots for docs/screenshots.
// Needs the browser fixture (tests/passkey_browser_server.py on :8777) with fresh
// builds of admin and cabinet. Usage: node scripts/screenshots.mjs <out-dir> <version-tag>
// Example: node scripts/screenshots.mjs ../docs/screenshots v28-10-0
import {chromium} from '@playwright/test';
import fs from 'node:fs';

const out = process.argv[2] || '../docs/screenshots';
const tag = process.argv[3] || 'dev';
const base = 'http://localhost:8777';
fs.mkdirSync(out, {recursive: true});
// --lang makes the browser's own controls (file pickers) Russian as well.
const browser = await chromium.launch({executablePath: process.env.E2E_CHROMIUM_PATH || undefined, args: ['--lang=ru-RU'], env: {...process.env, LANG: 'ru_RU.UTF-8', LANGUAGE: 'ru'}});

async function context(viewport, theme = 'dark', extra = {}) {
  const ctx = await browser.newContext({viewport, locale: 'ru-RU', deviceScaleFactor: 1, ...extra});
  await ctx.addInitScript((value) => {
    localStorage.setItem('rw_lang', 'ru');
    localStorage.setItem('rw_theme', value);
  }, theme);
  return ctx;
}

async function adminSignIn(page) {
  await page.goto(base + '/');
  await page.getByRole('textbox', {name: 'Email', exact: true}).fill('browser@example.test');
  await page.locator('input[type=password]').first().fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await page.waitForSelector('.workspace .topbar');
}

async function settle(page) {
  await page.waitForSelector('.loading-bar', {state: 'detached', timeout: 10000}).catch(() => {});
  await page.waitForTimeout(700);
}

async function open(page, label) {
  await page.locator('.sidebar .nav-item', {hasText: label}).first().click();
  await settle(page);
}

/** Viewport-sized capture (keeps the fixed sidebar intact), optionally grown to the page height. */
async function shot(page, name, {full = false} = {}) {
  if (full) {
    const height = await page.evaluate(() => Math.min(document.documentElement.scrollHeight, 2400));
    const size = page.viewportSize();
    await page.setViewportSize({width: size.width, height});
    await page.waitForTimeout(250);
    await page.screenshot({path: `${out}/${name}-${tag}.png`});
    await page.setViewportSize(size);
  } else {
    await page.screenshot({path: `${out}/${name}-${tag}.png`});
  }
  console.log('saved', name);
}

// Demo catalogue so tables are not empty.
{
  const ctx = await context({width: 1440, height: 900});
  const page = await ctx.newPage();
  await adminSignIn(page);
  await page.evaluate(async () => {
    const csrf = document.cookie.split('; ').find((c) => c.startsWith('rw_csrf='))?.split('=')[1] || '';
    const post = (url, body) => fetch(url, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': decodeURIComponent(csrf)}, body: JSON.stringify(body)});
    for (const [name, price, days] of [['Месяц', 199, 30], ['Три месяца', 499, 90], ['Год', 1690, 365]]) await post('/api/admin/plans', {name, price, duration_days: days, enabled: true});
    await post('/api/admin/promo-codes', {code: 'SUMMER25', kind: 'percent', value: 25});
    await post('/api/admin/promo-codes', {code: 'WELCOME10', kind: 'percent', value: 10});
    await post('/api/admin/promotions', {name: 'Чёрная пятница', kind: 'percent', value: 30});
  });
  await ctx.close();
}

// Admin, desktop dark.
{
  const ctx = await context({width: 1440, height: 900});
  const page = await ctx.newPage();
  await page.goto(base + '/');
  await page.waitForSelector('.auth-card');
  await page.waitForTimeout(400);
  await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : undefined));
  await page.waitForTimeout(300);
  await shot(page, 'admin-login');
  await adminSignIn(page);
  await settle(page);
  await shot(page, 'admin-panel', {full: true});
  await page.getByPlaceholder('Например: промокод, возврат, логотип').fill('промокод');
  await page.waitForTimeout(300);
  await shot(page, 'admin-panel-search');
  await page.getByRole('button', {name: 'Очистить поиск'}).click();
  for (const [label, name] of [
    ['Главная', 'admin-dashboard'],
    ['Тарифы', 'admin-plans'],
    ['Конструктор тарифов', 'admin-tariff-constructor'],
    ['Акции и рассылки', 'admin-marketing'],
    ['Меню бота и Mini App', 'admin-bot-content'],
    ['Настройки без перезапуска', 'admin-runtime-settings'],
    ['Роли и администраторы', 'admin-admins'],
    ['Сеть узлов', 'admin-network-intel'],
  ]) {
    await open(page, label);
    await shot(page, name, {full: name !== 'admin-dashboard'});
  }
  await page.keyboard.press('Control+K');
  await page.getByRole('dialog', {name: 'Быстрый поиск'}).getByRole('textbox').fill('возврат');
  await page.waitForTimeout(300);
  await shot(page, 'admin-command-search');
  await ctx.close();
}

// Admin, light theme.
{
  const ctx = await context({width: 1440, height: 900}, 'light');
  const page = await ctx.newPage();
  await adminSignIn(page);
  await settle(page);
  await shot(page, 'admin-panel-light');
  await ctx.close();
}

// Admin, phone.
{
  const ctx = await context({width: 390, height: 844}, 'dark', {isMobile: true, hasTouch: true});
  const page = await ctx.newPage();
  await adminSignIn(page);
  await settle(page);
  await shot(page, 'admin-mobile');
  await page.getByRole('button', {name: 'Открыть меню'}).click();
  await page.waitForTimeout(400);
  await shot(page, 'admin-mobile-drawer');
  await page.locator('.sidebar .nav-item', {hasText: 'Конструктор тарифов'}).click();
  await settle(page);
  await shot(page, 'admin-mobile-form');
  await ctx.close();
}

// Customer cabinet.
{
  const ctx = await context({width: 1440, height: 900});
  const page = await ctx.newPage();
  await page.goto(base + '/cabinet/');
  await page.locator('input[type=email]').fill('customer@example.test');
  await page.locator('input[type=password]').fill('customer-browser-password');
  await page.locator('form').getByRole('button', {name: 'Войти', exact: true}).click();
  await page.getByRole('region', {name: 'Статус подписки'}).waitFor();
  await page.waitForTimeout(4500);
  await shot(page, 'cabinet-overview');
  await page.locator('nav').getByText('Тарифы', {exact: true}).first().click();
  await page.waitForTimeout(1500);
  await shot(page, 'cabinet-plans');
  await ctx.close();
}

// Mini App in Telegram light theme.
{
  const ctx = await context({width: 390, height: 844}, 'light', {isMobile: true, hasTouch: true});
  const page = await ctx.newPage();
  await page.goto(base + '/cabinet/');
  await page.locator('input[type=email]').fill('customer@example.test');
  await page.locator('input[type=password]').fill('customer-browser-password');
  await page.locator('form').getByRole('button', {name: 'Войти', exact: true}).click();
  await page.getByRole('region', {name: 'Статус подписки'}).waitFor();
  await page.addInitScript(() => {
    const button = () => ({text: '', visible: false, show() {}, hide() {}, onClick() {}, offClick() {}, setParams() {}, showProgress() {}, hideProgress() {}});
    window.Telegram = {WebApp: {
      initData: 'query_id=docs', version: '8.0', platform: 'ios', colorScheme: 'light',
      themeParams: {button_color: '#2481cc', bg_color: '#ffffff', secondary_bg_color: '#f1f1f4', text_color: '#000000', hint_color: '#8e8e93'},
      viewportStableHeight: 800, safeAreaInset: {top: 0, bottom: 20}, contentSafeAreaInset: {top: 0, bottom: 0},
      isVersionAtLeast: () => true, ready() {}, expand() {}, disableVerticalSwipes() {}, setHeaderColor() {}, setBackgroundColor() {},
      onEvent() {}, offEvent() {}, HapticFeedback: {impactOccurred() {}, notificationOccurred() {}, selectionChanged() {}},
      BackButton: button(), MainButton: button(), SecondaryButton: button(),
    }};
  });
  // The fixture cannot sign Telegram initData; the cookie session from the form sign-in is reused.
  await page.route('**/api/auth/telegram', (route) => route.fulfill({json: {ok: true}}));
  await page.reload();
  await page.getByRole('region', {name: 'Статус подписки'}).waitFor();
  await page.waitForTimeout(1500);
  await shot(page, 'miniapp-light');
  await ctx.close();
}

await browser.close();
