import {expect, test} from '@playwright/test';

// v28.129.0: «Смена протокола» → «MASQUE: ноды и подписка». The backend is a stub shaped like backend/app/masque_panel.py
// (tests/test_masque_panel.py checks the rules; scripts/ci/masque-check.sh runs the node part for real).
const SHIELD = {strict_sni: true, tls_like_site: true, probe_ban: true, ban_after: 30, ban_minutes: 10};
const node = (over: object = {}) => ({server_id: 3, name: 'de-1', address: '203.0.113.5', domain: 'de.example.com', ready: true, installed: false, port: null, users: null, synced_at: null, error: null, shield: null, ...over});
const view = (over: object = {}) => ({enabled: false, plan_ids: [], port: 2087, plans: [{id: 1, name: 'Lucy Max', enabled: true, traffic_limit_gb: null}, {id: 2, name: 'Lucy Mini', enabled: true, traffic_limit_gb: 50}],
  nodes: [node(), node({server_id: 4, name: 'cz-1', domain: null, ready: false})], users: 0, images: {xray: 'ghcr.io/xtls/xray-core:26.11.9', haproxy: 'haproxy:3.2-alpine'},
  notes: ['Трафик MASQUE не входит в лимит трафика тарифа: панель Remnawave его не видит.'], shield_default: SHIELD, ...over});

