import {test, expect} from '@playwright/test';
import {deflateSync} from 'zlib';

function png(width: number, height: number): Buffer {
  const crc = (buf: Buffer) => { let c = ~0; for (const b of buf) { c ^= b; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1)); } return ~c >>> 0; };
  const chunk = (type: string, data: Buffer) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([len, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2;
  const raw = Buffer.alloc((width * 3 + 1) * height, 0x80); for (let y = 0; y < height; y++) raw[y * (width * 3 + 1)] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

test('administrator replaces, hides and resets bot section banners', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/bot/banners')),
    page.getByRole('button', {name: 'Баннеры бота', exact: true}).click(),
  ]);
  const buy = page.locator('[data-banner="buy"]');
  await expect(buy).toContainText('Тарифы');
  await expect(buy).toContainText('/buy · стандартный');
  const preview = buy.getByRole('img', {name: 'Баннер: Тарифы'});
  await expect(preview).toHaveAttribute('src', /\/api\/bot\/banners\/default\/buy\.jpg$/);
  await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1280);
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.waitForFunction(() => [...document.querySelectorAll('.banner-preview img')].every((i: any) => i.complete));
    await page.screenshot({path: `${process.env.E2E_SCREENSHOT_DIR}/bot-banners.png`, fullPage: true});
  }

  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/bot/banners/buy') && r.request().method() === 'POST' && r.ok()),
    buy.getByLabel('Своё изображение', {exact: true}).setInputFiles({name: 'tariffs.png', mimeType: 'image/png', buffer: png(640, 320)}),
  ]);
  await expect(buy).toContainText('/buy · свой');
  await expect(buy.getByRole('img', {name: 'Баннер: Тарифы'})).toHaveAttribute('src', /\/media\/bot-banner-buy-[0-9a-f]+\.jpg$/);

  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/bot/banners/buy/visibility') && r.ok()),
    buy.getByRole('checkbox', {name: 'Показывать', exact: true}).click(),
  ]);
  await expect(buy).toContainText('/buy · скрыт');

  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/bot/banners/buy') && r.request().method() === 'DELETE' && r.ok()),
    buy.getByRole('button', {name: 'Вернуть стандартный', exact: true}).click(),
  ]);
  await expect(buy).toContainText('/buy · стандартный');
  await expect(buy.getByRole('checkbox', {name: 'Показывать', exact: true})).toBeChecked();
  await expect(page.locator('[data-banner="start"]')).toContainText('Приветствие');
});
