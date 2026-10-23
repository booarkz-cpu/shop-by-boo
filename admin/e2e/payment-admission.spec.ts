import {test, expect} from '@playwright/test';
import {generateKeyPairSync, sign} from 'node:crypto';

const b64url = (b: Buffer) => b.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const CHECKS = ['checkout', 'idempotent_checkout', 'signed_webhook', 'provider_match', 'fulfilled', 'duplicate_ignored',
  'tamper_rejected', 'refund_confirmed', 'refund_idempotent', 'access_revoked', 'late_success_ignored'];

test('administrator admits real payments with a signed staging E2E v2 result', async ({page}) => {
  const {publicKey, privateKey} = generateKeyPairSync('ed25519');
  const raw = b64url(Buffer.from((publicKey.export({format: 'jwk'}) as any).x, 'base64url'));
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/e2e-v2/overview')),
    page.getByRole('button', {name: 'Проверка платежей', exact: true}).click(),
  ]);
  await expect(page.getByText('Реальные платежи:')).toContainText('закрыты');
  await page.getByLabel('Открытый ключ стенда', {exact: true}).fill(raw);
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/e2e-v2/admission/config') && r.request().method() === 'PUT'),
    page.getByRole('button', {name: 'Сохранить', exact: true}).first().click(),
  ]);
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/e2e-v2/admission/nonce')),
    page.getByRole('button', {name: 'Получить код запуска', exact: true}).click(),
  ]);
  const nonce = await page.getByLabel('Код для этого запуска', {exact: true}).inputValue();
  expect(nonce).toMatch(/^e2e2n\./);
  const overview = await page.evaluate(async () => (await fetch('/api/admin/e2e-v2/overview')).json());
  const body = Buffer.from(JSON.stringify({
    contract_version: 2, environment: 'staging', distribution_tag: overview.distribution_tag, nonce, run_id: 'browser-run',
    status: 'passed', full_e2e: true, finished_at: new Date().toISOString(),
    provider_results: [{provider: 'yookassa', status: 'passed', checks: CHECKS}],
  }));
  const attestation = `e2e2.${b64url(body)}.${b64url(sign(null, body, privateKey))}`;
  await page.getByLabel('Подписанный результат', {exact: true}).fill(attestation);
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/e2e-v2/admission/attestation')),
    page.getByRole('button', {name: 'Принять результат', exact: true}).click(),
  ]);
  await expect(page.getByText('Проверка: пройдена')).toBeVisible();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/payments/production-gate')),
    page.getByRole('button', {name: 'Открыть реальные платежи', exact: true}).click(),
  ]);
  await expect(page.getByText('Реальные платежи:')).toContainText('открыты');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/payments/production-gate')),
    page.getByRole('button', {name: 'Закрыть', exact: true}).click(),
  ]);
  await expect(page.getByText('Реальные платежи:')).toContainText('закрыты');
});
