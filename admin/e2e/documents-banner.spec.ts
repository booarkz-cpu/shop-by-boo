import {test, expect} from '@playwright/test';

// A tiny valid PNG (8×4) as the uploaded banner.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAECAIAAAAmkwkpAAAAEklEQVR4nGP4z8DAwMDAgA4AAEoAAZ8xU8EAAAAASUVORK5CYII=', 'base64');

test('administrator sets the text and the banner of a document and both appear everywhere', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/info-pages') && r.request().method() === 'GET'),
    page.getByRole('button', {name: 'Документы', exact: true}).click(),
  ]);
  await page.getByRole('tab', {name: /Политика конфиденциальности/}).click();
  await page.getByLabel('Текст', {exact: true}).fill('## Данные\n- Храним только **email**');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/info-pages/privacy') && r.request().method() === 'PUT' && r.ok()),
    page.getByRole('button', {name: 'Сохранить', exact: true}).click(),
  ]);
  const banner = page.locator('[data-doc-banner="privacy"]');
  await expect(banner.getByRole('img', {name: 'Баннер: Политика конфиденциальности'})).toHaveAttribute('src', /\/api\/bot\/banners\/default\/privacy\.jpg$/);
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/bot/banners/privacy') && r.request().method() === 'POST' && r.ok()),
    banner.getByLabel('Загрузить своё изображение', {exact: true}).setInputFiles({name: 'privacy.png', mimeType: 'image/png', buffer: PNG}),
  ]);
  const doc = await page.evaluate(async () => (await (await fetch('/api/public/info-pages/privacy?lang=ru', {cache: 'no-store'})).json()));
  expect(doc.body).toContain('Храним только **email**');
  expect(doc.banner).toMatch(/\/media\/bot-banner-privacy-[0-9a-f]+\.jpg$/);
  // The Mini App and the cabinet read the same banner key.
  const cfg = await page.evaluate(async () => (await (await fetch('/api/app-config', {cache: 'no-store'})).json()));
  expect(cfg.banners.privacy).toBe(doc.banner);
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/bot/banners/privacy') && r.request().method() === 'DELETE' && r.ok()),
    banner.getByRole('button', {name: 'Вернуть стандартный', exact: true}).click(),
  ]);
  const reset = await page.evaluate(async () => (await (await fetch('/api/public/info-pages/privacy?lang=ru', {cache: 'no-store'})).json()));
  expect(reset.banner).toMatch(/\/api\/bot\/banners\/default\/privacy\.jpg$/);
});
