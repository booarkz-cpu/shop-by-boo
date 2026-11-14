import {expect, test} from '@playwright/test';

// v28.135.0 (owner's task of 2026-11-13): «Установка» → «Порты сервера». The backend is a stub shaped like
// backend/app/rw_ports.py (tests/test_rw_ports.py checks the rules; scripts/ci/ports-check.sh runs the node script for real).
const row = (over: object) => ({proto: 'tcp', port: 443, why: '', scope: 'all', firewall: 'open', listening: true, process: 'xray',
  opened_by_shop: false, ssh: false, required: true, reachable: null, ...over});
const view = (over: object = {}) => ({server_id: 2, name: 'de-1', host: '198.51.100.2', firewalls: ['ufw'], checked_outside: false,
  missing: ['tcp/80'], notes: ['Порт SSH магазин не закрывает никогда.'],
  ports: [row({port: 80, why: 'сайт SelfSteal', firewall: 'closed', listening: true, process: 'caddy'}),
    row({port: 443, why: 'нода: VLESS + REALITY'}), row({port: 2222, why: 'нода ↔ панель', scope: 'panel', firewall: 'panel_only'}),
    row({port: 22, why: '', ssh: true, required: false, process: 'sshd'}), row({port: 2087, why: 'открыт вручную', required: false, opened_by_shop: true, process: 'haproxy'})],
  ...over});

test('server ports: see, open the missing ones, open and close by hand', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  const sent: any[] = [];
  let current: any = view();
  await page.route('**/api/admin/rw/servers', (r: any) => r.fulfill({json: {servers: [{id: 2, name: 'de-1', host: '198.51.100.2'}]}}));
  await page.route('**/api/admin/rw/ports/2', (r: any) => r.fulfill({json: current}));
  await page.route('**/api/admin/rw/ports/2?outside=true', (r: any) => r.fulfill({json: {...current, checked_outside: true,
    ports: current.ports.map((p: any) => ({...p, reachable: p.port !== 80}))}}));
  await page.route('**/api/admin/rw/ports/2/open-required', (r: any) => {
    sent.push(['required']);
    current = view({missing: [], ports: current.ports.map((p: any) => (p.port === 80 ? {...p, firewall: 'open', opened_by_shop: true} : p))});
    return r.fulfill({json: current});
  });
  await page.route('**/api/admin/rw/ports/2/open', (r: any) => { sent.push(['open', r.request().postDataJSON()]); return r.fulfill({json: current}); });
  await page.route('**/api/admin/rw/ports/2/close', (r: any) => { sent.push(['close', r.request().postDataJSON()]); return r.fulfill({json: current}); });

  await page.locator('.sidebar').getByRole('button', {name: 'Установка', exact: true}).click();
  const root = page.locator('[data-server-ports]');
  await root.getByRole('button', {name: 'Проверить порты', exact: true}).click();
  await expect(root.locator('[data-server-ports-summary]')).toContainText('Брандмауэр: ufw');
  await expect(root.locator('[data-server-ports-summary]')).toContainText('Закрыты нужные: tcp/80');
  await expect(root.locator('[data-server-port="tcp/2222"]')).toContainText('только для панели');
  await expect(root.locator('[data-server-port="tcp/22"]').getByRole('button')).toHaveCount(0);     // SSH: no button at all
  await expect(root.locator('[data-server-port="tcp/443"]').getByRole('button')).toHaveCount(0);    // not opened by the shop: not closed from here

  await root.getByRole('button', {name: 'Проверить снаружи', exact: true}).click();
  await expect(root.locator('[data-server-port="tcp/80"]')).toContainText('не доходит');
  await expect(root.locator('[data-server-port="tcp/443"]')).toContainText('доходит');

  await root.getByRole('button', {name: 'Открыть все нужные', exact: true}).click();
  await expect(root.locator('[data-server-ports-summary]')).toContainText('Нужные порты открыты');

  const custom = root.getByLabel('Открыть другой порт', {exact: true});
  await custom.fill('70000');
  await expect(root.getByRole('alert')).toHaveText('Порт — число от 1 до 65535.');
  await custom.fill('51820');
  await root.getByLabel('Протокол', {exact: true}).selectOption('udp');
  await root.locator('form').getByRole('button', {name: 'Открыть', exact: true}).click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[1]).toEqual(['open', [{port: 51820, proto: 'udp'}]]);

  await root.locator('[data-server-port="tcp/2087"]').getByRole('button', {name: 'Закрыть', exact: true}).click();
  const dialog = root.locator('[data-server-ports-confirm]');
  await expect(dialog).toContainText('Закрыть порт 2087/tcp на «de-1»?');
  await dialog.getByRole('button', {name: 'Отмена', exact: true}).click();
  expect(sent).toHaveLength(2);
  await root.locator('[data-server-port="tcp/2087"]').getByRole('button', {name: 'Закрыть', exact: true}).click();
  await root.locator('[data-server-ports-confirm]').getByRole('button', {name: 'Закрыть', exact: true}).click();
  await expect.poll(() => sent.length).toBe(3);
  expect(sent[0]).toEqual(['required']);
  expect(sent[2][0]).toBe('close');
  expect(sent[2][1][0]).toMatchObject({port: 2087, proto: 'tcp'});
});
