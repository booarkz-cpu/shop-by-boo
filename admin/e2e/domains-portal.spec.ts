import {expect, test} from '@playwright/test';

// v28.67.0 (stage 11): «Домены и сертификаты» and «Портал подписки» against the real backend of the browser stand.
// DNS and TLS checks need the internet and are covered by tests/test_subscription_portal.py and the CI job «caddy».
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

test('add, switch off and remove a portal domain; routes and certificates are listed', async ({page}) => {
  test.setTimeout(60_000);
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Домены и сертификаты/}).click();
  const list = page.locator('[data-domain-list]');
  await expect(list.getByText('Доменов пока нет')).toBeVisible();
  const form = list.locator('[data-add-domain]');
  await form.getByLabel('Домен', {exact: true}).fill('sub.e2e-corgi.test');
  await form.getByRole('button', {name: 'Добавить', exact: true}).click();
  const row = list.locator('[data-domain="sub.e2e-corgi.test"]');
  await expect(row).toContainText('Портал подписки');
  await expect(row).toContainText('не проверен');
  await page.locator('[data-proxy-routes]').waitFor();
  await expect(page.locator('[data-proxy-routes]')).toContainText('sub.e2e-corgi.test');
  await expect(page.locator('[data-certificates]')).toContainText('Let\'s Encrypt');
  await row.getByRole('button', {name: 'Выключить'}).click();
  await expect(row).toContainText('выключен');
  await row.getByRole('button', {name: 'Удалить', exact: true}).click();
  await row.getByRole('button', {name: 'Точно удалить'}).click();
  await expect(list.getByText('Доменов пока нет')).toBeVisible();
});

test('the portal page settings are saved', async ({page}) => {
  test.setTimeout(60_000);
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Портал подписки/}).click();
  const portal = page.locator('[data-sub-portal]');
  await expect(portal.locator('[data-portal-app]').first()).toBeVisible();
  await portal.getByLabel('Заголовок', {exact: true}).fill('Подписка Корги Люси');
  await portal.getByLabel('Шаблон', {exact: true}).selectOption('minimal');
  await portal.getByRole('button', {name: 'Сохранить портал'}).click();
  await page.reload();
  await page.locator('.sidebar').getByRole('button', {name: /Портал подписки/}).click();
  await expect(page.locator('[data-sub-portal]').getByLabel('Заголовок', {exact: true})).toHaveValue('Подписка Корги Люси');
  await expect(page.locator('[data-sub-portal]').getByLabel('Шаблон', {exact: true})).toHaveValue('minimal');
  await expect(page.locator('[data-reset-link]')).toContainText('Сменить ссылку подписки клиента');
});
