// Full screenshot catalog: every admin section and every customer cabinet section.
// Writes <root>/screenshots/admin_panel/NN_<tab>.png and <root>/screenshots/storefront_user/NN_<name>.png
// and writes an index of the admin captures to the OS temp dir (used to build the README "Скриншоты" section).
// Needs the browser fixture (tests/passkey_browser_server.py on :8777) started with PAYMENTS_SANDBOX=true
// and fresh builds of admin and cabinet. Usage: node scripts/screenshots-catalog.mjs <repo-root>
import {chromium} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import os from 'node:os';

const root = path.resolve(process.argv[2] || '..');
const base = 'http://localhost:8777';
const adminDir = path.join(root, 'screenshots/admin_panel');
const userDir = path.join(root, 'screenshots/storefront_user');
for (const dir of [adminDir, userDir]) {
  fs.rmSync(dir, {recursive: true, force: true});
  fs.mkdirSync(dir, {recursive: true});
}

// Section order and names come from the same map the panel uses.
const here = path.dirname(fileURLToPath(import.meta.url));
const sectionsSource = fs.readFileSync(path.join(here, '../src/sections.ts'), 'utf8');
const body = sectionsSource.slice(sectionsSource.indexOf('export const SECTION_GROUPS'), sectionsSource.indexOf('] as const'));
const groups = body.split(/\n  \{\n    id:/).slice(1).map((chunk) => ({
  title: chunk.match(/title: "([^"]+)"/)[1],
  description: chunk.match(/description: "([^"]+)"/)[1],
  items: [...chunk.matchAll(/\{tab: "([^"]+)", label: "([^"]+)", description: "([^"]+)"/g)].map((m) => ({tab: m[1], label: m[2], description: m[3]})),
}));

// --lang makes the browser's own controls (file pickers) Russian as well.
const browser = await chromium.launch({executablePath: process.env.E2E_CHROMIUM_PATH || undefined, args: ['--lang=ru-RU'], env: {...process.env, LANG: 'ru_RU.UTF-8', LANGUAGE: 'ru'}});
const viewport = {width: 1440, height: 900};
const CUSTOMER = {email: 'demo.buyer@example.test', password: 'DemoBuyerPass123!', name: 'demo.buyer'};

async function newPage(theme = 'dark') {
  const ctx = await browser.newContext({viewport, locale: 'ru-RU'});
  await ctx.addInitScript((value) => {
    localStorage.setItem('rw_lang', 'ru');
    localStorage.setItem('rw_theme', value);
  }, theme);
  return ctx.newPage();
}

const csrfFetch = `
  window.__api = async (url, method = 'GET', body) => {
    const csrf = decodeURIComponent(document.cookie.split('; ').find((c) => c.startsWith('rw_csrf='))?.split('=')[1] || '');
    const headers = {'Content-Type': 'application/json'};
    if (method !== 'GET') { headers['X-CSRF-Token'] = csrf; headers['Idempotency-Key'] = 'docs-' + Math.random().toString(36).slice(2); }
    const r = await fetch(url, {method, credentials: 'include', headers, body: body ? JSON.stringify(body) : undefined});
    let data = {}; try { data = await r.json(); } catch {}
    if (!r.ok) throw new Error(url + ' ' + r.status + ' ' + JSON.stringify(data));
    return data;
  };
  window.__buy = async (planId) => {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      try {
        const pay = await window.__api('/api/payments/create', 'POST', {plan_id: planId, provider: 'sandbox'});
        return await window.__api('/api/payments/sandbox/complete', 'POST', {payment_id: String(pay.id)});
      } catch (error) {
        if (!String(error).includes(' 409 ')) throw error;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }
    throw new Error('sandbox payment did not start');
  };`;

async function adminSignIn(page) {
  await page.goto(base + '/');
  await page.getByRole('textbox', {name: 'Email', exact: true}).fill('browser@example.test');
  await page.locator('input[type=password]').first().fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await page.waitForSelector('.workspace .topbar');
}

async function settle(page) {
  await page.waitForSelector('.loading-bar', {state: 'detached', timeout: 10000}).catch(() => {});
  await page.waitForTimeout(800);
}

