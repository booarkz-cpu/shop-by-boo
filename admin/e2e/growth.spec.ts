import {test, expect} from '@playwright/test';

async function login(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
}

test('administrator adds a win-back scenario with a personal promo code', async ({page}) => {
  await login(page);
  await Promise.all([
    page.waitForResponse((r: any) => r.url().endsWith('/api/admin/automation/catalog')),
    page.getByRole('button', {name: 'Автоматизация', exact: true}).click(),
  ]);
  const preset = page.locator('[data-preset="winback_expired"]');
  await expect(preset).toContainText('{promo}');
  await Promise.all([
    page.waitForResponse((r: any) => r.url().endsWith('/api/admin/automation/presets/winback_expired') && r.status() === 200),
    preset.getByRole('button').click(),
  ]);
  const rules = await page.evaluate(async () => (await (await fetch('/api/admin/enterprise/rules')).json()));
  expect(rules.find((r: any) => r.event === 'subscription.expired')).toMatchObject({enabled: false, actions: {promo_code: {percent: 20, days: 2}}});
  await expect(page.locator('[data-rule-id]').filter({hasText: 'промокод −20% на 2 дн.'}).first()).toBeVisible();
});

test('retention, family plans, plugin catalog and trial protection have their screens', async ({page}) => {
  await login(page);
  await Promise.all([
    page.waitForResponse((r: any) => r.url().includes('/api/admin/analytics/retention')),
    page.getByRole('button', {name: 'Удержание клиентов', exact: true}).first().click(),
  ]);
  await expect(page.getByRole('heading', {name: 'Когорты по месяцу первой оплаты'})).toBeVisible();
  await expect(page.getByText('Средний доход с клиента (LTV)')).toBeVisible();

  await Promise.all([
    page.waitForResponse((r: any) => r.url().endsWith('/api/admin/family')),
    page.getByRole('button', {name: 'Семейные подписки', exact: true}).first().click(),
  ]);
  await expect(page.getByText('Семей пока нет.')).toBeVisible();

  await Promise.all([
    page.waitForResponse((r: any) => r.url().endsWith('/api/admin/plugins/catalogs')),
    page.getByRole('button', {name: 'Плагины', exact: true}).first().click(),
  ]);
  await expect(page.getByRole('region', {name: 'Каталог плагинов'})).toBeVisible();

  await Promise.all([
    page.waitForResponse((r: any) => r.url().endsWith('/api/admin/app-config')),
    page.getByRole('button', {name: 'Конфигурация Mini App', exact: true}).first().click(),
  ]);
  await page.getByRole('spinbutton', {name: 'Пробных периодов с одной сети за сутки (0 — без ограничения)', exact: true}).fill('2');
  await page.getByRole('checkbox', {name: 'Пробный период только с привязанным Telegram', exact: true}).check();
  await page.getByRole('checkbox', {name: 'Подписка Stars с автопродлением (тарифы на 30 дней)', exact: true}).check();
  await Promise.all([
    page.waitForResponse((r: any) => r.url().endsWith('/api/admin/app-config') && r.request().method() === 'PUT' && r.status() === 200),
    page.getByRole('button', {name: 'Сохранить', exact: true}).first().click(),
  ]);
  const saved = await page.evaluate(async () => (await (await fetch('/api/admin/app-config')).json()));
  expect(saved.overrides.trial).toMatchObject({max_per_ip_per_day: 2, require_telegram: true});
  expect(saved.overrides.wallet.stars.subscriptions).toBe(true);
});
