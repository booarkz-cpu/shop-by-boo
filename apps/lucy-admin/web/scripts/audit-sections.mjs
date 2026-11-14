// Visits every admin section, saves a screenshot and reports controls without a visible label.
// Usage: node scripts/audit-sections.mjs <out-dir> [width]
import {chromium} from '@playwright/test';
import fs from 'node:fs';

const out = process.argv[2] || 'audit';
const width = Number(process.argv[3] || 1440);
fs.mkdirSync(out, {recursive: true});
const browser = await chromium.launch({executablePath: process.env.E2E_CHROMIUM_PATH || undefined});
const page = await browser.newPage({viewport: {width, height: 900}});
await page.addInitScript(() => {
  localStorage.setItem('rw_lang', 'ru');
  localStorage.setItem('rw_theme', 'dark');
});
await page.goto('http://localhost:8777/');
await page.getByRole('textbox', {name: 'Email', exact: true}).fill('browser@example.test');
await page.locator('input[type=password]').first().fill('browser-only-password');
await page.getByRole('button', {name: 'Войти', exact: true}).click();
await page.waitForSelector('.sidebar');
const tabs = await page.evaluate(() =>
  [...document.querySelectorAll('.sidebar .nav-item[data-tab], .sidebar .nav-item')]
    .map((el) => ({tab: el.getAttribute('data-tab'), text: el.textContent.trim()}))
    .filter((x) => x.text && !/Свернуть|Развернуть|Выйти/.test(x.text)),
);
const report = [];
for (const [index, item] of tabs.entries()) {
  await page.locator('.sidebar .nav-item', {hasText: item.text}).first().click();
  await page.waitForTimeout(700);
  await page.waitForSelector('.loading-bar', {state: 'detached', timeout: 8000}).catch(() => {});
  const problems = await page.evaluate(() => {
    const result = [];
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    for (const el of document.querySelectorAll('.content-wrap input:not([type=hidden]), .content-wrap select, .content-wrap textarea')) {
      if (!visible(el) && el.tagName !== 'SELECT') continue;
      const label = el.closest('label');
      const own = label ? [...label.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim() : '';
      const labelled = el.id && document.querySelector(`label[for="${el.id}"]`);
      const visibleText = own || (label && label.querySelector('span,b,strong,.label')?.textContent?.trim()) || (labelled && labelled.textContent.trim());
      if (!visibleText) result.push(`${el.tagName.toLowerCase()}[${el.type || ''}] placeholder="${el.placeholder || ''}" aria="${el.getAttribute('aria-label') || ''}"`);
    }
    const english = [...document.querySelectorAll('.content-wrap h2, .content-wrap h3, .content-wrap .eyebrow, .content-wrap button, .content-wrap th')]
      .map((el) => el.textContent.trim())
      .filter((t) => /^[A-Za-z][A-Za-z0-9 ·&/:\-+.]{3,}$/.test(t));
    return {unlabeled: result, english: [...new Set(english)], h1: document.querySelector('h1')?.textContent};
  });
  const name = String(index).padStart(2, '0') + '-' + item.text.replace(/[^\p{L}\p{N}]+/gu, '_').slice(0, 40);
  await page.screenshot({path: `${out}/${name}.png`, fullPage: true});
  report.push({name, ...problems});
}
fs.writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 1));
console.log(report.map((r) => `${r.name}: unlabeled=${r.unlabeled.length} english=${r.english.length}`).join('\n'));
await browser.close();
