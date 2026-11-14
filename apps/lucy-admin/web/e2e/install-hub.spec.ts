import {expect, test} from '@playwright/test';

// v28.92.0 (stage 20, N7): «Серверы → Установка». The catalogue comes from the real backend (route.fetch); the
// server and its installation are added to the answer, the plans are stubs shaped like the backend's
// (tests/test_install_catalogue.py and tests/test_rw_netmods.py run the same flows against fake servers).
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

test('Установка: catalogue, modes, search, a module plan and the danger zone', async ({page}) => {
  test.setTimeout(90_000);
  await signIn(page);
  await page.route('**/api/admin/rw/servers', (r: any) => r.fulfill({json: {servers: [{id: 7, name: 'fi-1', host: '93.184.216.34', status: 'ready'}]}}));
  await page.route('**/api/admin/install/catalogue*', async (r: any) => {
    const real = await (await r.fetch({url: r.request().url().split('?')[0]})).json();
    const state = {server: {id: 7, name: 'fi-1', host: '93.184.216.34', status: 'ready'}, installation_id: 9, roles: ['node', 'panel'],
      panel_domain: 'panel.example.com', panel_domain_aliases: [], separate_subpage: false,
      steps: {prepared: true, panel: true, domain: false}};
    for (const op of real.operations) op.ready = true;
    return r.fulfill({json: {...real, state}});
  });
  await page.route('**/api/admin/install/snapshots', (r: any) => r.fulfill({json: {snapshots: [
    {name: 'config-7-20261107T010000Z.tar.gz.enc', kind: 'files', server_id: 7, size: 20480, created_at: '2026-11-07T01:00:00+00:00'}]}}));
  await page.route('**/api/admin/install/anti-censorship', (r: any) => r.fulfill({json: {nodes: [{key: '9:7', name: 'fi-1', address: '93.184.216.34',
    country: 'FI', done: 1, total: 2, items: [{key: 'selfsteal', title: 'Свой сайт SelfSteal на домене ноды', ok: true, fix: 'selfsteal'},
      {key: 'guard', title: 'Защита ноды от сканеров и перебора включена', ok: false, fix: 'node_guard'}]}]}}));
  await page.route('**/api/admin/install/mtproto', (r: any) => r.fulfill({json: {proxies: [{server_id: 7, name: 'fi-1', port: 9443,
    domain: 'www.cloudflare.com', tg: 'tg://proxy?server=93.184.216.34&port=9443&secret=ee00', https: 'https://t.me/proxy?server=93.184.216.34&port=9443&secret=ee00'}]}}));
  await page.route('**/api/admin/install/snapshots-schedule', (r: any) => r.fulfill({json: {enabled: false, time: '04:00', telegram: false, state: {}}}));
  const sent: any[] = [];
  await page.route('**/api/admin/rw/installations/9/actions', (r: any) => {
    sent.push(r.request().postDataJSON());
    return r.fulfill({json: {id: 10, plan_sha256: 'c'.repeat(64), plan: {steps: [{position: 1, title: 'fi-1: план шага'}]}}});
  });
  await page.locator('.sidebar').getByRole('button', {name: 'Установка', exact: true}).click();

  const hub = page.locator('[data-install-hub]');
  await expect(hub.locator('[data-install-steps]')).toContainText('Подключите домен');
  const simple = await hub.locator('[data-op]').count();
  await hub.locator('[data-install-mode="expert"]').click();
  expect(await hub.locator('[data-op]').count()).toBeGreaterThan(simple);
  await hub.locator('[data-install-search]').fill('MSS');
  await expect(hub.locator('[data-op]')).toHaveCount(1);
  await expect(hub.locator('[data-op="mss_clamp"]')).toContainText('по SSH');
  await hub.locator('[data-install-search]').fill('');

  // A module with its own settings: the node guard.
  await hub.locator('[data-op="node_guard"]').getByRole('button', {name: 'Установить'}).click();
  const plan = hub.locator('[data-install-plan="node_guard"]');
  await plan.getByLabel('Новых соединений в секунду с одного адреса', {exact: true}).fill('80');
  await plan.getByLabel('Режим', {exact: true}).selectOption('observe');
  await plan.getByRole('button', {name: 'Составить план'}).click();
  await expect(plan.locator('[data-install-plan-steps]')).toContainText('план шага');
  expect(sent.at(-1)).toEqual({action: 'module', module: {name: 'node_guard', enabled: true, server_ids: [7], guard_rate: 80,
    guard_mode: 'observe', guard_ports: [443, 4443, 8443, 2053]}});

  // v28.94.0: MTProto — its port and cover site; the link of the running proxy.
  await hub.locator('[data-op="mtproto"]').getByRole('button', {name: 'Установить'}).click();
  const mt = hub.locator('[data-install-plan="mtproto"]');
  await expect(mt.locator('[data-mtproto-links]')).toContainText('https://t.me/proxy?server=93.184.216.34&port=9443');
  await mt.getByLabel('Порт TCP', {exact: true}).fill('9555');
  await mt.getByLabel('Маскировка под сайт', {exact: true}).fill('www.Microsoft.com');
  await mt.getByRole('button', {name: 'Составить план'}).click();
  expect(sent.at(-1)).toEqual({action: 'module', module: {name: 'mtproto', enabled: true, server_ids: [7], mtproto_port: 9555,
    mtproto_domain: 'www.microsoft.com'}});

  // Snapshots: the list and the schedule.
  await expect(hub.locator('[data-install-snapshots]')).toContainText('Файлы компонентов');
  await expect(hub.locator('[data-install-schedule]')).toBeVisible();
  await hub.locator('[data-restore="config-7-20261107T010000Z.tar.gz.enc"]').click();
  await hub.locator('[data-install-action="restore_files"]').getByRole('button', {name: 'Составить план', exact: true}).click();
  expect(sent.at(-1)).toEqual({action: 'restore_files', snapshot: 'config-7-20261107T010000Z.tar.gz.enc'});

  // «Анти-РКН»: a red point opens the card that fixes it.
  const anti = hub.locator('[data-anti-node="9:7"]');
  await anti.locator('summary').click();
  await expect(anti).toContainText('1 из 2');
  await anti.getByRole('button', {name: 'Исправить'}).click();
  await expect(hub.locator('[data-install-plan="node_guard"]')).toBeVisible();

  // v28.97.0: «Сменить домен панели» — the new domain and keeping the former one for subscriptions.
  await hub.locator('[data-op="change_domain"]').getByRole('button', {name: 'Установить'}).click();
  const dom = hub.locator('[data-install-domain]');
  await expect(dom).toContainText('Сейчас: panel.example.com');
  await dom.locator('[data-domain-new]').fill('Panel2.example.com');
  await dom.getByRole('button', {name: 'Дальше'}).click();
  await dom.getByRole('button', {name: 'Составить план', exact: true}).click();
  expect(sent.at(-1)).toEqual({action: 'change_domain', new_panel_domain: 'panel2.example.com', keep_old_domain: true});

  // Danger zone: nothing until the server's name is typed.
  const danger = hub.locator('[data-install-danger]');
  await danger.locator('[data-danger-what]').selectOption('node');
  const button = danger.getByRole('button', {name: 'Составить план удаления'});
  await expect(button).toBeDisabled();
  await danger.locator('[data-danger-confirm]').fill('fi-1');
  await button.click();
  await danger.getByRole('button', {name: 'Составить план', exact: true}).click();
  expect(sent.at(-1)).toEqual({action: 'remove_component', component: 'node'});

  // A card of another section opens it.
  await hub.locator('[data-op="selfsteal"]').getByRole('button', {name: 'Открыть'}).click();
  await expect(page.locator('[data-selfsteal]')).toBeVisible();
});
