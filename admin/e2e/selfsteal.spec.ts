import {expect, test} from '@playwright/test';

// v28.92.0 (stage 20, N8): «Серверы → SelfSteal». The catalogue and the preview come from the real backend; the nodes,
// the outside check, the uploads and the plan are answered by stubs shaped like the backend's responses
// (tests/test_selfsteal_sites.py and tests/test_rw_node_modules.py run the same flow against fake nodes).
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

test('SelfSteal: nodes, outside check, own site, catalogue and a change of site', async ({page}) => {
  test.setTimeout(60_000);
  await signIn(page);
  const report = {domain: 'fi.example.com', address: '93.184.216.34', checked_at: '2026-11-07T02:00:00+00:00', remarks: 1,
    summary: 'есть замечания (1)', points: [{key: 'dns', ok: true, text: 'fi.example.com → 93.184.216.34'},
      {key: 'hsts', ok: false, text: 'Нет Strict-Transport-Security'}]};
  let checked = false;
  await page.route('**/api/admin/rw/selfsteal/overview', (r: any) => r.fulfill({json: {known: 1, total: 2, panel_connected: true, templates: 22, nodes: [
    {key: '9:2', installation_id: 9, server_id: 2, name: 'fi-1', address: '93.184.216.34', country: 'FI', domain: 'fi.example.com',
      site: {template: 'corgi', title: 'Дневник корги', lang: 'ru', upload: null}, check: checked ? report : null},
    {key: null, name: 'old-de', address: '203.0.113.7', country: 'DE', domain: null, site: null, check: null, unknown: true}]}}));
  await page.route('**/api/admin/rw/selfsteal/check', (r: any) => { checked = true; return r.fulfill({json: report}); });
  let sites: any[] = [];
  await page.route('**/api/admin/rw/selfsteal/sites', (r: any) => {
    if (r.request().method() === 'POST') {
      sites = [{id: 'a'.repeat(16), name: 'Моя студия', title: 'Моя студия', files: 3, size: 2048, archive: 'site.zip',
        uploaded_at: '2026-11-07T02:00:00+00:00', by: 'browser@example.test'}];
      return r.fulfill({json: sites[0]});
    }
    return r.fulfill({json: {sites, limits: {archive_mb: 20, files: 800}}});
  });
  let sent: any = null;
  await page.route('**/api/admin/rw/installations/9/actions', (r: any) => {
    sent = r.request().postDataJSON();
    return r.fulfill({json: {id: 10, plan_sha256: 'b'.repeat(64), plan: {steps: [{position: 1, title: 'fi-1: SelfSteal — сайт «Свой сайт»'},
      {position: 2, title: 'fi-1: перезапуск Caddy SelfSteal'}]}}});
  });
  await page.locator('.sidebar').getByRole('button', {name: /SelfSteal/}).click();

  const root = page.locator('[data-selfsteal]');
  await expect(root.locator('[data-selfsteal-known]')).toHaveText('Что стоит на нодах — известно про 1 из 2');
  await expect(root.locator('[data-node="9:2"]')).toContainText('Дневник корги');
  await expect(root.locator('[data-node="unknown"]')).toContainText('не знаем');
  await expect(root.locator('[data-node="9:2"]')).toContainText('не проверяли');
  await root.locator('[data-node="9:2"]').getByRole('button', {name: 'Проверить'}).click();
  await expect(root.locator('[data-check-points]')).toContainText('Нет Strict-Transport-Security');
  await expect(root.locator('[data-check-summary]')).toContainText('есть замечания (1)');

  // The catalogue of the real backend: 22 templates, a filter by theme, a preview in a sandboxed frame.
  const catalogue = root.locator('[data-selfsteal-catalogue]');
  await expect(catalogue.locator('[data-template]')).toHaveCount(22);
  await catalogue.locator('[data-selfsteal-theme]').selectOption('creative');
  expect(await catalogue.locator('[data-template]').count()).toBeLessThan(22);
  await catalogue.locator('[data-template="photo"]').getByRole('button', {name: 'Превью'}).click();
  const frame = catalogue.locator('iframe');
  await expect(frame).toHaveAttribute('sandbox', '');
  await expect(page.frameLocator('[data-selfsteal-catalogue] iframe').locator('h1')).toBeVisible();

  // Own site: upload an archive, then put it on the node through the installation's plan.
  await root.locator('[data-selfsteal-file]').setInputFiles({name: 'site.zip', mimeType: 'application/zip', buffer: Buffer.from('PK\x03\x04')});
  await root.getByRole('button', {name: 'Загрузить архив'}).click();
  await expect(root.locator('[data-selfsteal-sites]')).toContainText('Моя студия');
  await root.locator('[data-node="9:2"]').getByRole('button', {name: 'Сменить сайт'}).click();
  const change = root.locator('[data-selfsteal-change]');
  await change.getByLabel('Сайт', {exact: true}).selectOption('custom');
  await change.getByRole('button', {name: 'Составить план'}).click();
  await expect(change.locator('[data-selfsteal-plan]')).toContainText('перезапуск Caddy SelfSteal');
  expect(sent).toEqual({action: 'module', module: {name: 'selfsteal_site', selfsteal_template: 'custom', selfsteal_lang: 'ru',
    selfsteal_upload: 'a'.repeat(16)}});
});