// ---------- Demo data ----------
{
  const page = await newPage();
  await adminSignIn(page);
  await page.evaluate(csrfFetch);
  await page.evaluate(async () => {
    const api = window.__api;
    // Demo store name on the pictures; the yearly plan has family seats so the family section is shown.
    await api('/api/admin/settings/app_name', 'PUT', {value: 'Корги Люси'});
    await api('/api/admin/app-config', 'PUT', {texts: {home_subtitle: 'Корги Люси всегда рядом'}});
    for (const [name, price, days, seats] of [['Месяц', 199, 30, 0], ['Три месяца', 499, 90, 0], ['Год', 1690, 365, 2]]) await api('/api/admin/plans', 'POST', {name, price, duration_days: days, enabled: true, family_seats: seats});
    await api('/api/admin/promo-codes', 'POST', {code: 'SUMMER25', kind: 'percent', value: 25});
    await api('/api/admin/promo-codes', 'POST', {code: 'WELCOME10', kind: 'percent', value: 10});
    await api('/api/admin/promotions', 'POST', {name: 'Чёрная пятница', kind: 'percent', value: 30});
    // Documents for «Информация» (demo texts, not legal advice).
    await api('/api/admin/info-pages/faq', 'PUT', {enabled: true, ru: {title: '', body: 'Ответы на вопросы, которые нам задают чаще всего.', items: [
      {question: 'Как подключиться после оплаты?', answer: 'Откройте раздел «Подключение», выберите своё устройство и нажмите **Добавить подписку** — приложение настроится само.'},
      {question: 'Сколько устройств можно подключить?', answer: 'Столько, сколько указано в тарифе. Лишнее устройство можно отключить в разделе «Устройства».'},
      {question: 'Как вернуть деньги?', answer: 'Напишите в поддержку в течение 14 дней после оплаты — вернём тем же способом.'},
      {question: 'Можно ли поделиться подпиской с семьёй?', answer: 'Да, на тарифах с семейными местами: пригласите близких в разделе «Семья».'}]}});
    await api('/api/admin/info-pages/rules', 'PUT', {enabled: true, ru: {title: '', body: '## Общие положения\nПользуясь сервисом, вы соглашаетесь с этими правилами.\n\n## Запрещено\n- рассылка спама и вредоносных программ;\n- передача доступа третьим лицам за плату;\n- действия, нарушающие закон.\n\n## Нарушения\nПри нарушении правил доступ может быть **приостановлен** до выяснения обстоятельств.', items: []}});
    await api('/api/admin/info-pages/privacy', 'PUT', {enabled: true, ru: {title: '', body: '## Какие данные мы храним\n- email или Telegram ID для входа;\n- историю платежей;\n- список подключённых устройств.\n\n## Чего мы не храним\nМы не записываем посещённые сайты и содержимое трафика.\n\n## Удаление данных\nУдалить аккаунт и данные можно в разделе «Безопасность».', items: []}});
    await api('/api/admin/info-pages/offer', 'PUT', {enabled: true, ru: {title: '', body: '## 1. Предмет оферты\nИсполнитель предоставляет доступ к сервису на срок оплаченного тарифа.\n\n## 2. Оплата\nОплата принимается картой, через СБП и Telegram Stars. Доступ открывается сразу после подтверждения оплаты.\n\n## 3. Возврат\nВозврат возможен в течение 14 дней по обращению в поддержку.', items: []}});
  });
  // Mail domain: two DMARC aggregate reports and a DNS check (the stand sets MAIL_DOMAIN;
  // without a reachable DNS-over-HTTPS resolver the check shows "not performed").
  await page.evaluate(async () => {
    const csrf = decodeURIComponent(document.cookie.split('; ').find((c) => c.startsWith('rw_csrf='))?.split('=')[1] || '');
    const day = 86400, begin = Math.floor(Date.now() / 1000) - 2 * day;
    const report = (org, id, rows) => `<?xml version="1.0"?><feedback><report_metadata><org_name>${org}</org_name><email>dmarc-reports@${org}</email><report_id>${id}</report_id><date_range><begin>${begin}</begin><end>${begin + day}</end></date_range></report_metadata><policy_published><domain>shop.example</domain><p>quarantine</p><pct>100</pct></policy_published>${rows.map(([ip, n, dkim, spf, disp]) => `<record><row><source_ip>${ip}</source_ip><count>${n}</count><policy_evaluated><disposition>${disp}</disposition><dkim>${dkim}</dkim><spf>${spf}</spf></policy_evaluated></row><identifiers><header_from>shop.example</header_from></identifiers><auth_results><dkim><domain>${dkim === 'pass' ? 'shop.example' : 'unknown.example'}</domain><result>${dkim}</result></dkim><spf><domain>shop.example</domain><result>${spf}</result></spf></auth_results></record>`).join('')}</feedback>`;
    const files = [
      ['google.com!shop.example.xml', report('google.com', 'g-1024', [['198.51.100.7', 1840, 'pass', 'pass', 'none'], ['198.51.100.8', 312, 'pass', 'fail', 'none'], ['192.0.2.66', 14, 'fail', 'fail', 'quarantine']])],
      ['mail.ru!shop.example.xml', report('mail.ru', 'm-77', [['198.51.100.7', 655, 'pass', 'pass', 'none'], ['203.0.113.90', 3, 'fail', 'fail', 'quarantine']])],
    ];
    for (const [name, xml] of files) {
      const body = new FormData();
      body.append('file', new Blob([xml], {type: 'text/xml'}), name);
      await fetch('/api/admin/mail/dmarc/upload', {method: 'POST', credentials: 'include', headers: {'X-CSRF-Token': csrf}, body});
    }
    await fetch('/api/admin/mail/domain/check', {method: 'POST', credentials: 'include', headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}, body: JSON.stringify({dkim_selectors: []})});
  });
  await page.context().close();
}
{
  // A customer with two sandbox purchases and a support request.
  const page = await newPage();
  await page.goto(base + '/cabinet/');
  await page.evaluate(csrfFetch);
  await page.evaluate(async (customer) => {
    const api = window.__api;
    const csrf = Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    document.cookie = `rw_csrf=${csrf}; path=/`;
    await api('/api/auth/register', 'POST', {email: customer.email, password: customer.password, name: customer.name});
    const plans = await api('/api/plans');
    for (let i = 0; i < 2; i += 1) await window.__buy(plans[0].id);
    await api('/api/me/support/tickets', 'POST', {subject: 'Не подключается на iPhone', message: 'Добавил подписку в приложение, но соединение не устанавливается.'});
  }, CUSTOMER);
  await page.context().close();
}

