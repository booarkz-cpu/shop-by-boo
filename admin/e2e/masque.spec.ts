import {expect, test} from '@playwright/test';

// v28.128.0: «Смена протокола» → «MASQUE (CONNECT-IP)». The backend is a stub shaped like backend/app/masque.py
// (tests/test_masque.py checks the versions, the inbound and the port conflicts).
const blockers = [{key: 'panel', title: 'Панель Remnawave не знает MASQUE', text: 'Панель не добавляет пользователей.'},
  {key: 'link', title: 'Нет общей ссылки для клиента', text: 'Только JSON.'}, {key: 'reality', title: 'Не работает с REALITY', text: 'Только TLS.'}];
const view = (port: number, conflicts: string[]) => ({required: 'v26.10.21', first_tag: 'v26.9.30', port, http: ['h3', 'h2'], nodes_ready: 1,
  nodes: [{uuid: 'n1', name: 'de-1', xray: '26.11.9', state: 'ready'}, {uuid: 'n2', name: 'cz-1', xray: '26.7.28', state: 'old'}, {uuid: 'n3', name: 'nl-1', xray: null, state: 'unknown'}],
  profiles: [{uuid: 'p1', name: 'Основной', conflicts}], blockers, can_enable: false, example: {tag: 'MASQUE', port, protocol: 'masque'}});

test('MASQUE readiness: nodes, blockers and the port check', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();

  const asked: string[] = [];
  await page.route('**/api/admin/masque?port=*', (r: any) => {
    const port = Number(new URL(r.request().url()).searchParams.get('port'));
    asked.push(String(port));
    return r.fulfill({json: view(port, port === 443 ? ['UDP 443 занят inbound «HYSTERIA2»', 'TCP 443 занят inbound «VLESS_TCP_REALITY»'] : [])});
  });

  await page.locator('.sidebar').getByRole('button', {name: /Смена протокола/}).click();
  const root = page.locator('[data-masque]');
  await expect(root.locator('[data-masque-summary]')).toContainText('Не включается');
  await expect(root.locator('[data-masque-summary]')).toContainText('Ноды с подходящим ядром: 1 из 3');
  await expect(root).toContainText('Нужно ядро Xray v26.10.21 или новее');
  await expect(root.locator('[data-masque-blocker]')).toHaveCount(3);
  await expect(root.locator('[data-masque-node="de-1"]')).toContainText('подходит');
  await expect(root.locator('[data-masque-node="cz-1"]')).toContainText('старое ядро');
  await expect(root.locator('[data-masque-node="nl-1"]')).toContainText('версия неизвестна');
  await expect(root.locator('[data-masque-profile="Основной"]')).toContainText('свободен');
  await expect(root.getByRole('button', {name: /включить/i})).toHaveCount(0);   // nothing pretends to switch MASQUE on

  const port = root.getByLabel('Порт MASQUE (UDP для HTTP/3 и TCP для HTTP/2)', {exact: true});
  await port.fill('99999');
  await expect(root.getByRole('alert')).toHaveText('Порт — число от 1 до 65535.');
  await expect(root.getByRole('button', {name: 'Проверить порт', exact: true})).toBeDisabled();
  await port.fill('443');
  await root.getByRole('button', {name: 'Проверить порт', exact: true}).click();
  await expect(root.locator('[data-masque-profile="Основной"]')).toContainText('UDP 443 занят inbound «HYSTERIA2»');
  expect(asked).toEqual(['2087', '443']);

  await root.getByText('Проверенный inbound для Xray', {exact: true}).click();
  await expect(root.locator('[data-masque-example]')).toContainText('"protocol": "masque"');
});
