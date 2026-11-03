import {expect, test} from '@playwright/test';

// v28.66.0 (stage 10): «Установка Remnawave». The registry goes through the real backend (fingerprint required,
// the key never comes back); the browser stand has no VPS, so the server check, the plan and the job are answered
// by route stubs shaped exactly like the backend's responses (tests/test_rw_installer.py runs the same flow against
// a fake SSH server; tests/live/test_install_live.py installs for real in CI).
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

const FP = 'SHA256:' + 'Q'.repeat(43);
const STEPS = ['preflight', 'install_docker', 'write_files', 'compose_up', 'wait_panel', 'panel_bootstrap', 'verify'];

test('add a server, check it, review the plan, run it and read the step log', async ({page}) => {
  test.setTimeout(90_000);
  await signIn(page);
  await page.route('**/api/admin/rw/servers/scan', (route: any) => route.fulfill({json: {fingerprint: FP, key_type: 'ssh-ed25519'}}));
  await page.locator('.sidebar').getByRole('button', {name: /Установка Remnawave/}).click();
  const registry = page.locator('[data-rw-registry]');
  await expect(registry.getByText('Серверов пока нет')).toBeVisible();

  const form = registry.locator('[data-rw-add-server]');
  await form.getByLabel('Название', {exact: true}).fill('e2e-vps');
  await form.getByLabel('IP-адрес или имя хоста', {exact: true}).fill('198.51.100.77');
  await form.getByLabel('Способ входа', {exact: true}).selectOption('password');
  await form.getByLabel('Пароль', {exact: true}).fill('e2e-password');
  const save = form.getByRole('button', {name: 'Сохранить сервер'});
  await expect(save).toBeDisabled();  // no fingerprint yet: no trust on first use
  await form.getByRole('button', {name: 'Получить отпечаток ключа сервера'}).click();
  await expect(form.locator('[data-rw-fingerprint]')).toContainText(FP);
  await expect(save).toBeDisabled();
  await form.getByRole('checkbox', {name: /Отпечаток совпадает/}).check();
  await save.click();
  const row = registry.locator('[data-rw-server="e2e-vps"]');
  await expect(row).toContainText('root@198.51.100.77:22');
  await expect(row).toContainText('не проверен');
  await expect(page.locator('[data-rw-installer]')).not.toContainText('e2e-password');

  // The real check cannot reach 198.51.100.77 from the stand: the reason is shown, the server stays unusable.
  await row.getByRole('button', {name: 'Проверить'}).click();
  await expect(registry.getByRole('alert')).toContainText(/SSH/, {timeout: 40_000});
  await expect(row).toContainText('нет связи');

  // From here the VPS is simulated.
  const ready = {id: 1, name: 'e2e-vps', host: '198.51.100.77', ssh_port: 22, ssh_user: 'root', auth_method: 'password', has_secret: true,
    host_key_fingerprint: FP, purpose: ['panel', 'node'], roles: [], status: 'ready', os: 'Ubuntu 24.04.3 LTS', arch: 'x86_64', cpu_cores: 2,
    ram_mb: 4096, disk_gb: 40, check_ok: true, last_checked_at: new Date().toISOString(),
    checks: [{key: 'ssh', status: 'ok', detail: 'SSH root@198.51.100.77:22, ключ сервера совпал'}, {key: 'docker', status: 'warn', detail: 'Docker нет — будет установлен'}]};
  const steps = STEPS.map((kind, i) => ({kind, server_id: 1, title: `e2e-vps: шаг ${kind}`, params: {}, position: i + 1}));
  const plan = {id: 7, action: 'install', mode: 'panel', title: 'Только панель', server_ids: [1], status: 'planned', plan_sha256: 'a'.repeat(64),
    plan: {mode: 'panel', title: 'Только панель', panel: 'новая', images: {panel: 'remnawave/backend:3@sha256:' + 'd'.repeat(64)},
      servers: {'1': {name: 'e2e-vps', host: '198.51.100.77', roles: ['panel'], changes: ['Caddy занимает порты 80 и 443']}}, steps}, steps: [], progress: 0};
  let approved = false;
  const job = () => ({...plan, status: 'running', progress: 43, approved_by: 'browser@example.test', started_at: new Date().toISOString(),
    steps: steps.map((s, i) => ({id: i + 1, position: s.position, kind: s.kind, title: s.title, server_id: 1,
      status: i < 3 ? 'done' : i === 3 ? 'running' : 'pending', log: i === 0 ? 'ok: Ubuntu 24.04.3 LTS' : null}))});
  await page.route('**/api/admin/rw/servers', (route: any) => route.request().method() === 'GET' ? route.fulfill({json: {servers: [ready]}}) : route.continue());
  await page.route('**/api/admin/rw/installations', (route: any) => route.fulfill({json: {installations: approved ? [{...job(), steps: undefined, current_step: 'e2e-vps: шаг compose_up'}] : []}}));
  await page.route('**/api/admin/rw/installations/plan', (route: any) => route.fulfill({json: plan}));
  await page.route('**/api/admin/rw/installations/7/approve', (route: any) => {
    expect(route.request().postDataJSON()).toEqual({plan_sha256: 'a'.repeat(64)});
    approved = true;
    return route.fulfill({json: job()});
  });
  await page.route('**/api/admin/rw/installations/7', (route: any) => route.fulfill({json: job()}));
  await page.locator('.sidebar').getByRole('button', {name: /Состояние системы/}).click();
  await page.locator('.sidebar').getByRole('button', {name: /Установка Remnawave/}).click();
  await expect(registry.locator('[data-rw-server="e2e-vps"]')).toContainText('готов');
  await registry.getByRole('button', {name: 'Отчёт'}).click();
  await expect(registry.locator('[data-rw-checks]')).toContainText('ключ сервера совпал');

  const wizard = page.locator('[data-rw-wizard]');
  await expect(wizard.locator('[data-rw-mode] option')).toHaveCount(7);
  await wizard.getByLabel('Режим', {exact: true}).selectOption('panel');
  await wizard.getByLabel('Сервер панели', {exact: true}).selectOption('1');
  await wizard.getByLabel('Домен панели', {exact: true}).fill('panel.example.com');
  await wizard.getByLabel('Email для Let\'s Encrypt', {exact: true}).fill('owner@example.com');
  await wizard.getByRole('button', {name: 'Составить план'}).click();
  const shown = wizard.locator('[data-rw-plan]');
  await expect(shown).toContainText('Caddy занимает порты 80 и 443');
  await expect(shown.locator('[data-rw-plan-steps] li')).toHaveCount(STEPS.length);
  await shown.getByRole('button', {name: 'Запустить по этому плану'}).click();

  const jobs = page.locator('[data-rw-jobs]');
  await expect(jobs.locator('[data-rw-job="7"]')).toContainText('выполняется');
  await expect(jobs.locator('[data-rw-job="7"]')).toContainText('43%');
  const detail = jobs.locator('[data-rw-job-detail="7"]');
  await expect(detail).toContainText('ok: Ubuntu 24.04.3 LTS');
  await expect(detail.locator('[data-kind="compose_up"]')).toHaveAttribute('data-status', 'running');
  await expect(detail.getByRole('button', {name: 'Остановить и откатить'})).toBeVisible();
});

