import {expect, test} from '@playwright/test';
import {execFileSync} from 'node:child_process';

const SNAPSHOT = `
import sqlite3, sys
db = sqlite3.connect(':memory:')
db.execute('CREATE TABLE users(id INTEGER, telegram_id INTEGER, username TEXT, balance TEXT)')
db.execute("INSERT INTO users VALUES (501, 9005001, 'History A', '0'), (502, 9005002, 'History B', '0')")
db.execute('CREATE TABLE payments(id TEXT, user_id INTEGER, amount TEXT, status TEXT, paid_at TEXT)')
db.execute("INSERT INTO payments VALUES ('h-1', 501, '199.00', 'succeeded', '2025-02-01T10:00:00Z'), ('h-2', 502, '299.00', 'succeeded', '2025-02-02T10:00:00Z'), ('h-3', 502, '50.00', 'canceled', '2025-02-03T10:00:00Z')")
db.execute('CREATE TABLE subscriptions(user_id INTEGER, expires_at TEXT, uuid TEXT, tariff TEXT)')
db.execute("INSERT INTO subscriptions VALUES (501, '2031-01-01T00:00:00', 'aaaaaaaa-1111-4222-8333-000000000501', 'Browser history plan')")
db.commit()
sys.stdout.buffer.write(db.serialize())
`;

test('administrator reconciles, applies and rolls back a historical import', async ({page}) => {
  const source = execFileSync(process.env.PASSKEY_TEST_PYTHON || 'python', ['-c', SNAPSHOT]);
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.dash-metric').first()).toBeVisible();

  // Profiles of the same source and a target plan are prerequisites of the history import.
  await page.evaluate(async (bytes) => {
    const csrf = decodeURIComponent(document.cookie.split('; ').find((x) => x.startsWith('rw_csrf='))?.split('=')[1] || '');
    const headers = {'X-CSRF-Token': csrf};
    const plan = await fetch('/api/admin/plans', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'},
      body: JSON.stringify({name: 'Browser history plan', price: 199, duration_days: 30, traffic_limit_gb: 0, device_limit: 3})});
    if (!plan.ok) throw new Error('plan');
    const form = () => { const data = new FormData(); data.append('file', new Blob([new Uint8Array(bytes)]), 'old.db'); return data; };
    const mapping = {namespace: 'history-browser', table: 'users', source_id: 'id', telegram_id: 'telegram_id', username: 'username', balance: null, currency: 'RUB', credit_balances: false};
    const preview = form(); preview.append('mapping', JSON.stringify(mapping));
    const staged = await (await fetch('/api/admin/customer-operations/import/preview', {method: 'POST', headers, body: preview})).json();
    const applied = await fetch(`/api/admin/customer-operations/import/${staged.id}/apply`, {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify({fingerprint: staged.fingerprint})});
    if (!applied.ok) throw new Error('profiles');
  }, [...source]);

  await page.getByRole('button', {name: /Импорт и массовые операции/}).click();
  await expect(page.getByRole('heading', {name: 'Перенос подписок и платежей'})).toBeVisible();
  await page.getByLabel('Выгрузка SQLite с подписками и платежами', {exact: true}).setInputFiles({name: 'old.db', mimeType: 'application/octet-stream', buffer: source});
  await page.getByLabel('Имя источника профилей', {exact: true}).fill('history-browser');
  await page.getByRole('button', {name: 'Загрузить колонки платежей'}).click();
  await expect(page.getByRole('combobox', {name: 'ID платежа', exact: true})).toContainText('id');
  await page.getByRole('button', {name: 'Загрузить колонки подписок'}).click();
  await expect(page.getByRole('combobox', {name: 'UUID пользователя Remnawave', exact: true})).toContainText('uuid');

  // A wrong control total is shown as a mismatch and keeps apply disabled.
  await page.getByLabel('Количество успешных и возвращённых платежей', {exact: true}).fill('2');
  await page.getByRole('textbox', {name: /Сумма успешных платежей/}).fill('400.00');
  await page.getByLabel('Количество подписок', {exact: true}).fill('1');
  await page.getByRole('button', {name: 'Сверить историю'}).click();
  await expect(page.getByText('Расхождение')).toBeVisible();
  await page.getByRole('checkbox', {name: 'Я сверил итоги и строки с исходной системой'}).check();
  await expect(page.getByRole('button', {name: 'Применить историю'})).toBeDisabled();

  await page.getByRole('textbox', {name: /Сумма успешных платежей/}).fill('498.00');
  await page.getByRole('button', {name: 'Сверить историю'}).click();
  await expect(page.getByText('Совпадает')).toHaveCount(3);
  await expect(page.getByText(/Пропущено платежей с другими статусами: 1/)).toBeVisible();
  await page.getByRole('checkbox', {name: 'Я сверил итоги и строки с исходной системой'}).check();
  await page.getByRole('button', {name: 'Применить историю'}).click();
  await expect(page.getByText(/Перенос применён: платежей 2, подписок 1/)).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept('Browser rollback check'));
  await page.getByRole('row', {name: /history-browser/}).filter({hasText: 'Применён'}).getByRole('button', {name: 'Откатить'}).click();
  await expect(page.getByText(/Перенос откатан: удалено платежей 2, подписок 1/)).toBeVisible();
});
