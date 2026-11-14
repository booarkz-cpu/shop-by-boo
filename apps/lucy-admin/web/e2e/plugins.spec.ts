import {expect, test, type Page} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';

const python = process.env.PASSKEY_TEST_PYTHON || 'python';
const tool = path.resolve(__dirname, '../../scripts/sign-plugin.py');

function signedPackage() {
  const dir = mkdtempSync(path.join(tmpdir(), 'corgi-plugin-'));
  const key = path.join(dir, 'publisher.key');
  const publicKey = execFileSync(python, [tool, 'keygen', key]).toString().trim();
  const source = path.join(dir, 'src');
  execFileSync('mkdir', ['-p', source]);
  writeFileSync(path.join(source, 'manifest.json'), JSON.stringify({
    id: 'e2e.crm', name: 'E2E CRM', version: '1.0.0', api_version: 1, publisher: 'E2E Ltd',
    description: 'Отправляет новых клиентов во внешнюю CRM.', endpoint: 'https://93.184.216.34/corgi/events',
    capabilities: ['users.read'], events: ['user.registered'],
    settings: [{key: 'crm_key', type: 'secret', label: 'Ключ CRM', required: true}],
  }));
  const zip = path.join(dir, 'e2e-crm-1.0.0.zip');
  execFileSync(python, [tool, 'sign', key, source, zip]);
  return {publicKey, zip};
}

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

test('signed plugin is trusted, approved, configured, enabled and disabled', async ({page}) => {
  const {publicKey, zip} = signedPackage();
  await signIn(page);
  await page.getByRole('button', {name: /Плагины/}).first().click();
  await expect(page.getByText('Плагины ещё не загружены.')).toBeVisible();

  const publishers = page.getByRole('region', {name: 'Доверенные издатели'});
  await publishers.getByRole('textbox', {name: 'Название издателя'}).fill('E2E Ltd');
  await publishers.getByRole('textbox', {name: 'Открытый ключ Ed25519 (base64)'}).fill(publicKey);
  await publishers.getByRole('button', {name: 'Добавить ключ'}).click();
  await expect(publishers.getByText('Активен')).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(zip);
  await page.getByRole('button', {name: 'Проверить и загрузить'}).click();
  const card = page.getByRole('article', {name: 'Плагин E2E CRM'});
  await expect(card).toBeVisible();
  await expect(card.getByText('Загружен, не включён')).toBeVisible();
  await expect(card.getByText(/users\.read/)).toBeVisible();

  // Required settings first, then explicit approval of the requested rights.
  await card.locator('input[type="password"]').fill('crm-secret-value');
  await card.getByRole('button', {name: 'Сохранить настройки'}).click();
  await expect(card.locator('input[type="password"]')).toHaveAttribute('placeholder', /Задан/);
  const enable = card.getByRole('button', {name: 'Включить версию 1.0.0'});
  await expect(enable).toBeDisabled();
  await card.getByRole('checkbox', {name: 'Разрешаю плагину эти права и события'}).check();
  await enable.click();

  const credentials = page.getByRole('status', {name: 'Учётные данные плагина'});
  await expect(credentials).toBeVisible();
  await expect(credentials.locator('code').first()).toHaveText(/^cpl_/);
  await credentials.getByRole('button', {name: 'Я сохранил данные'}).click();
  await expect(credentials).toBeHidden();
  await expect(card.getByText('Включён', {exact: true})).toBeVisible();  // exact: «не включён» matches too until the card reloads
  await expect(page.locator('body')).not.toContainText('crm-secret-value');

  await card.getByRole('button', {name: 'Выключить'}).click();
  await expect(card.getByText('Выключен', {exact: true})).toBeVisible();

  await page.setViewportSize({width: 390, height: 844});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
