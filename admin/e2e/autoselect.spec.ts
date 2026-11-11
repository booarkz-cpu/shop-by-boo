import {expect, test} from '@playwright/test';

// v28.112.0: «Серверы → Пул автовыбора». The panel is answered by a stub shaped like backend/app/rw_autoselect.py
// (tests/test_rw_autoselect.py runs the same flow against a model of the Remnawave panel).
const DE = '00000001-0000-4000-8000-000000000000', CZ = '00000002-0000-4000-8000-000000000000', OFF = '00000004-0000-4000-8000-000000000000';
const host = (uuid: string, name: string, country: string, extra: object = {}) => ({uuid, name, address: `${country.toLowerCase()}1.example.com`, country,
  in_pool: false, hidden: false, disabled: false, online: true, users_online: 3, nodes: [`${country.toLowerCase()}-1`], ...extra});

function view(state: any) {
  const hosts = [host(DE, 'Германия №1', 'DE'), host(CZ, 'Чехия №1', 'CZ', {online: false, users_online: 0}), host(OFF, 'Выключенный', 'NL', {disabled: true, online: null, users_online: null})]
    .map((h) => ({...h, in_pool: state.hosts.includes(h.uuid), hidden: state.enabled && state.hide_nodes && state.hosts.includes(h.uuid)}));
  const pool = hosts.filter((h) => h.in_pool);
  return {enabled: state.enabled, name: state.name, algorithm: state.algorithm, hide_nodes: state.hide_nodes, applied_at: state.enabled ? '2026-11-10T20:00:00+00:00' : null,
    checked_at: '2026-11-10T20:00:05+00:00',
    algorithms: {leastPing: 'По задержке — узел с наименьшим временем ответа', leastLoad: 'По нагрузке — узел с самым стабильным ответом за последние замеры',
      roundRobin: 'По кругу — узлы по очереди', random: 'Случайно — любой доступный узел'},
    tile: {exists: state.enabled, name: state.enabled ? state.name : null, visible: state.enabled, formats_excluded: []},
    stats: {hosts_total: 2, in_subscription: hosts.filter((h) => !h.disabled && !h.hidden).length, pool_total: pool.length, pool_served: pool.length,
      pool_online: pool.filter((h) => h.online).length, pool_offline: pool.filter((h) => h.online === false).length, pool_unknown: 0,
      excluded: 2 - pool.length, missing: []},
    json_at_base: false, hosts};
}

test('auto-selection pool: choose nodes, switch on, hide, refresh, remove', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  const state: any = {enabled: false, name: '⚡ Автовыбор', algorithm: 'leastPing', hide_nodes: false, hosts: []};
  const sent: any[] = [];
  let refreshed = 0;
  await page.route('**/api/admin/rw/autoselect', (r: any) => {
    const method = r.request().method();
    if (method === 'PUT') { const body = r.request().postDataJSON(); sent.push(body); Object.assign(state, body, {enabled: true}); }
    if (method === 'DELETE') Object.assign(state, {enabled: false, hide_nodes: state.hide_nodes});
    return r.fulfill({json: view(state)});
  });
  await page.route('**/api/admin/rw/autoselect/refresh', (r: any) => { refreshed += 1; return r.fulfill({json: view(state)}); });
  page.on('dialog', (d: any) => d.accept());

  await page.locator('.sidebar').getByRole('button', {name: /Пул автовыбора/}).click();
  const root = page.locator('[data-autoselect]');
  await expect(root.getByText('Плитки нет')).toBeVisible();
  await expect(root.locator('[data-stat="subscription"]')).toContainText('Видны в подписке: 2/2');
  // Real state per node; a disabled host cannot be chosen; the panel setting is reported, not hidden.
  await expect(root.locator(`[data-host="${CZ}"]`)).toContainText('не на связи');
  await expect(root.getByLabel('В пуле: Выключенный', {exact: true})).toBeDisabled();
  await expect(root.getByText('Формат Xray JSON не основной')).toBeVisible();
  const start = root.getByRole('button', {name: 'Включить leastPing'});
  await expect(start).toBeDisabled();  // nothing chosen yet

  await root.getByRole('button', {name: 'Выбрать все', exact: true}).click();
  await root.getByLabel('Алгоритм', {exact: true}).selectOption('leastLoad');
  await root.getByLabel('Имя плитки', {exact: true}).fill('🚀 Быстрый');
  await expect(root.getByText('В Clash, Mihomo, sing-box и Base64 плитка не показывается')).toBeVisible();
  await root.getByRole('button', {name: 'Включить leastLoad'}).click();
  await expect(root.getByText('Плитка включена')).toBeVisible();
  expect(sent[0]).toEqual({name: '🚀 Быстрый', algorithm: 'leastLoad', hide_nodes: false, hosts: [DE, CZ]});
  await expect(root.locator('[data-stat="pool"]')).toContainText('В пуле: 2/2');
  await expect(root.locator('[data-stat="pool"]')).toContainText('на связи 1, не на связи 1');

  await root.getByLabel('Скрыть узлы пула из списка приложения', {exact: true}).check();
  await expect(root.getByText('там плитка ведёт на первый узел пула')).toBeVisible();  // the honest limit of other formats
  await root.getByRole('button', {name: 'Сохранить и обновить пул'}).click();
  await expect(root.locator('[data-stat="subscription"]')).toContainText('Видны в подписке: 0/2');
  expect(sent[1].hide_nodes).toBe(true);

  await root.getByRole('button', {name: 'Обновить пул', exact: true}).click();
  await expect.poll(() => refreshed).toBe(1);
  await root.getByRole('button', {name: 'Убрать плитку', exact: true}).click();
  await expect(root.getByText('Плитки нет')).toBeVisible();
  await expect(root.getByRole('button', {name: 'Убрать плитку', exact: true})).toHaveCount(0);
});
