import {expect, test} from '@playwright/test';

// v28.60.0 (stage 6): the 30 modules, the roles × permissions table and the audit log search.
async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

test('admin center lists the 30 modules and opens a section from the table', async ({page}) => {
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Админ-центр/}).click();
  const center = page.locator('[data-control-center]');
  await expect(center.locator('tbody tr')).toHaveCount(30);
  // v28.69.0: every module of the master task has its section.
  await expect(center.locator('tr[data-status="NOT_STARTED"]')).toHaveCount(0);
  await expect(center.locator('tr[data-module="Node Extensions"]')).toContainText('Расширения Remnawave');
  await expect(center.locator('tr[data-module="Domains"]')).toContainText('Домены и сертификаты');
  await center.locator('tr[data-module="Tariffs"]').getByRole('button', {name: 'Тарифы', exact: true}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Тарифы'})).toBeVisible();
});

test('roles table and audit log search are in «Безопасность»', async ({page}) => {
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: /Роли и администраторы/}).click();
  const roles = page.locator('[data-roles-matrix]');
  await expect(roles.getByRole('columnheader', {name: 'operator'})).toBeVisible();
  await expect(roles.getByText('Администраторы и роли')).toBeVisible();

  await page.locator('.sidebar').getByRole('button', {name: /Журнал действий/}).click();
  const log = page.locator('[data-audit-log]');
  await expect(log.getByRole('textbox', {name: 'Администратор'})).toBeVisible();
  await log.getByRole('textbox', {name: 'Действие начинается с'}).fill('такого-действия-нет.');
  await log.getByRole('button', {name: 'Найти'}).click();
  await expect(log.getByText('Ничего не найдено.')).toBeVisible();
});
