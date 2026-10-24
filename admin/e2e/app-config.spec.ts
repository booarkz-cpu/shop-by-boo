import {test, expect} from '@playwright/test';

test('administrator configures the Mini App and the public config follows', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/app-config') && r.request().method() === 'GET'),
    page.getByRole('button', {name: 'Конфигурация Mini App', exact: true}).click(),
  ]);
  await page.getByLabel('Акцент (неоновый)', {exact: true}).fill('#00ff99');
  await page.getByLabel('Кнопки сумм (через запятую)', {exact: true}).fill('150, 300, 900');
  await page.getByRole('button', {name: 'Добавить: Кнопка поддержки', exact: true}).click();
  await page.getByLabel('Кнопка поддержки: Ссылка 1', {exact: true}).fill('https://t.me/corgi_support');
  await page.getByRole('button', {name: 'Добавить: Категория серверов', exact: true}).click();
  await page.getByLabel('Категория серверов: Страны 1', {exact: true}).fill('de, NL');
  await page.getByRole('checkbox', {name: 'Спрашивать согласие с офертой'}).click();
  await page.getByLabel('Версия оферты', {exact: true}).fill('2026-10');
  await page.getByLabel('Текст «greeting»', {exact: true}).fill('Хей, {name}!');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/app-config') && r.request().method() === 'PUT' && r.ok()),
    page.getByRole('button', {name: 'Сохранить', exact: true}).click(),
  ]);
  const cfg = await page.evaluate(async () => (await (await fetch('/api/app-config')).json()));
  expect(cfg.theme.vars['--cfg-accent']).toBe('#00ff99');
  expect(cfg.wallet.amounts).toEqual([150, 300, 900]);
  expect(cfg.support.buttons[0]).toMatchObject({title: 'Написать в Telegram', link: 'https://t.me/corgi_support'});
  expect(cfg.servers.categories[0].countries).toEqual(['DE', 'NL']);
  expect(cfg.consent).toMatchObject({enabled: true, version: '2026-10'});
  expect(cfg.texts.greeting).toBe('Хей, {name}!');
  expect(cfg.banners.overview).toMatch(/\/api\/bot\/banners\/default\/home\.jpg$/);

  // A bad link is rejected with a readable error and nothing changes.
  await page.getByLabel('Кнопка поддержки: Ссылка 1', {exact: true}).fill('javascript:alert(1)');
  await page.getByRole('button', {name: 'Сохранить', exact: true}).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/app-config') && r.request().method() === 'DELETE' && r.ok()),
    page.getByRole('button', {name: 'Сбросить к значениям по умолчанию', exact: true}).click(),
  ]);
  const reset = await page.evaluate(async () => (await (await fetch('/api/app-config')).json()));
  expect(reset.theme.vars['--cfg-accent']).toBe('#39ff88');
  expect(reset.consent.enabled).toBe(false);
});