// ---------- Admin panel ----------
const index = [];
{
  const page = await newPage();
  await page.goto(base + '/');
  await page.waitForSelector('.auth-card');
  await page.waitForTimeout(400);
  await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : undefined));
  await page.waitForTimeout(300);
  await page.screenshot({path: path.join(adminDir, '01_login.png')});
  index.push({file: '01_login.png', group: 'Вход', label: 'Вход в панель', description: 'Email и пароль администратора, вход по ключу доступа (passkey), выбор темы и языка.'});
  await adminSignIn(page);
  await settle(page);
  await page.screenshot({path: path.join(adminDir, '00_all_sections.png')});
  index.unshift({file: '00_all_sections.png', group: 'Все разделы', label: 'Все разделы', description: 'Стартовая страница: ключевые показатели и все функции панели по группам с описанием и поиском по задаче.'});
  let number = 2;
  for (const group of groups) {
    for (const item of group.items) {
      await page.evaluate((tab) => { location.hash = tab; }, item.tab);
      await page.waitForFunction((label) => document.querySelector('h1')?.textContent === label, item.label);
      await settle(page);
      await page.evaluate(() => window.scrollTo(0, 0));
      const file = `${String(number).padStart(2, '0')}_${item.tab}.png`;
      await page.screenshot({path: path.join(adminDir, file)});
      index.push({file, group: group.title, groupDescription: group.description, label: item.label, description: item.description});
      number += 1;
    }
  }
  // Cards of newer features sit below the fold: each is captured on its own (screenshots/admin_panel/features/).
  const featureDir = path.join(adminDir, 'features');
  fs.mkdirSync(featureDir, {recursive: true});
  const features = [
    ['nodes', 'Мониторинг и автовосстановление нод', 'node-monitor'],
    ['apps', 'Резервные адреса API и сайты напрямую', 'api-mirrors'],
    ['fraud', 'Анти-шеринг: лимит устройств', 'anti-sharing'],
    ['backups', 'Копия базы в Telegram', 'telegram-backup'],
    ['payouts', 'Бонус днями за друга', 'referral-bonus'],
    ['marketing', 'Генератор промокодов', 'promo-generator'],
    ['support', 'База знаний ИИ-ассистента', 'ai-knowledge'],
  ];
  for (const [tab, heading, name] of features) {
    try {
      await page.evaluate((target) => { location.hash = target; }, tab);
      const card = page.locator('.card', {has: page.locator('h3, summary', {hasText: heading})}).first();
      await card.waitFor({timeout: 15000});
      // Collapsible cards (<details>) are opened so the picture shows their content.
      await card.evaluate((element) => { if (element.tagName === 'DETAILS') element.open = true; });
      await settle(page);
      await card.scrollIntoViewIfNeeded();
      await card.screenshot({path: path.join(featureDir, `${name}.png`)});
    } catch (error) {
      console.warn(`feature card ${name} not captured: ${error.message.split('\n')[0]}`);
    }
  }
  await page.keyboard.press('Control+K');
  await page.getByRole('dialog', {name: 'Быстрый поиск'}).getByRole('textbox').fill('возврат');
  await page.waitForTimeout(300);
  const file = `${number}_command_search.png`;
  await page.screenshot({path: path.join(adminDir, file)});
  index.push({file, group: 'Поиск', label: 'Быстрый поиск', description: 'Ctrl+K (⌘K) из любого раздела: поиск по названию, описанию и синонимам, переход клавишами.'});
  await page.context().close();
}

