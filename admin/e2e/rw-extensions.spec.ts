import {expect, test} from '@playwright/test';

// v28.69.0 (stage 12): «Расширения Remnawave». The browser stand has no Remnawave panel: without it the section says
// so; the rest is answered by route stubs shaped like the panel's answers (the real panel runs in
// tests/live/test_remnawave_live.py::test_extensions_*).
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

const P = '11111111-1111-1111-1111-111111111111', I = '22222222-2222-2222-2222-222222222222', N = '33333333-3333-3333-3333-333333333333';
const PLUGIN = '44444444-4444-4444-4444-444444444444';

test('without a panel the section explains why', async ({page}) => {
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Расширения Remnawave/}).click();
  await expect(page.locator('main [role="alert"]').first()).toContainText(/Remnawave/);
  await expect(page.getByRole('button', {name: 'Повторить'})).toBeVisible();
});

test('REALITY profile builder, plugins on a node and the SRR tester', async ({page}) => {
  test.setTimeout(60_000);
  let plugin = {uuid: PLUGIN, name: 'Lucy', config: {torrentBlocker: {enabled: false, blockDuration: 3600, ignoreLists: {ip: []}}}, nodes: [] as string[]};
  const overview = () => ({profiles: [{uuid: P, name: 'Default', inbounds: [{uuid: I, tag: 'VLESS_TCP_REALITY', type: 'vless', port: 443}], nodes: ['fi-1']}],
    plugins: [plugin], nodes: [{uuid: N, name: 'fi-1', profile: P, inbounds: [I], plugin: plugin.nodes.length ? PLUGIN : null}],
    plugin_kinds: ['torrentBlocker'], template_types: ['XRAY_JSON'], selfsteal_socket: '/dev/shm/selfsteal.sock'});
  await page.route('**/api/admin/rw/extensions', (r: any) => r.fulfill({json: overview()}));
  let built: any = null;
  await page.route('**/api/admin/rw/extensions/profiles/reality', (r: any) => { built = r.request().postDataJSON(); return r.fulfill({json: {uuid: P, name: built.name, inbounds: [], public_key: 'PUBKEY123', short_ids: ['0123456789abcdef']}}); });
  await page.route(`**/api/admin/rw/extensions/plugins/${PLUGIN}`, (r: any) => { plugin = {...plugin, config: r.request().postDataJSON().config}; return r.fulfill({json: plugin}); });
  await page.route(`**/api/admin/rw/extensions/nodes/${N}/plugin`, (r: any) => { plugin = {...plugin, nodes: r.request().postDataJSON().plugin_uuid ? ['fi-1'] : []}; return r.fulfill({json: {}}); });
  await page.route('**/api/admin/rw/extensions/subscription-settings', (r: any) => r.fulfill({json: {uuid: N, responseRules: {version: '1', settings: {}, rules: []}, hwidSettings: {enabled: true}, customResponseHeaders: {}}}));
  await page.route('**/api/admin/rw/extensions/srr-test', (r: any) => r.fulfill({json: {matched: false, responseType: 'XRAY_BASE64', matchedRule: null, inputHeaders: {}, outputHeaders: {}}}));
  await page.route('**/api/admin/rw/extensions/subpage-configs', (r: any) => r.fulfill({json: {configs: []}}));
  await page.route('**/api/admin/rw/extensions/templates', (r: any) => r.fulfill({json: {templates: []}}));
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Расширения Remnawave/}).click();

  const profiles = page.locator('[data-rw-profiles]');
  await expect(profiles.locator('[data-profile="Default"]')).toContainText('fi-1');
  const form = profiles.locator('[data-reality-builder]');
  await form.getByLabel('Название', {exact: true}).fill('Lucy-REALITY');
  await form.getByLabel('Домены SNI (serverNames)', {exact: true}).fill('node1.example.com');
  await form.getByLabel('Минимальная версия клиента', {exact: true}).fill('25.1.1');
  await form.getByRole('button', {name: 'Создать профиль'}).click();
  await expect(profiles.locator('[data-reality-made]')).toContainText('PUBKEY123');
  expect(built).toMatchObject({name: 'Lucy-REALITY', server_names: ['node1.example.com'], dest: 'selfsteal', min_client_ver: '25.1.1', port: 443});

  const plugins = page.locator('[data-rw-plugins]');
  await plugins.locator('[data-plugin="Lucy"]').getByRole('button', {name: 'Настроить'}).click();
  await plugins.getByRole('checkbox', {name: /TorrentBlocker/}).click();
  await expect(plugins.locator('[data-plugin="Lucy"]')).toContainText('torrentBlocker');
  await plugins.getByRole('checkbox', {name: 'fi-1'}).click();
  await expect(plugins.locator('[data-plugin="Lucy"]')).toContainText('ноды: fi-1');

  const srr = page.locator('[data-rw-srr]');
  await srr.getByRole('textbox', {name: 'User-Agent для проверки'}).fill('Happ/2.0');
  await srr.getByRole('button', {name: 'Проверить правило'}).click();
  await expect(srr.locator('[data-srr-result]')).toContainText('XRAY_BASE64');
});
