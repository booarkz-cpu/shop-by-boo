import {expect, test} from '@playwright/test';

// v28.71.0 (stage 13): «Бот и кабинет → Telegram-бот». The browser stand has no bot token, so the section first
// says so; then route stubs shaped like the backend's answers (tests/test_telegram_bot.py runs the backend with a fake
// Telegram, tests/live/test_telegram_live.py — with the real Bot API).
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

test('without a token the section says how to connect the bot', async ({page}) => {
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Telegram-бот/}).click();
  await expect(page.locator('[data-bot-status]')).toContainText('Токен не задан');
  await expect(page.locator('[data-bot-status]')).toHaveAttribute('data-level', 'off');
  await expect(page.locator('[data-bot-commands] [data-command="start"]')).toBeVisible();
  await expect(page.locator('[data-bot-commands]').getByRole('button', {name: 'Сохранить и применить'})).toBeDisabled();

  // v28.72.0: the bot's texts are saved by the real backend (no token is needed for them).
  // The default is the brand text since v28.132.0 (backend/app/brand_copy.py, owner's decision 4).
  const WELCOME_EN = 'Welcome to {name} — free internet without the extra woof!\nYour internet. Your rules. Your Lusi.';
  const texts = page.locator('[data-bot-texts]');
  await texts.getByLabel('Язык', {exact: true}).selectOption('en');
  await texts.getByLabel('Поиск', {exact: true}).fill('welcome');
  const welcome = texts.getByRole('textbox', {name: 'welcome', exact: true});
  await expect(welcome).toHaveValue(WELCOME_EN);
  await welcome.fill('Hi from {name}!');
  await texts.getByRole('button', {name: 'Сохранить (1)'}).click();
  await expect(texts.locator('[data-text="welcome"]')).toContainText('свой');
  await welcome.fill('Hi {user}!');
  await texts.getByRole('button', {name: 'Сохранить (1)'}).click();
  await expect(texts.getByRole('alert')).toContainText('{user}');
  await texts.getByRole('button', {name: 'Стандартный текст'}).click();
  await texts.getByRole('button', {name: 'Сохранить (1)'}).click();
  await expect(texts.locator('[data-text="welcome"]')).not.toContainText('свой');
  await expect(welcome).toHaveValue(WELCOME_EN);
});

test('connected bot: live check, stale webhook, commands and a test message', async ({page}) => {
  const status = {state: 'running', connected: true, username: 'corgi_lucy_bot', first_name: 'Корги Люси', token_set: true,
    token_fingerprint: 'abc123def456', token_fingerprint_settings: 'abc123def456', bot_username_setting: 'corgi_lucy_bot',
    last_ok_at: new Date().toISOString(), last_update_at: new Date().toISOString(), updates_total: 128, last_error: null,
    check: {status: 'ok', detail: '@corgi_lucy_bot на связи с Telegram'}, stats: {telegram_users: 12, new_last_day: 2}};
  let hooked = true, commands: any = null, message: any = null;
  await page.route('**/api/admin/telegram/status', (r: any) => r.fulfill({json: status}));
  await page.route('**/api/admin/telegram/check', (r: any) => r.fulfill({json: {bot_id: 1, username: 'corgi_lucy_bot', mode: hooked ? 'webhook' : 'polling',
    webhook_url: hooked ? 'https://old.example.com/hook' : null, pending_updates: hooked ? 3 : 0, username_mismatch: false}}));
  await page.route('**/api/admin/telegram/webhook/delete', (r: any) => { hooked = false; return r.fulfill({json: {deleted: true}}); });
  await page.route('**/api/admin/telegram/commands', (r: any) => {
    if (r.request().method() === 'PUT') { commands = r.request().postDataJSON(); return r.fulfill({json: {commands, applied: true}}); }
    return r.fulfill({json: {custom: false, applied_at: null, commands: {ru: [{command: 'start', description: 'Главное меню'}, {command: 'buy', description: 'Тарифы и покупка'}],
      en: [{command: 'start', description: 'Main menu'}], uk: [{command: 'start', description: 'Головне меню'}]}}});
  });
  await page.route('**/api/admin/telegram/test-message', (r: any) => { message = r.request().postDataJSON(); return r.fulfill({json: {sent: true, message_id: 7}}); });
  await page.route('**/api/admin/telegram/texts', (r: any) => r.fulfill({json: {languages: ['ru', 'en', 'uk'], texts: []}}));
  await page.route('**/api/admin/telegram/errors', (r: any) => r.fulfill({json: {errors: [{id: 1, level: 'ERROR', message: 'bot session failed: TelegramNetworkError', count: 2, resolved: false, last_seen: new Date().toISOString()}]}}));
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Telegram-бот/}).click();

  const s = page.locator('[data-bot-status]');
  await expect(s).toHaveAttribute('data-level', 'ok');
  await expect(s.locator('[data-bot-facts]')).toContainText('@corgi_lucy_bot');
  await expect(s.locator('[data-bot-facts]')).toContainText('12 (за сутки +2)');
  await s.getByRole('button', {name: 'Проверить сейчас'}).click();
  await expect(s.locator('[data-bot-live]')).toContainText('webhook https://old.example.com/hook');
  await s.getByRole('button', {name: 'Удалить webhook'}).click();
  await expect(s.locator('[data-bot-live]')).toContainText('long polling');

  const c = page.locator('[data-bot-commands]');
  await c.getByLabel('Описание 2', {exact: true}).fill('Купить VPN');
  await c.getByRole('button', {name: 'Добавить команду'}).click();
  await c.getByLabel('Команда 3', {exact: true}).fill('help');
  await c.getByLabel('Описание 3', {exact: true}).fill('Помощь');
  await c.getByLabel('Язык', {exact: true}).selectOption('en');
  await expect(c.locator('[data-command="start"] input').nth(1)).toHaveValue('Main menu');
  await c.getByRole('button', {name: 'Сохранить и применить'}).click();
  await expect.poll(() => commands?.ru?.map((x: any) => x.command)).toEqual(['start', 'buy', 'help']);
  expect(commands.ru[1].description).toBe('Купить VPN');

  const t = page.locator('[data-bot-test]');
  await t.getByLabel('Chat ID', {exact: true}).fill('777000');
  await t.getByRole('button', {name: 'Отправить'}).click();
  await expect.poll(() => message).toEqual({chat_id: 777000, text: 'Проверка связи: бот магазина работает.'});
  await expect(page.locator('[data-bot-errors]')).toContainText('TelegramNetworkError');
});
