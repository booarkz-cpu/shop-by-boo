import {expect, test, type Page} from '@playwright/test';

async function signIn(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('rw_lang', 'ru');
    localStorage.setItem('rw_theme', 'dark');
  });
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
}

test('login and admin shell use the Obsidian design system', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('rw_theme', 'dark');
    localStorage.setItem('rw_lang', 'ru');
  });
  await page.goto('/');

  await expect(page.getByRole('heading', {name: 'Вход в панель'})).toBeVisible();
  await expect(page.getByText('Система работает.')).toBeVisible();
  await expect(page.getByText('Всё под контролем.')).toBeVisible();

  const submit = page.getByRole('button', {name: 'Войти', exact: true});
  await expect(submit).toHaveCSS('background-color', 'rgb(255, 138, 31)');

  const email = page.getByLabel('Email', {exact: true});
  await expect(email).toHaveAttribute('aria-description', /рабочий email администратора/i);
  const emailLabel = page.locator('label').filter({has: email});
  await expect(emailLabel.getByRole('button', {name: 'Подсказка: Email'})).toBeVisible();

  await signIn(page);
  await expect(page.locator('.sidebar')).toBeVisible();
  await expect(page.getByRole('button', {name: /Главная/})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Открыть меню'})).toBeHidden();
  await expect(page.locator('.sidebar .nav-item').first()).toHaveCSS('background-image', 'none');
  await expect(page.getByRole('button', {name: /Быстрый поиск/})).toBeVisible();
  await expect(page.locator('.sidebar .nav-item.active')).toHaveCSS('box-shadow', /rgb\(255, 138, 31\)/);
});

test('all editable controls receive keyboard-accessible contextual help', async ({page}) => {
  await signIn(page);
  await page.getByRole('button', {name: /Диагностика/}).click();

  const controls = page.locator('input:not([type="hidden"]), select:not([hidden]):not([aria-hidden="true"]), textarea, button[role="combobox"]');
  await expect.poll(async () => controls.count()).toBeGreaterThan(0);
  const count = await controls.count();
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    await expect(control).toHaveAttribute('data-hint-ready', 'true');
    await expect(control).toHaveAttribute('aria-description', /.+/);
    await expect(control).toHaveAttribute('title', /.+/);
  }
});

test('mobile layout keeps navigation accessible', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await signIn(page);

  await expect(page.getByRole('button', {name: 'Открыть меню'})).toBeVisible();
  await expect.poll(async () => {const bounds=await page.locator('.sidebar').boundingBox();return bounds?Math.round(bounds.x+bounds.width):1;}).toBeLessThanOrEqual(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole('button', {name: 'Открыть меню'}).click();
  await expect(page.locator('.sidebar')).toHaveClass(/open/);
  await expect(page.getByRole('button', {name: 'Закрыть меню'})).toBeVisible();
});
