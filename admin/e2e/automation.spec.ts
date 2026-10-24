import {test, expect} from '@playwright/test';

test('administrator builds, checks and enables an automation rule and schedules a campaign', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/automation/catalog')),
    page.getByRole('button', {name: 'Автоматизация', exact: true}).click(),
  ]);
  await page.getByLabel('Название правила', {exact: true}).fill('Напоминание e2e');
  await page.getByLabel('Событие', {exact: true}).selectOption('subscription.expiring');
  await page.getByLabel('Дни (по умолчанию 3)', {exact: true}).fill('5');
  await page.getByLabel('Заголовок уведомления', {exact: true}).fill('Подписка скоро закончится');
  await page.getByLabel('Текст уведомления', {exact: true}).fill('Срок до {expires_at}');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/enterprise/rules') && r.request().method() === 'POST'),
    page.getByRole('button', {name: 'Создать правило', exact: true}).click(),
  ]);
  const rules = await page.evaluate(async () => (await (await fetch('/api/admin/enterprise/rules')).json()));
  const rule = rules.find((r: any) => r.name === 'Напоминание e2e');
  expect(rule).toMatchObject({event: 'subscription.expiring', enabled: false, conditions: {days: 5}, actions: {notify: {title: 'Подписка скоро закончится', telegram: true}}});
  const row = page.locator(`[data-rule-id="${rule.id}"]`);
  await expect(row).toContainText('Подписка скоро закончится · 5 дн.');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith(`/api/admin/automation/rules/${rule.id}/preview`)),
    row.getByRole('button', {name: 'Проверить', exact: true}).click(),
  ]);
  await expect(row).toContainText('ожидают: 0');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith(`/api/admin/v3/automation/${rule.id}/toggle`)),
    row.getByRole('checkbox', {name: 'Включено'}).click(),
  ]);
  await expect(row.getByRole('checkbox', {name: 'Включено'})).toBeChecked();

  await page.getByLabel('Название кампании', {exact: true}).fill('Осенняя акция e2e');
  await page.getByLabel('Кому', {exact: true}).selectOption('inactive');
  await page.getByLabel('Текст сообщения', {exact: true}).fill('Скидка 20% до конца недели');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/admin/enterprise/campaigns') && r.request().method() === 'POST'),
    page.getByRole('button', {name: 'Запланировать', exact: true}).click(),
  ]);
  const campaigns = await page.evaluate(async () => (await (await fetch('/api/admin/enterprise/campaigns')).json()));
  expect(campaigns.find((c: any) => c.name === 'Осенняя акция e2e')).toMatchObject({status: 'scheduled', audience: {segment: 'inactive'}, content: {text: 'Скидка 20% до конца недели'}});
});