// ---------- Customer cabinet ----------
const cabinet = [
  ['03_overview', 'Обзор'], ['04_plans', 'Тарифы'], ['06_trial', 'Пробный период'], ['07_connection', 'Подключение'],
  ['08_servers', 'Серверы'], ['09_support', 'Поддержка'], ['10_devices', 'Устройства'], ['11_partner', 'Партнёрский кабинет'],
  ['12_wallet', 'Кошелёк'], ['13_subscription', 'Моя подписка'], ['14_payments', 'Платежи'], ['15_gifts', 'Подарки'],
  ['16_referral', 'Реферальная программа'], ['17_notifications', 'Уведомления'], ['18_security', 'Безопасность'],
  ['19_surveys', 'Опросы'], ['20_giveaways', 'Конкурсы и призы'], ['21_info', 'Информация'],
];
{
  const page = await newPage();
  await page.goto(base + '/cabinet/');
  await page.locator('input[type=email]').waitFor();
  await page.waitForTimeout(600);
  await page.screenshot({path: path.join(userDir, '01_login.png')});
  await page.getByRole('tab', {name: 'Регистрация'}).click();
  await page.waitForTimeout(400);
  await page.screenshot({path: path.join(userDir, '02_register.png')});
  await page.getByRole('tab', {name: 'Вход'}).click();
  await page.locator('input[type=email]').fill(CUSTOMER.email);
  await page.locator('input[type=password]').fill(CUSTOMER.password);
  await page.locator('form').getByRole('button', {name: 'Войти', exact: true}).click();
  await page.getByRole('region', {name: 'Статус подписки'}).waitFor();
  await page.waitForTimeout(4500); // welcome toast fades out
  const nav = page.getByRole('navigation', {name: 'Основные разделы'}).first();
  for (const [name, label] of cabinet) {
    const link = page.locator('aside, nav').getByRole('button', {name: label, exact: true}).first();
    if (await link.count()) await link.click();
    else await nav.getByRole('button', {name: new RegExp(label)}).first().click();
    await page.waitForTimeout(1200);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: path.join(userDir, `${name}.png`)});
    if (name === '21_info') {
      // Two documents from «Документы»: the FAQ with an opened answer and the public offer.
      for (const [shot, title] of [['22_faq', 'Частые вопросы'], ['23_offer', 'Публичная оферта']]) {
        await page.getByRole('button', {name: title}).first().click();
        await page.waitForTimeout(1200);
        if (shot === '22_faq') await page.locator('summary').first().click();
        await page.waitForTimeout(300);
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({path: path.join(userDir, `${shot}.png`)});
        await page.getByRole('button', {name: '← Все документы'}).click();
        await page.waitForTimeout(500);
      }
    }
    if (name === '04_plans') {
      // Checkout result: pay for the first plan from the plans page.
      await page.evaluate(csrfFetch);
      await page.evaluate(async () => {
        const plans = await window.__api('/api/plans');
        await window.__buy(plans[0].id);
      });
      const overview = page.locator('aside, nav').getByRole('button', {name: 'Обзор', exact: true}).first();
      await overview.click();
      await page.waitForTimeout(1500);
      await page.screenshot({path: path.join(userDir, '05_checkout_success.png')});
    }
  }
  await page.context().close();
}

await browser.close();
// Index of admin captures (file, group, label, description) for the README "Скриншоты" section.
const indexFile = path.join(os.tmpdir(), 'admin-screenshots-index.json');
fs.writeFileSync(indexFile, JSON.stringify(index, null, 1));
console.log(`admin ${fs.readdirSync(adminDir).length} files, cabinet ${fs.readdirSync(userDir).length} files, index ${indexFile}`);
