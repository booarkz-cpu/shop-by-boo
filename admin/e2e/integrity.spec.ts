import {expect, test} from '@playwright/test';

// v28.59.0 (stage 5): the read-only integrity report is reachable from the admin panel and shows every relation.
test('administrator checks data integrity from «Запуск и оповещения»', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  await page.locator('.sidebar').getByRole('button', {name: /Запуск и оповещения/}).click();
  const card = page.locator('[data-integrity]');
  await expect(card.getByRole('heading', {name: 'Целостность данных'})).toBeVisible();
  await card.getByRole('button', {name: 'Проверить'}).click();
  await expect(card.locator('li')).toHaveCount(16);
  await expect(card.getByText('subscriptions.user_id → users')).toBeVisible();
  await expect(card.getByRole('button', {name: 'Проверить снова'})).toBeEnabled();
});
