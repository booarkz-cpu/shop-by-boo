import {test, expect} from '@playwright/test';

test('administrator records an anti-fraud decision with a note', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/fraud')),
    page.getByRole('button', {name: 'Антифрод', exact: true}).click(),
  ]);
  const signal = (await page.evaluate(async () => (await (await fetch('/api/admin/fraud')).json())[0]));
  const row = page.locator(`[data-signal-id="${signal.id}"]`);
  await expect(row).toContainText('Много платежей за сутки');
  await row.getByRole('button', {name: 'Решение'}).click();
  await page.getByLabel('Заметка к решению', {exact: true}).fill('Покупки для семьи');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith(`/api/admin/fraud/${signal.id}`) && r.request().method() === 'POST'),
    page.getByRole('button', {name: 'Ложная тревога', exact: true}).click(),
  ]);
  await expect(row).toHaveCount(0);
  await page.getByLabel('Показать', {exact: true}).selectOption('resolved');
  await expect(row).toContainText('решён');
  const stored = await page.evaluate(async (id) => (await (await fetch('/api/admin/fraud')).json()).find((x: any) => x.id === id), signal.id);
  expect(stored.status).toBe('resolved');
  expect(stored.resolved_at).toBeTruthy();
  const audit = await page.evaluate(async () => (await (await fetch('/api/admin/audit')).json()));
  expect(audit.some((x: any) => x.action === 'fraud.signal.updated' && x.target === String(signal.id))).toBeTruthy();
});
