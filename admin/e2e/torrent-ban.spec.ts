import {expect, test} from '@playwright/test';

// v28.117.0: «Серверы → Торренты на узлах» → «Временный бан за торренты». The backend is a stub shaped like
// backend/app/rw_torrent_ban.py (tests/test_rw_torrent_ban.py runs the same flow against a model of the panel).
const DE = '00000001-0000-4000-8000-000000000000', CZ = '00000002-0000-4000-8000-000000000000';

function view(state: any) {
  const node = (uuid: string, name: string, country: string, plugin: any = null) => ({uuid, name, country, online: true, plugin,
    ban: state.on.includes(uuid), minutes: state.on.includes(uuid) ? state.minutes : null, node_version: '2.7.4', supported: true});
  return {nodes: [node(CZ, 'cz-1', 'CZ', {uuid: 'p1', name: 'MyFilters', ours: false}), node(DE, 'de-1', 'DE', state.on.includes(DE) ? {uuid: 'p2', name: 'CorgiTorrentBan', ours: true} : null)],
    enabled_nodes: state.on.length, ignore_ips: state.ignore, minutes: state.minutes, reports_supported: true, panel_supported: true, panel_error: null,
    reports: [{at: '2026-11-11T08:00:00Z', node: 'de-1', user: 'user_5', ip: '198.51.100.9', seconds: 1800}, {at: null, node: null, user: null, ip: null, seconds: null}]};
}

test('temporary torrent ban: choose nodes, switch on with a warning, switch off', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  const state: any = {on: [], minutes: 60, ignore: []};
  const sent: any[] = [], asked: string[] = [];
  await page.route('**/api/admin/rw/torrent-ban', (r: any) => {
    if (r.request().method() === 'PUT') {
      const body = r.request().postDataJSON();
      sent.push(body);
      state.on = body.enabled ? body.node_uuids : state.on.filter((u: string) => !body.node_uuids.includes(u));
      if (body.enabled) Object.assign(state, {minutes: body.minutes, ignore: body.ignore_ips});
    }
    return r.fulfill({json: view(state)});
  });
  page.on('dialog', (d: any) => { asked.push(d.message()); d.accept(); });

  await page.locator('.sidebar').getByRole('button', {name: /Торренты на узлах/}).click();
  const root = page.locator('[data-torrent-ban]');
  await expect(root.locator('[data-ban-summary]')).toHaveText('Выключен');
  // The warning about a shared address is on the page before anything is switched on.
  await expect(root.getByText('Блокируется адрес, а не клиент')).toBeVisible();
  const on = root.getByRole('button', {name: 'Включить на выбранных', exact: true});
  await expect(on).toBeDisabled();  // no node chosen

  await root.getByLabel('Выбрать: de-1', {exact: true}).check();
  await root.getByLabel('Выбрать: cz-1', {exact: true}).check();
  await root.getByLabel('Срок блокировки, минут', {exact: true}).fill('0');
  await expect(on).toBeDisabled();  // a senseless duration
  await root.getByLabel('Срок блокировки, минут', {exact: true}).fill('30');
  await root.getByLabel('Адреса, которые не блокировать (по одному в строке, без маски)', {exact: true}).fill('203.0.113.9\n2001:db8::1');
  await on.click();
  await expect(root.locator('[data-ban-summary]')).toHaveText('Включён на 2 из 2 нод');
  expect(sent[0]).toEqual({enabled: true, minutes: 30, node_uuids: [DE, CZ], ignore_ips: ['203.0.113.9', '2001:db8::1']});
  expect(asked[0]).toContain('Блокируется адрес целиком');
  await expect(root.locator('[data-node="de-1"]')).toContainText('включён, 30 мин.');
  await expect(root.locator('[data-node="cz-1"]')).toContainText('MyFilters (ваш: меняется только блок торрентов)');
  // The journal: a real block and a report whose fields the panel did not give — shown empty, not invented.
  await expect(root.getByRole('cell', {name: '198.51.100.9', exact: true})).toBeVisible();
  await expect(root.getByRole('cell', {name: '30 мин.', exact: true})).toBeVisible();

  await root.getByLabel('Выбрать: cz-1', {exact: true}).uncheck();
  await root.getByRole('button', {name: 'Выключить на выбранных', exact: true}).click();
  await expect(root.locator('[data-ban-summary]')).toHaveText('Включён на 1 из 2 нод');
  expect(sent[1]).toMatchObject({enabled: false, node_uuids: [DE]});
});
