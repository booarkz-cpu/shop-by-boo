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

test('login and admin shell use the Remna dark design system', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('rw_theme', 'dark');
    localStorage.setItem('rw_lang', 'ru');
  });
  await page.goto('/');

  await expect(page.getByRole('heading', {name: 'Вход в панель'})).toBeVisible();
  await expect(page.getByText('Система работает.')).toBeVisible();
  await expect(page.getByText('Всё под контролем.')).toBeVisible();

  const submit = page.getByRole('button', {name: 'Войти', exact: true});
  await expect(submit).toHaveCSS('background-color', 'rgb(59, 130, 246)');

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
  await expect(page.locator('.sidebar .nav-item.active')).toHaveCSS('box-shadow', /rgb\(59, 130, 246\)/);
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
  await expect(page.locator('body')).toHaveClass(/drawer-locked/);
  await page.keyboard.press('Escape');
  await expect(page.locator('.sidebar')).not.toHaveClass(/open/);
  await expect(page.getByRole('button', {name: 'Открыть меню'})).toBeFocused();
  await page.getByRole('button', {name: 'Открыть меню'}).click();
  await page.locator('.sidebar-backdrop').click({position: {x: 370, y: 400}});
  await expect(page.locator('.sidebar')).not.toHaveClass(/open/);
  await page.getByRole('button', {name: 'Открыть меню'}).click();
  await page.getByRole('button', {name: /Платежи/}).first().click();
  await expect(page.locator('.sidebar')).not.toHaveClass(/open/);
  await expect(page.getByRole('heading', {level: 1, name: 'Платежи'})).toBeVisible();
});

test('dashboard tiles use a 2x2 grid on phones and 4x1 on desktop', async ({page}) => {
  await signIn(page);
  const tiles = page.locator('.dash-metric');
  await expect(tiles).toHaveCount(4);
  const desktopRows = new Set<number>();
  for (let i = 0; i < 4; i += 1) desktopRows.add(Math.round((await tiles.nth(i).boundingBox())!.y));
  expect(desktopRows.size).toBe(1);
  await expect(page.locator('.dash-banner')).toBeVisible();
  await expect(page.locator('.dash-strip')).toBeVisible();

  await page.setViewportSize({width: 390, height: 844});
  await expect.poll(async () => {
    const rows = new Set<number>();
    for (let i = 0; i < 4; i += 1) rows.add(Math.round((await tiles.nth(i).boundingBox())!.y));
    return rows.size;
  }).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('dashboard search, segmented filter and actions menu are keyboard operable', async ({page}) => {
  await signIn(page);
  const filter = page.getByRole('radiogroup', {name: 'Фильтр по статусу'});
  await expect(filter.getByRole('radio', {name: /Все/})).toHaveAttribute('aria-checked', 'true');
  await filter.getByRole('radio', {name: /Все/}).focus();
  await page.keyboard.press('ArrowRight');
  await expect(filter.getByRole('radio', {name: /Онлайн/})).toHaveAttribute('aria-checked', 'true');
  await expect(filter.getByRole('radio', {name: /Онлайн/})).toBeFocused();
  await page.getByRole('searchbox', {name: 'Поиск сервера'}).fill('nl');
  await expect(page.getByRole('button', {name: 'Очистить поиск'})).toBeVisible();
  await page.getByRole('button', {name: 'Действия'}).click();
  await expect(page.getByRole('menuitem', {name: 'Сверить платежи'})).toBeVisible();
  await page.getByRole('menuitem', {name: 'Журнал действий'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Журнал действий'})).toBeVisible();
});

test('desktop sidebar collapses to an icon rail and remembers the choice', async ({page}) => {
  await signIn(page);
  const sidebar = page.locator('.sidebar');
  await expect.poll(async () => Math.round((await sidebar.boundingBox())!.width)).toBe(272);
  await page.getByRole('button', {name: 'Свернуть меню'}).click();
  await expect.poll(async () => Math.round((await sidebar.boundingBox())!.width)).toBe(76);
  await expect(page.getByRole('button', {name: 'Развернуть меню'})).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await expect.poll(async () => Math.round((await page.locator('.sidebar').boundingBox())!.width)).toBe(76);
  await page.getByRole('button', {name: 'Развернуть меню'}).click();
  await expect.poll(async () => Math.round((await page.locator('.sidebar').boundingBox())!.width)).toBe(272);
});

test('runtime settings are hinted, staged, applied and rolled back', async ({page}) => {
  await signIn(page);
  await page.getByRole('button', {name: /Настройки без перезапуска/}).click();

  await expect(page.getByRole('heading', {name: 'Настройки без перезапуска', level: 2})).toBeVisible();
  const registryCounts = page.locator('.runtime-registry-counts');
  await expect(registryCounts).toContainText('96 live');
  await expect(registryCounts).toContainText('53 deployment');
  await expect(registryCounts).toContainText('2 workflow');
  await expect(page.getByText('RW доступ')).toBeVisible();

  const trialDays = page.getByRole('spinbutton', {name: 'Максимальный пробный период', exact: true});
  await expect(trialDays).toHaveAttribute('data-hint-ready', 'true');
  await trialDays.fill('7');
  await page.getByRole('textbox', {name: 'Причина изменения', exact: true}).fill('Browser acceptance check');
  await page.getByRole('button', {name: /Проверить и подготовить/}).click();

  await expect(page.getByText('Проверка пройдена', {exact: true})).toBeVisible();
  await expect(page.locator('.runtime-preview')).toContainText('Максимальный пробный период');
  await expect(page.locator('.runtime-preview')).toContainText('7');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', {name: 'Применить версию 1', exact: true}).click();
  await expect(page.getByText('LIVE CONFIG · VERSION 1', {exact: true})).toBeVisible();

  page.on('dialog', async (dialog) => {
    await dialog.accept(dialog.type() === 'prompt' ? 'Browser rollback check' : undefined);
  });
  await page.getByRole('button', {name: 'Откатить', exact: true}).click();
  await expect(page.getByText('LIVE CONFIG · VERSION 2', {exact: true})).toBeVisible();
});
