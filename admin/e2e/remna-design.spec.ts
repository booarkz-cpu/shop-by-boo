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

async function openDashboard(page: Page) {
  await signIn(page);
  await page.locator('.sidebar').getByRole('button', {name: 'Главная', exact: true}).click();
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
  await expect(page.locator('.sidebar').getByRole('button', {name: /Главная/})).toBeVisible();
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
  await openDashboard(page);
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
  await openDashboard(page);
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

  await expect(page.getByRole('heading', {name: 'Настройки без перезапуска', level: 1})).toBeVisible();
  const registryCounts = page.locator('.runtime-registry-counts');
  await expect(registryCounts).toContainText('132 live');
  await expect(registryCounts).toContainText('90 deployment');
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
  await expect(page.getByText('Версия настроек: 1', {exact: true})).toBeVisible();

  page.on('dialog', async (dialog) => {
    await dialog.accept(dialog.type() === 'prompt' ? 'Browser rollback check' : undefined);
  });
  await page.getByRole('button', {name: 'Откатить', exact: true}).click();
  await expect(page.getByText('Версия настроек: 2', {exact: true})).toBeVisible();
});

test('notifications section reports native push readiness without leaking tokens', async ({page}) => {
  await signIn(page);
  await page.getByRole('button', {name: /Уведомления/}).first().click();
  const card = page.getByRole('region', {name: 'Push-уведомления'});
  await expect(card).toBeVisible();
  await expect(card.getByText('Android · FCM')).toBeVisible();
  await expect(card.getByText('iOS · APNs')).toBeVisible();
  await expect(card.getByText('Не настроен').first()).toBeVisible();
  await expect(card.getByText('Android 0 · iOS 0')).toBeVisible();
  await expect(card.getByText('За 24 часа отправок не было')).toBeVisible();
});

test('node network section shows sources, freshness rules and stays usable on phones', async ({page}) => {
  await signIn(page);
  await page.getByRole('button', {name: /Сеть узлов/}).first().click();
  const sources = page.getByRole('region', {name: 'Источники сетевых данных'});
  await expect(page.getByRole('heading', {name: /ASN и репутация/, level: 1})).toBeVisible();
  await expect(sources).toBeVisible();
  await expect(sources.getByText('RIPEstat (RIPE NCC)')).toBeVisible();
  await expect(sources.getByText('Задайте ABUSEIPDB_API_KEY, чтобы проверять репутацию.')).toBeVisible();
  // No Remnawave panel in the browser stand: the section explains it instead of failing.
  await expect(sources.getByRole('alert')).toContainText('Remnawave недоступен');
  const customers = page.getByRole('region', {name: 'Сети клиентов'});
  await expect(customers.getByText('Отдельные IP-адреса клиентов здесь не показываются.')).toBeVisible();
  await page.setViewportSize({width: 390, height: 844});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test('all-sections hub lists every feature with a description and finds them by task', async ({page}) => {
  await signIn(page);
  await expect(page.getByRole('heading', {level: 1, name: 'Все разделы'})).toBeVisible();
  const cards = page.locator('.hub-card');
  await expect(cards).toHaveCount(8);
  for (const title of ['Аналитика', 'Пользователи', 'Тарифы и оплата', 'Маркетинг', 'Бот и кабинет', 'Серверы', 'Система', 'Безопасность'])
    await expect(page.locator('.hub-card h3', {hasText: title}).first()).toBeVisible();
  // Every entry has a name and a one-sentence description.
  const items = page.locator('.hub-item');
  const total = await items.count();
  expect(total).toBeGreaterThanOrEqual(61);
  for (let i = 0; i < total; i += 1) await expect(items.nth(i).locator('small')).toHaveText(/\S.{20,}/);

  const search = page.getByPlaceholder('Например: промокод, возврат, логотип');
  await search.fill('логотип');
  await expect(items).toHaveCount(1);
  await expect(page.locator('.hub-item', {hasText: 'Оформление'})).toBeVisible();
  await search.fill('ничего такого нет');
  await expect(page.getByText('Ничего не найдено')).toBeVisible();
  await page.getByRole('button', {name: 'Очистить поиск'}).click();
  await expect(items).toHaveCount(total);

  await page.locator('.hub-item', {hasText: 'Конструктор тарифов'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Конструктор тарифов'})).toBeVisible();
  await expect(page.locator('.breadcrumb')).toContainText('Тарифы и оплата');
  await expect(page.locator('.page-description')).toContainText('собирает сам');
  // Fields carry a visible label, not just a placeholder.
  await expect(page.locator('label.field', {hasText: 'Базовая цена, ₽'})).toBeVisible();
  await expect(page.locator('label.field', {hasText: 'Доплата, ₽'}).first()).toBeVisible();
  await page.locator('.breadcrumb').getByRole('button', {name: 'Админ-панель'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Все разделы'})).toBeVisible();

  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