test('MASQUE panel: settings, install on a node, status, subscriptions, removal', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  let current: any = view();
  const sent: any[] = [];
  await page.route('**/api/admin/masque/panel', (r: any) => r.fulfill({json: current}));
  await page.route('**/api/admin/masque/panel/settings', (r: any) => {
    const body = r.request().postDataJSON();
    sent.push(['settings', body]);
    current = view({...body, users: 2});
    return r.fulfill({json: current});
  });
  await page.route('**/api/admin/masque/panel/nodes/3/install', (r: any) => {
    const shield = r.request().postDataJSON().shield;
    sent.push(['install', shield]);
    current = {...current, nodes: [node({installed: true, port: current.port, users: 2, synced_at: '2026-11-12T12:00:00Z', shield}), current.nodes[1]]};
    return r.fulfill({json: current});
  });
  await page.route('**/api/admin/masque/panel/nodes/3/probe', (r: any) => r.fulfill({json: {domain: 'de.example.com', port: 2090, same: false, checks: [
    {check: 'Главная страница', same: true, differences: []}, {check: 'Несуществующая страница', same: false, differences: ['заголовок server: лишний']}],
    limits: ['Порт не 443: сайт на нестандартном порту сам по себе необычен.']}}));
  await page.route('**/api/admin/masque/panel/nodes/3/status', (r: any) => r.fulfill({json: {users: 2, port: 2090, certificate_until: 'Feb 10 2027 GMT',
    traffic: [{subscription_id: 11, user_id: 7, login: 'm1', uplink: 1048576, downlink: 52428800}]}}));
  await page.route('**/api/admin/masque/panel/users?limit=50', (r: any) => r.fulfill({json: {total: 1, items: [{subscription_id: 11, user_id: 7, plan_id: 1, login: 'm1',
    expires_at: '2026-12-12T00:00:00Z', url: 'https://shop.example.com/api/masque/sub/11.abc'}]}}));
  await page.route('**/api/admin/masque/panel/sync', (r: any) => {
    sent.push(['sync', 0]);
    return r.fulfill({json: current});
  });
  await page.route('**/api/admin/masque/panel/users/11/reissue', (r: any) => {
    sent.push(['reissue', 11]);
    return r.fulfill({json: {subscription_id: 11, url: 'https://shop.example.com/api/masque/sub/11.new', login: 'm9'}});
  });
  await page.route('**/api/admin/masque/panel/nodes/3/remove', (r: any) => {
    sent.push(['remove', 3]);
    current = {...current, nodes: [node(), current.nodes[1]]};
    return r.fulfill({json: current});
  });

  await page.locator('.sidebar').getByRole('button', {name: /Смена протокола/}).click();
  const root = page.locator('[data-masque-panel]');
  await expect(root.locator('[data-masque-panel-summary]')).toContainText('Доступ не выдаётся');
  await expect(root).toContainText('Трафик MASQUE не входит в лимит трафика тарифа');
  await expect(root.locator('[data-masque-panel-node="cz-1"]')).toContainText('нет сайта SelfSteal');
  await expect(root.locator('[data-masque-panel-node="cz-1"]').getByRole('button', {name: 'Установить', exact: true})).toBeDisabled();

  // Settings: nothing to save until something changed; a bad port is refused in the form.
  const save = root.getByRole('button', {name: 'Сохранить', exact: true});
  await expect(save).toBeDisabled();
  await root.getByLabel('Выдавать MASQUE по действующим подпискам', {exact: true}).check();
  await root.getByLabel(/^Lucy Max/).check();
  const port = root.getByLabel('Порт для новых установок (TCP, от 1024)', {exact: true});
  await port.fill('443');
  await expect(root.getByRole('alert')).toHaveText('Порт — число от 1024 до 65535.');
  await expect(save).toBeDisabled();
  await port.fill('2090');
  await save.click();
  await expect(root.locator('[data-masque-panel-summary]')).toContainText('Доступ выдаётся');
  await expect(root.locator('[data-masque-panel-summary]')).toContainText('Подписок с доступом: 2');
  expect(sent[0]).toEqual(['settings', {enabled: true, plan_ids: [1], port: 2090}]);

  // Install on the node that has a SelfSteal site: the protections are chosen first (owner's decision of 2026-11-12).
  await root.locator('[data-masque-panel-node="de-1"]').getByRole('button', {name: 'Установить', exact: true}).click();
  const setup = root.locator('[data-masque-panel-setup]');
  await expect(setup).toContainText('Всегда включено');
  await setup.getByLabel(/^Строгий SNI/).uncheck();
  const after = setup.getByLabel('Отказов до блокировки (5–500)', {exact: true});
  await after.fill('2');
  await expect(setup.getByRole('alert')).toHaveText('Порог — от 5 до 500, срок — от 1 до 1440 минут.');
  await expect(setup.getByRole('button', {name: 'Установить', exact: true})).toBeDisabled();
  await after.fill('40');
  await setup.getByRole('button', {name: 'Установить', exact: true}).click();
  await expect(root.locator('[data-masque-panel-node="de-1"]')).toContainText('работает, порт 2090');
  await expect(root.locator('[data-masque-panel-node="de-1"]')).toContainText('TLS как у сайта, блокировка после 40 отказов на 10 мин.');
  expect(sent[1]).toEqual(['install', {...SHIELD, strict_sni: false, ban_after: 40}]);

  // The look from outside: what differs from the site is named.
  await root.locator('[data-masque-panel-node="de-1"]').getByRole('button', {name: 'Проверить маскировку', exact: true}).click();
  await expect(root.locator('[data-masque-panel-probe]')).toContainText('Есть отличия от сайта');
  await expect(root.locator('[data-masque-panel-probe]')).toContainText('заголовок server: лишний');

  // Changing the protections of an installed node warns that tunnels reconnect; «Отмена» sends nothing.
  await root.locator('[data-masque-panel-node="de-1"]').getByRole('button', {name: 'Изменить защиты', exact: true}).click();
  await expect(root.locator('[data-masque-panel-setup]')).toContainText('открытые туннели на этой ноде переподключатся');
  await root.locator('[data-masque-panel-setup]').getByRole('button', {name: 'Отмена', exact: true}).click();
  await expect(root.locator('[data-masque-panel-setup]')).toHaveCount(0);
  await expect(root.locator('[data-masque-panel-summary]')).toContainText('Нод с MASQUE: 1');

  await root.locator('[data-masque-panel-node="de-1"]').getByRole('button', {name: 'Проверить', exact: true}).click();
  await expect(root.locator('[data-masque-panel-status]')).toContainText('Пользователей в Xray: 2');
  await expect(root.locator('[data-masque-panel-status]')).toContainText('50 МБ');

  await root.getByRole('button', {name: 'Сверить пользователей сейчас', exact: true}).click();
  await expect.poll(() => sent.some((x) => x[0] === 'sync')).toBe(true);

  await root.getByRole('button', {name: 'Показать список и ссылки', exact: true}).click();
  await expect(root.locator('[data-masque-panel-users]')).toContainText('m1');
  await expect(root.getByRole('button', {name: 'Скопировать ссылку подписки 11', exact: true})).toBeVisible();

  // A new link for a subscription: asks first, then the row shows the new login.
  await root.getByRole('button', {name: 'Выдать новую ссылку подписке 11', exact: true}).click();
  await expect(root.locator('[data-masque-panel-reissue]')).toContainText('Старая ссылка и логин перестанут работать сразу');
  await root.locator('[data-masque-panel-reissue]').getByRole('button', {name: 'Выдать новую', exact: true}).click();
  await expect(root.locator('[data-masque-panel-users]')).toContainText('m9');

  // Removal asks first; «Отмена» changes nothing.
  await root.locator('[data-masque-panel-node="de-1"]').getByRole('button', {name: 'Удалить', exact: true}).click();
  const dialog = root.locator('[data-masque-panel-confirm]');
  await expect(dialog).toContainText('Туннели её пользователей оборвутся');
  await dialog.getByRole('button', {name: 'Отмена', exact: true}).click();
  await expect(dialog).toHaveCount(0);
  expect(sent.filter((s) => s[0] === 'remove')).toHaveLength(0);
  await root.locator('[data-masque-panel-node="de-1"]').getByRole('button', {name: 'Удалить', exact: true}).click();
  await root.locator('[data-masque-panel-confirm]').getByRole('button', {name: 'Удалить', exact: true}).click();
  await expect(root.locator('[data-masque-panel-node="de-1"]')).toContainText('не установлен');
  expect(sent.map((s) => s[0])).toEqual(['settings', 'install', 'sync', 'reissue', 'remove']);
});
