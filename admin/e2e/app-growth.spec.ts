import {test, expect} from '@playwright/test';

test('app analytics counts the funnel and a push campaign reaches its segment', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  // An app installation reports its first steps (anonymous, no session), before the admin signs in.
  const install = 'e2e-install-' + Date.now();
  const events = await page.request.post('/api/mobile/events', {data: {install_id: install, platform: 'android', app_version: '3.1.0',
    events: [{event: 'install'}, {event: 'open'}, {event: 'screen', screen: 'premium'}, {event: 'connect_tap'}, {event: 'checkout_start'}, {event: 'not_an_event'}]}});
  expect(events.ok()).toBeTruthy();
  expect((await events.json()).accepted).toBe(5);
  // A second «install» of the same installation is not counted again.
  expect((await (await page.request.post('/api/mobile/events', {data: {install_id: install, platform: 'android', events: [{event: 'install'}]}})).json()).accepted).toBe(0);
  // The seeded customer@example.test never bought a subscription: the campaign segment.
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();

  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/admin/app-analytics') && r.ok()),
    page.getByRole('button', {name: 'Приложения: аналитика', exact: true}).click(),
  ]);
  const analytics = page.locator('[data-app-analytics]');
  await expect(analytics.locator('[data-step="install"]')).toContainText(/[1-9]/);
  await expect(analytics.locator('[data-step="checkout_start"]')).toContainText(/[1-9]/);
  await expect(analytics.locator('[data-screen="premium"]')).toContainText('Премиум');

  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/push-campaigns') && r.ok()),
    page.getByRole('button', {name: 'Приложения: push-кампании', exact: true}).click(),
  ]);
  const campaigns = page.locator('[data-push-campaigns]');
  await campaigns.getByLabel('Сегмент', {exact: true}).selectOption('no_subscription');
  await expect(campaigns.locator('[data-reach]')).toContainText(/Получателей: [1-9]/);
  await campaigns.getByLabel('Заголовок', {exact: true}).fill('Попробуйте Корги Люси');
  await campaigns.getByLabel('Текст', {exact: true}).fill('Три дня бесплатно — нажмите «Попробовать» в приложении');
  page.once('dialog', (d) => d.accept());
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/push-campaigns') && r.request().method() === 'POST' && r.ok()),
    campaigns.getByRole('button', {name: 'Отправить', exact: true}).click(),
  ]);
  await expect(campaigns.locator('[data-campaign]').first()).toContainText('Попробуйте Корги Люси');
});
