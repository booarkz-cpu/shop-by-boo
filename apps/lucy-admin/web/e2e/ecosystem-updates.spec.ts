import {expect, test} from '@playwright/test';

// v28.118.0: «Обновления» → «Вся экосистема». The backend is a stub shaped like backend/app/ecosystem_updates.py
// (tests/test_ecosystem_updates.py checks how the rows are built).
const row = (key: string, title: string, extra: any = {}) => ({key, title, installed: null, latest: null, state: 'unknown', auto: 'none', schedule: null, last_result: null, how: 'Как обновляется.', tab: 'releases', note: null, ...extra});

test('ecosystem updates: one table says what updates itself and what does not', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  let calls = 0;
  await page.route('**/api/admin/ecosystem-updates', (r: any) => {
    calls += 1;
    return r.fulfill({json: {checked_at: '2026-11-11T12:00:00+00:00', summary: {total: 4, automatic: 2, switched_off: 1, no_mechanism: 1, updates_waiting: 1},
      components: [
        row('shop', 'Магазин: бот, Mini App, кабинет, панель администратора, Support Pro', {installed: 'v28.117.0', latest: 'v28.118.0', state: 'update', auto: 'on', schedule: 'каждую ночь в 03:00 по времени сервера', last_result: 'ok'}),
        row('remnawave_node', 'Ноды Remnawave', {installed: '2.7.4', latest: '2.7.4', state: 'current', auto: 'off', note: 'Отстаёт установок: 0 из 1'}),
        row('android_client', '«Корги Люси: клиент» для Android', {latest: 'выпуск v28.118.0', auto: 'in_app'}),
        row('ios_user', 'Приложение магазина для iOS', {latest: '3.5.0', note: 'Нужен аккаунт Apple Developer: обновления на iOS идут только через App Store или TestFlight'}),
      ]}});
  });

  await page.locator('.sidebar').getByRole('button', {name: /^Обновления/}).click();
  const root = page.locator('[data-ecosystem]');
  await expect(root.locator('[data-eco-summary]')).toContainText('Обновляются сами: 2 из 4');
  await expect(root.locator('[data-eco-summary]')).toContainText('Выключено: 1');
  await expect(root.locator('[data-eco-summary]')).toContainText('Без автообновления: 1');
  await expect(root.locator('[data-eco-summary]')).toContainText('Ждут обновления: 1');
  const shop = root.locator('[data-eco="shop"]');
  await expect(shop).toContainText('v28.117.0');
  await expect(shop).toContainText('есть обновление');
  await expect(shop).toContainText('включено');
  await expect(shop).toContainText('каждую ночь в 03:00');
  await expect(root.locator('[data-eco="remnawave_node"]')).toContainText('выключено');
  await expect(root.locator('[data-eco="android_client"]')).toContainText('в приложении');
  // No mechanism is said plainly, with the reason.
  const ios = root.locator('[data-eco="ios_user"]');
  await expect(ios.getByText('нет', {exact: true})).toBeVisible();
  await expect(ios).toContainText('Apple Developer');

  await root.getByRole('button', {name: 'Проверить снова', exact: true}).click();
  await expect.poll(() => calls).toBeGreaterThan(1);
});
