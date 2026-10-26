import {test, expect} from '@playwright/test';

// A valid PNG generated in the test (same helper as bot-banners.spec.ts).
import {deflateSync} from 'zlib';

function png(width: number, height: number): Buffer {
  const crc = (buf: Buffer) => { let c = ~0; for (const b of buf) { c ^= b; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1)); } return ~c >>> 0; };
  const chunk = (type: string, data: Buffer) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([len, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2;
  const raw = Buffer.alloc((width * 3 + 1) * height, 0x80); for (let y = 0; y < height; y++) raw[y * (width * 3 + 1)] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

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
    banner.getByLabel('Загрузить своё изображение', {exact: true}).setInputFiles({name: 'privacy.png', mimeType: 'image/png', buffer: png(640, 320)}),
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
