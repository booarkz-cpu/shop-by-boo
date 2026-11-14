import {test, expect} from '@playwright/test';

test('administrator creates, edits and hides a fixed plan with its Remnawave squad', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/plans')),
    page.getByRole('button', {name: 'Тарифы', exact: true}).click(),
  ]);
  const squad = '11111111-2222-3333-4444-555555555555';
  await page.getByLabel('Название тарифа', {exact: true}).fill('Три месяца e2e');
  await page.getByLabel('Цена, ₽', {exact: true}).fill('499');
  await page.getByLabel('Срок', {exact: true}).selectOption('90');
  await page.getByLabel('Трафик, ГБ (0 — без ограничения)', {exact: true}).fill('200');
  await page.getByLabel('Устройств (пусто — без ограничения)', {exact: true}).fill('5');
  // The test server has no Remnawave: the editor falls back to a typed squad UUID.
  await page.getByLabel('Профиль Remnawave (Internal Squad)', {exact: true}).fill(squad);
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/plans') && r.request().method() === 'POST'),
    page.getByRole('button', {name: 'Создать тариф', exact: true}).click(),
  ]);
  const card = page.locator('.plan.card').filter({hasText: 'Три месяца e2e'});
  await expect(card).toContainText('3 месяца · 200 ГБ · устройств: 5');
  await expect(card).toContainText(`Профиль Remnawave: ${squad}`);

  const stored = await page.evaluate(async () => (await (await fetch('/api/admin/plans')).json()).find((p: any) => p.name === 'Три месяца e2e'));
  expect(stored).toMatchObject({price: 499, duration_days: 90, traffic_limit_gb: 200, device_limit: 5, remnawave_profile_id: squad, enabled: true});

  const byId = page.locator(`[data-plan-id="${stored.id}"]`);
  await byId.getByRole('button', {name: 'Изменить'}).click();
  await byId.getByLabel('Цена, ₽', {exact: true}).fill('549');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith(`/api/admin/plans/${stored.id}`) && r.request().method() === 'PUT'),
    byId.getByRole('button', {name: 'Сохранить', exact: true}).click(),
  ]);
  await expect(byId.locator('.price')).toContainText('549');

  await byId.getByRole('button', {name: 'Снять с продажи'}).click();
  await expect(byId).toContainText('Скрыт');
  const publicPlans = await page.evaluate(async () => (await (await fetch('/api/plans')).json()).map((p: any) => p.name));
  expect(publicPlans).not.toContain('Три месяца e2e');
});
