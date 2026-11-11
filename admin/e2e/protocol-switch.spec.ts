import {expect, test} from '@playwright/test';

// v28.113.0: «Серверы → Смена протокола». The backend is a stub shaped like backend/app/rw_protocol_switch.py
// (tests/test_rw_protocol_switch.py runs the same flow against a model of the Remnawave panel).
const PROFILE = '00000001-0000-4000-8000-000000000000';
const stage = (key: string, title: string, status: string, log: string[] = ['2026-11-11T05:00:00+00:00 запись']) => ({key, title, status, started_at: '2026-11-11T05:00:00+00:00', finished_at: status === 'running' ? null : '2026-11-11T05:00:01+00:00', log});
const node = (n: number, name: string, country: string, online: boolean, error: string | null = null) => ({n, uuid: `n${n}`, country, name, online, disabled: false, was_online: true, transport: 'xhttp', error, checked_at: '2026-11-11T05:00:05+00:00'});

function job(status: string, nodes: any[] = [], extra: object = {}) {
  const online = nodes.filter((r) => r.online).length;
  return {id: 'run1', created_at: '2026-11-11T05:00:00+00:00', actor: 'owner', profile_name: 'Узлы', inbound_tag: 'STEAL-T12', from: 'grpc', to: 'xhttp', status,
    summary: status === 'partial' ? `На связи ${online} из ${nodes.length} нод. Смена не считается успешной, пока не подключились все.` : status === 'succeeded' ? `Все ноды на связи: ${online} из ${nodes.length}.` : status === 'rolled_back' ? 'Возвращён прежний транспорт gRPC.' : '',
    hosts_updated: 1, restored: status === 'rolled_back' ? ['inbound STEAL-T12: транспорт gRPC возвращён'] : [], nodes, checks: nodes.length ? 1 : 0,
    stages: [stage('read', 'Чтение текущего транспорта', 'done'), stage('switch', 'Смена протокола inbound', 'done'), stage('hosts', 'Обновление hosts', 'done'),
      stage('reconnect', 'Проверка реконнекта нод', status === 'checking' ? 'running' : status === 'succeeded' ? 'done' : 'partial')], ...extra};
}

test('protocol switch: gRPC to XHTTP, a partial reconnect is not a success, rollback', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  const sent: any[] = [];
  let checks = 0, rolledBack = false;
  await page.route('**/api/admin/rw/protocol-switch', (r: any) => {
    if (r.request().method() === 'POST') { sent.push(r.request().postDataJSON()); return r.fulfill({json: job('checking')}); }
    return r.fulfill({json: {transports: {tcp: 'TCP (RAW)', xhttp: 'XHTTP', grpc: 'gRPC'}, jobs: [], profiles: [{uuid: PROFILE, name: 'Узлы', inbounds: [
      {tag: 'STEAL-T12', protocol: 'vless', port: 8443, network: 'grpc', security: 'reality', hosts: 1, nodes: 3, nodes_online: 3, switchable: true},
      {tag: 'HY2', protocol: 'hysteria', port: 4443, network: 'hysteria', security: 'tls', hosts: 1, nodes: 3, nodes_online: 3, switchable: false}]}]}});
  });
  await page.route('**/api/admin/rw/protocol-switch/run1/check', (r: any) => {
    checks += 1;
    // Two of three nodes on every look: the third never comes back.
    return r.fulfill({json: job('partial', [node(1, 'cz-1', 'CZ', true), node(2, 'de-1', 'DE', true), node(3, 'nl-2', 'NL', false, 'connect ETIMEDOUT')])});
  });
  await page.route('**/api/admin/rw/protocol-switch/run1/rollback', (r: any) => { rolledBack = true; return r.fulfill({json: job('rolled_back')}); });
  page.on('dialog', (d: any) => d.accept());

  await page.locator('.sidebar').getByRole('button', {name: /Смена протокола/}).click();
  const root = page.locator('[data-protocol-switch]');
  await expect(root.getByRole('heading', {name: 'Починка блока: смена протокола'})).toBeVisible();
  await root.getByLabel('Профиль', {exact: true}).selectOption(PROFILE);
  // An inbound that is not a VLESS/Trojan stream cannot be chosen.
  await expect(root.getByLabel('Inbound', {exact: true}).locator('option', {hasText: 'HY2'})).toBeDisabled();
  await root.getByLabel('Inbound', {exact: true}).selectOption('STEAL-T12');
  await expect(root.locator('[data-current]')).toContainText('gRPC, порт 8443. Hosts: 1. Нод: 3, на связи 3.');
  // The current transport is not offered as a target.
  await expect(root.getByLabel('Новый транспорт', {exact: true}).locator('option')).toHaveText(['— выберите транспорт —', 'TCP (RAW)', 'XHTTP']);
  await expect(root.getByRole('button', {name: 'Сменить протокол', exact: true})).toBeDisabled();
  await root.getByLabel('Новый транспорт', {exact: true}).selectOption('xhttp');
  await root.getByRole('button', {name: 'Сменить протокол', exact: true}).click();
  expect(sent).toEqual([{profile_uuid: PROFILE, inbound_tag: 'STEAL-T12', target: 'xhttp'}]);

  // Four stages with their state; the node table; a partial reconnect is shown as partial, with the reason.
  const run = root.locator('[data-job]');
  await expect(run.locator('[data-stage]')).toHaveCount(4);
  await expect(run.locator('[data-stage="hosts"]')).toContainText('выполнен');
  await expect(run.locator('[data-reconnect]')).toHaveText('Ноды на связи: 2 из 3');
  await expect(run).toHaveAttribute('data-job', 'partial');
  await expect(run.getByText('Частично', {exact: true})).toBeVisible();
  await expect(run.getByText('Успешно', {exact: true})).toHaveCount(0);
  await expect(run.locator('[data-node="nl-2"]')).toContainText('не на связи');
  await expect(run.locator('[data-node="nl-2"]')).toContainText('connect ETIMEDOUT');
  await run.locator('[data-stage="read"] summary').click();
  await expect(run.locator('[data-stage="read"] pre')).toContainText('запись');
  expect(checks).toBeGreaterThan(0);

  await run.getByRole('button', {name: 'Вернуть прежний транспорт', exact: true}).click();
  await expect(run).toHaveAttribute('data-job', 'rolled_back');
  await expect(run.getByText('inbound STEAL-T12: транспорт gRPC возвращён')).toBeVisible();
  expect(rolledBack).toBe(true);
  await expect(run.getByRole('button', {name: 'Вернуть прежний транспорт', exact: true})).toHaveCount(0);
  await run.getByRole('button', {name: 'К списку', exact: true}).click();
  await expect(root.locator('[data-job]')).toHaveCount(0);
});
