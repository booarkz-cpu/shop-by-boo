import {expect, test} from '@playwright/test';

// v28.124.0: «Расширения Remnawave» → «Сверка с панелью». The backend is a stub shaped like backend/app/rw_drift.py
// (tests/test_rw_drift.py checks how the differences are found).
const base = {checked_at: null, ok_at: null, error: null, failed_at: null, items: [], in_sync: false, watched: {autoselect: true, torrent_ban_nodes: 2}};

test('panel drift: the last answer, a new check, the place to fix', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  let checks = 0;
  await page.route('**/api/admin/rw/drift/meta', (r: any) => r.fulfill({json: base}));
  await page.route('**/api/admin/rw/drift/check', (r: any) => {
    checks += 1;
    return r.fulfill({json: checks === 1
      ? {...base, checked_at: '2026-11-12T09:00:00+00:00', ok_at: '2026-11-11T09:00:00+00:00', items: [
          {area: 'Бан за торренты', object: 'Нода «de-1»', expected: 'бан на 60 мин.', actual: 'бан выключен на панели', tab: 'torrents'},
          {area: 'Автовыбор', object: 'Плитка «Автовыбор»', expected: 'есть в подписке', actual: 'удалена на панели', tab: 'autoselect'}]}
      : {...base, checked_at: '2026-11-12T09:05:00+00:00', ok_at: '2026-11-12T09:05:00+00:00', in_sync: true}});
  });

  await page.locator('.sidebar').getByRole('button', {name: /Расширения Remnawave/}).click();
  const root = page.locator('[data-rw-drift]');
  await expect(root.locator('[data-drift-summary]')).toHaveText('Ещё не проверялось');

  await root.getByRole('button', {name: 'Проверить сейчас', exact: true}).click();
  await expect(root.locator('[data-drift-summary]')).toHaveText('Расхождений: 2');
  const row = root.locator('[data-drift-item="Нода «de-1»"]');
  await expect(row).toContainText('бан на 60 мин.');
  await expect(row).toContainText('бан выключен на панели');
  await expect(row.getByRole('link', {name: 'Торренты на узлах', exact: true})).toHaveAttribute('href', '#torrents');
  await expect(root.locator('[data-drift-item="Плитка «Автовыбор»"]').getByRole('link', {name: 'Автовыбор', exact: true})).toHaveAttribute('href', '#autoselect');

  await root.getByRole('button', {name: 'Проверить сейчас', exact: true}).click();
  await expect(root.locator('[data-drift-summary]')).toHaveText('Совпадает');
  await expect(root.locator('[data-drift-item]')).toHaveCount(0);
});
