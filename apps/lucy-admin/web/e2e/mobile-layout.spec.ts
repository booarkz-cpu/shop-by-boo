import {test, expect} from '@playwright/test';

test('administrator edits sections, buttons and banners of the Android and iOS apps', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/mobile-layout') && r.request().method() === 'GET'),
    page.getByRole('button', {name: 'Приложения: экраны и кнопки', exact: true}).click(),
  ]);
  const editor = page.locator('.mobile-layout-editor');
  await expect(editor.getByText('В нижней панели: 5 из 2–5 разделов')).toBeVisible();

  // The VPN section is open: rename the main button, hide one, switch the banner off.
  const connect = editor.locator('[data-button="vpn/connect"]');
  await connect.getByLabel('Текст кнопки (RU)', {exact: true}).fill('Включить защиту');
  await connect.getByLabel('Текст кнопки (EN)', {exact: true}).fill('Turn protection on');
  await editor.locator('[data-button="vpn/report"]').getByRole('checkbox', {name: 'Показывать'}).uncheck();
  await editor.locator('[data-section="vpn"]').getByRole('checkbox', {name: 'Показывать баннер'}).uncheck();
  // The phone preview follows at once.
  await expect(page.locator('.ml-phone')).toContainText('Включить защиту');

  // A new button that opens a link.
  await editor.locator('[data-section="vpn"]').getByRole('button', {name: 'Добавить кнопку', exact: true}).click();
  const added = editor.locator('[data-button="vpn/button1"]');
  await added.getByLabel('Текст кнопки (RU)', {exact: true}).fill('Наш сайт');
  await added.getByLabel('Действие', {exact: true}).selectOption('url');
  await added.getByLabel('Ссылка', {exact: true}).fill('https://example.com/');
  await editor.getByLabel('Telegram-канал (кнопки «Telegram-канал»)', {exact: true}).fill('https://t.me/corgi_news');

  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/mobile-layout') && r.request().method() === 'PUT' && r.ok()),
    editor.getByRole('button', {name: 'Сохранить', exact: true}).click(),
  ]);
  const ru = await page.evaluate(async () => (await (await fetch('/api/mobile/layout?lang=ru')).json()));
  const vpn = ru.sections.find((s: any) => s.id === 'vpn');
  expect(vpn.buttons[0]).toMatchObject({id: 'connect', label: 'Включить защиту', action: 'connect', style: 'primary'});
  expect(vpn.buttons.map((b: any) => b.id)).not.toContain('report');
  expect(vpn.buttons.at(-1)).toMatchObject({label: 'Наш сайт', action: 'url', target: 'https://example.com/'});
  expect(vpn.banner).toBeNull();
  expect(ru.links.telegram_channel).toBe('https://t.me/corgi_news');
  expect(ru.tabs).toEqual(['subscription', 'premium', 'vpn', 'locations', 'settings']);
  const en = await page.evaluate(async () => (await (await fetch('/api/mobile/layout?lang=en')).json()));
  expect(en.sections.find((s: any) => s.id === 'vpn').buttons[0].label).toBe('Turn protection on');

  // A link that is not https is refused with a readable error.
  await added.getByLabel('Ссылка', {exact: true}).fill('javascript:alert(1)');
  await editor.getByRole('button', {name: 'Сохранить', exact: true}).click();
  await expect(editor.getByRole('alert')).toContainText('https://');

  page.once('dialog', (d) => d.accept());
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/mobile-layout') && r.request().method() === 'DELETE' && r.ok()),
    editor.getByRole('button', {name: 'Вернуть стандартный макет', exact: true}).click(),
  ]);
  const reset = await page.evaluate(async () => (await (await fetch('/api/mobile/layout?lang=ru')).json()));
  expect(reset.sections.find((s: any) => s.id === 'vpn').buttons[0].label).toBe('Подключить');
});
