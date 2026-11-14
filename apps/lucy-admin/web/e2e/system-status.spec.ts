import {expect, test} from '@playwright/test';

// v28.62.0 (stage 6): System Control Center — «Состояние системы» lists every part and opens its section.
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

const PARTS = ['backend', 'frontend', 'database', 'migrations', 'redis', 'remnawave', 'nodes', 'caddy', 'tls', 'payments', 'jobs', 'backup', 'telegram', 'updates'];

test('system status shows every part with a reason and opens the section that manages it', async ({page}) => {
  test.setTimeout(60_000);
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Состояние системы/}).click();
  const status = page.locator('[data-system-status]');
  await expect(status.locator('[data-check]')).toHaveCount(PARTS.length, {timeout: 20_000});
  for (const key of PARTS) await expect(status.locator(`[data-check="${key}"] small`)).not.toBeEmpty();
  await expect(status.locator('[data-check="database"]')).toHaveAttribute('data-status', 'ok');
  // The browser test stand has no Remnawave panel: the check says so instead of failing.
  await expect(status.locator('[data-check="remnawave"]')).toHaveAttribute('data-status', 'off');
  await expect(status.locator('[data-check="remnawave"]')).toContainText('REMNAWAVE_URL');
  await status.getByRole('button', {name: 'Проверить снова'}).click();
  await expect(status.locator('[data-check]')).toHaveCount(PARTS.length, {timeout: 20_000});
  await status.locator('[data-check="backup"]').getByRole('button', {name: 'Резервные копии'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Резервные копии'})).toBeVisible();
});