// v28.70.0 (stage 12): SelfSteal in the wizard and the node modules of a finished installation.
test('SelfSteal fields, node modules plan and Xray Checker results', async ({page}) => {
  test.setTimeout(60_000);
  const server = (id: number, name: string) => ({id, name, host: `198.51.100.${id}`, ssh_port: 22, ssh_user: 'root', auth_method: 'key', has_secret: true,
    host_key_fingerprint: FP, purpose: ['node'], roles: ['node'], status: 'installed', arch: 'x86_64', checks: [], check_ok: true});
  const job = {id: 9, action: 'install', mode: 'node', title: 'Только нода', server_ids: [2], status: 'succeeded', progress: 100,
    params: {mode: 'node', node_server_ids: [2], selfsteal_domain: 'node.example.com', xray_checker_server_id: 2},
    plan: {servers: {'2': {name: 'fi-1', host: '198.51.100.2', roles: ['node', 'selfsteal'], changes: []}}, steps: []},
    result: {state: {modules: {'2': {ipv6: 'off', xray_core: 'v25.10.15'}}}}, steps: [{id: 1, position: 1, kind: 'verify', title: 'Проверка', server_id: null, status: 'done', log: 'ok'}]};
  await signIn(page);
  await page.route('**/api/admin/rw/servers', (r: any) => r.fulfill({json: {servers: [server(2, 'fi-1'), server(3, 'de-1')]}}));
  await page.route('**/api/admin/rw/installations', (r: any) => r.fulfill({json: {installations: [{...job, steps: undefined}]}}));
  await page.route('**/api/admin/rw/installations/9', (r: any) => r.fulfill({json: job}));
  let sent: any = null;
  await page.route('**/api/admin/rw/installations/9/actions', (r: any) => {
    sent = r.request().postDataJSON();
    return r.fulfill({json: {id: 10, plan_sha256: 'b'.repeat(64), plan: {title: 'Модуль: NetBird: включить',
      steps: [{position: 1, kind: 'node_module', title: 'fi-1: NetBird — подключить'}]}}});
  });
  await page.route('**/api/admin/rw/installations/9/xray-checker', (r: any) => r.fulfill({json: {server_id: 2, total: 2, online: 1, proxies: [
    {name: 'fi-1', server: '198.51.100.2', port: 443, protocol: 'vless', online: true, latency_ms: 41},
    {name: 'de-1', server: '198.51.100.3', port: 443, protocol: 'vless', online: false, latency_ms: 0}]}}));
  await page.locator('.sidebar').getByRole('button', {name: /Установка Remnawave/}).click();

  const wizard = page.locator('[data-rw-wizard]');
  await wizard.getByLabel('Режим', {exact: true}).selectOption('node');
  await wizard.getByLabel('Серверы нод', {exact: true}).selectOption(['2']);
  const ss = wizard.locator('[data-rw-selfsteal]');
  await expect(ss).toContainText('TLS + REALITY');
  await ss.getByLabel('Домен ноды', {exact: true}).fill('node.example.com');
  await expect(ss.getByLabel('Сайт-шаблон', {exact: true}).locator('option')).toHaveCount(3);
  await wizard.getByLabel('Серверы нод', {exact: true}).selectOption(['2', '3']);
  await expect(ss).toHaveCount(0);  // one domain — one node

  await page.locator('[data-rw-job="9"]').getByRole('button', {name: 'Журнал'}).click();
  const mods = page.locator('[data-rw-modules]');
  await expect(mods.locator('[data-rw-module-state]')).toContainText('IPv6 выключен, ядро v25.10.15');
  await mods.getByLabel('Модуль', {exact: true}).selectOption('netbird');
  await mods.getByLabel('Действие', {exact: true}).selectOption('on');
  await mods.getByLabel('Ключ установки (Setup key)', {exact: true}).fill('ABCDEF12-3456-7890');
  await mods.getByRole('button', {name: 'Составить план'}).click();
  await expect(page.locator('[data-rw-action-plan]')).toContainText('fi-1: NetBird — подключить');
  expect(sent).toMatchObject({action: 'module', module: {name: 'netbird', enabled: true, setup_key: 'ABCDEF12-3456-7890', server_ids: [2]}});
  await expect(mods.getByLabel('Ключ установки (Setup key)', {exact: true})).toHaveValue('');

  await mods.getByRole('button', {name: 'Результаты Xray Checker'}).click();
  await expect(mods.locator('[data-rw-checker]')).toContainText('На связи 1 из 2');
  await expect(mods.locator('[data-online="false"]')).toContainText('недоступен');
});
