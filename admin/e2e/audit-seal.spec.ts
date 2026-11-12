import {expect, test} from '@playwright/test';

// v28.125.0: «Журнал действий» → «Целостность журнала». The backend is a stub shaped like backend/app/audit_seal.py
// (tests/test_audit_seal.py checks the seals on a real table).
const base = {sealed_records: 180, seals: 3, sealed_upto: 180, last_seal_at: '2026-11-12T09:50:00+00:00', unsealed_records: 2, verified_at: null, broken: [], intact: false, every_minutes: 10};

test('audit journal integrity: sealed, checked, a broken range is shown', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  let checks = 0;
  await page.route('**/api/admin/audit-seal', (r: any) => r.fulfill({json: base}));
  await page.route('**/api/admin/audit-seal/verify', (r: any) => {
    checks += 1;
    return r.fulfill({json: checks === 1
      ? {...base, verified_at: '2026-11-12T10:00:00+00:00', intact: true}
      : {...base, verified_at: '2026-11-12T10:05:00+00:00', broken: [{from: 61, to: 120, sealed: 60, found: 59, sealed_at: '2026-11-12T09:40:00+00:00'}]}});
  });

  await page.locator('.sidebar').getByRole('button', {name: /Журнал действий/}).click();
  const root = page.locator('[data-audit-seal]');
  await expect(root.locator('[data-seal-summary]')).toHaveText('Ещё не проверялось');
  await expect(root.locator('[data-seal-count]')).toHaveText('180 (по № 180)');
  await expect(root.locator('[data-seal-pending]')).toHaveText('2');
  // The limits are on the page, not only in the documentation.
  await expect(root.getByText('Записи, сделанные после последней печати, ещё не защищены.', {exact: false})).toBeVisible();

  const button = root.getByRole('button', {name: 'Проверить журнал', exact: true});
  await button.click();
  await expect(root.locator('[data-seal-summary]')).toHaveText('Журнал цел');

  await button.click();
  await expect(root.locator('[data-seal-summary]')).toHaveText('Нарушено диапазонов: 1');
  const broken = root.locator('[data-seal-broken="61-120"]');
  await expect(broken).toContainText('61–120');
  await expect(broken.getByRole('cell', {name: '60', exact: true})).toBeVisible();
  await expect(broken.getByRole('cell', {name: '59', exact: true})).toBeVisible();
  // The journal itself is still on the page below.
  await expect(page.locator('[data-audit-log]')).toBeVisible();
});
