import {expect, test, type Page} from '@playwright/test';

// v28.86.0: the cabinet's «Приложения» block is not on the sign-in or registration pages, it is shown to a signed-in
// customer, and the owner switches it off and on in «Android и iOS».
async function signIn(page: Page) {
  await page.getByLabel('Электронная почта').fill('customer@example.test');
  await page.getByLabel('Пароль').fill('customer-browser-password');
  await page.locator('form').getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.getByRole('region', {name: 'Статус подписки'})).toBeVisible();
}

async function owner(page: Page, show: boolean) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
  await page.locator('.sidebar').getByRole('button', {name: /Android и iOS/}).click();
  const box = page.locator('[data-cabinet-apps]').getByRole('checkbox');
  await expect(box).toBeVisible();
  if ((await box.isChecked()) !== show) await box.click();
  await page.getByRole('button', {name: 'Сохранить приложения'}).click();
  await expect(page.getByText('Приложения сохранены')).toBeVisible();
}

test('no apps block before sign-in; shown inside; the owner switches it off and on', async ({page, browser}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/cabinet/');
  await expect(page.getByLabel('Электронная почта')).toBeVisible();
  await expect(page.locator('section.apps-note')).toHaveCount(0);
  await page.getByRole('tab', {name: 'Регистрация'}).or(page.getByRole('button', {name: 'Регистрация'})).first().click();
  await expect(page.locator('section.apps-note')).toHaveCount(0);
  await page.getByRole('tab', {name: 'Вход'}).or(page.getByRole('button', {name: 'Вход', exact: true})).first().click();
  await signIn(page);
  await expect(page.locator('section.apps-note')).toBeVisible();

  const admin = await browser.newPage();
  await owner(admin, false);
  await page.reload();
  await expect(page.getByRole('region', {name: 'Статус подписки'})).toBeVisible();
  await expect(page.locator('section.apps-note')).toHaveCount(0);
  await owner(admin, true);
  await page.reload();
  await expect(page.locator('section.apps-note')).toBeVisible();
  await admin.close();
});
