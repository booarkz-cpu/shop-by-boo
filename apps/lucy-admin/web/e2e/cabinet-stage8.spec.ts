import {expect, test, type Page} from '@playwright/test';

// v28.63.0 (stage 8): Google sign-in, sessions one by one, devices under the limit, Lucy tariffs and the Lucy Mini trial.
async function customer(page: Page) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/cabinet/');
  await expect(page.getByRole('button', {name: 'Продолжить с Google'})).toBeVisible();
  await page.getByLabel('Электронная почта').fill('customer@example.test');
  await page.getByLabel('Пароль').fill('customer-browser-password');
  await page.locator('form').getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.getByRole('region', {name: 'Статус подписки'})).toBeVisible();
}

async function admin(page: Page) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

test('the customer ends a session and sees the devices section', async ({page}) => {
  await customer(page);
  const nav = page.getByRole('navigation', {name: 'Разделы кабинета'});
  await nav.getByRole('button', {name: /Безопасность/}).click();
  const sessions = page.locator('[data-sessions="ready"]');
  await expect(sessions.getByText('Эта сессия')).toBeVisible();
  await expect(sessions.getByRole('button', {name: 'Завершить'}).first()).toBeVisible();
  await nav.getByRole('button', {name: /Устройства/}).click();
  await expect(page.locator('[data-hwid-devices="none"]')).toContainText('после покупки подписки');
  page.once('dialog', d => d.accept());
  await page.goto('/cabinet/');
  await nav.getByRole('button', {name: /Безопасность/}).click();
  await sessions.locator('[data-session]').filter({hasText: 'Эта сессия'}).getByRole('button', {name: 'Завершить'}).click();
  await expect(page.getByLabel('Электронная почта')).toBeVisible();
});

test('the owner creates the Lucy tariffs and the trial is offered on Lucy Mini only', async ({page, browser}) => {
  await admin(page);
  await page.locator('.sidebar').getByRole('button', {name: /^Тарифы$/}).click();
  const lucy = page.locator('[data-lucy-plans]');
  await lucy.getByRole('textbox', {name: 'Цена Lucy Max'}).fill('300');
  await lucy.getByRole('textbox', {name: 'Цена Lucy Ultra'}).fill('700');
  await lucy.getByRole('button', {name: /тарифы Lucy/}).click();
  await expect(lucy.getByRole('alert')).toContainText('выгоднее');
  await lucy.getByRole('textbox', {name: 'Цена Lucy Ultra'}).fill('500');
  await lucy.getByRole('button', {name: /тарифы Lucy/}).click();
  await expect(lucy.locator('[data-state="success"]')).toContainText('Lucy Ultra');
  await expect(lucy.locator('tr[data-plan="Lucy Mini"]')).toContainText('пробный тариф');
  await expect(lucy.locator('tr[data-plan="Lucy Ultra"]')).toContainText('4');

  const cabinet = await browser.newPage();
  await customer(cabinet);
  await cabinet.getByRole('navigation', {name: 'Разделы кабинета'}).getByRole('button', {name: /Пробный период/}).click();
  const trial = cabinet.locator('[data-trial-plan]');
  await expect(trial).toContainText('Lucy Mini');
  await expect(trial).toContainText('1 устр.');
  await expect(trial.locator('article')).toHaveCount(1);
  await cabinet.close();

  page.once('dialog', d => d.accept());
  await lucy.getByRole('button', {name: 'Пробный период на любом тарифе'}).click();
  await expect(lucy.getByRole('button', {name: 'Пробный период на любом тарифе'})).toHaveCount(0);
});
