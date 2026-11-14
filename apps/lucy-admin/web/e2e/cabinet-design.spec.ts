import {expect, test, type Page} from '@playwright/test';

async function signIn(page: Page) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/cabinet/');
  await page.getByLabel('Электронная почта').fill('customer@example.test');
  await page.getByLabel('Пароль').fill('customer-browser-password');
  await page.locator('form').getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.getByRole('region', {name: 'Статус подписки'})).toBeVisible();
}

test('customer overview shows subscription state, wallet tiles and the unified navigation', async ({page}) => {
  await signIn(page);
  await expect(page.getByText('Подписка не подключена')).toBeVisible();
  await expect(page.getByRole('region', {name: 'Статус подписки'}).getByText('Нет подписки')).toBeVisible();
  await expect(page.getByRole('button', {name: /Кошелёк/}).first()).toBeVisible();
  await expect(page.getByRole('navigation', {name: 'Основные разделы'})).toBeHidden();
  await page.getByRole('region', {name: 'Статус подписки'}).getByRole('button', {name: 'Выбрать тариф'}).click();
  await expect(page.getByRole('heading', {name: 'Тарифы', level: 2})).toBeVisible();
  await expect(page.getByLabel('Для какой подписки')).toBeVisible();
});

test('mobile cabinet has a bottom tab bar, a drawer and no horizontal scroll', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await signIn(page);
  const tabs = page.getByRole('navigation', {name: 'Основные разделы'});
  await expect(tabs).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await tabs.getByRole('button', {name: /Подключение/}).click();
  await expect(page.getByRole('heading', {name: 'Подключение', level: 2})).toBeVisible();
  await expect(page.getByRole('list', {name: 'Шаги подключения'}).getByRole('listitem')).toHaveCount(3);
  await page.getByRole('tab', {name: 'iOS'}).click();
  await expect(page.getByRole('tab', {name: 'iOS'})).toHaveAttribute('aria-selected', 'true');
  await tabs.getByRole('button', {name: /Ещё/}).click();
  await expect(page.locator('.user-sidebar')).toHaveClass(/drawer-open/);
  await page.getByRole('navigation', {name: 'Разделы кабинета'}).getByRole('button', {name: /Платежи/}).click();
  await expect(page.locator('.user-sidebar')).not.toHaveClass(/drawer-open/);
  await expect(page.getByRole('heading', {name: 'История платежей'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('profile can be renamed from the security section', async ({page}) => {
  await signIn(page);
  await page.getByRole('navigation', {name: 'Разделы кабинета'}).getByRole('button', {name: /Безопасность/}).click();
  const profile = page.getByRole('region', {name: 'Профиль'});
  await expect(profile.getByText('customer@example.test')).toBeVisible();
  await profile.getByRole('button', {name: 'Изменить имя'}).click();
  await profile.getByLabel('Имя в кабинете').fill('Browser Customer');
  await profile.getByRole('button', {name: 'Сохранить'}).click();
  await expect(profile.getByText('Профиль сохранён')).toBeVisible();
  await expect(profile.getByText('Browser Customer')).toBeVisible();
});

test('Telegram Mini App integration drives theme, haptics, BackButton and MainButton', async ({page}) => {
  await signIn(page);
  await page.addInitScript(() => {
    const calls: string[] = [];
    (window as any).__tgCalls = calls;
    const button = (name: string) => {
      const handlers: (() => void)[] = [];
      return {
        handlers,
        text: '',
        visible: false,
        show() { this.visible = true; calls.push(`${name}.show`); },
        hide() { this.visible = false; calls.push(`${name}.hide`); },
        onClick(cb: () => void) { handlers.push(cb); },
        offClick(cb: () => void) { const i = handlers.indexOf(cb); if (i >= 0) handlers.splice(i, 1); },
        setParams(p: any) { if (p.text) this.text = p.text; if (p.is_visible) this.visible = true; calls.push(`${name}.setParams:${p.text}`); },
        showProgress() {}, hideProgress() {},
      };
    };
    (window as any).Telegram = {WebApp: {
      initData: 'query_id=browser-test', version: '8.0', platform: 'ios', colorScheme: 'light',
      themeParams: {button_color: '#2481cc'}, viewportStableHeight: 700,
      safeAreaInset: {top: 0, bottom: 20}, contentSafeAreaInset: {top: 0, bottom: 0},
      isVersionAtLeast: () => true,
      ready: () => calls.push('ready'), expand: () => calls.push('expand'),
      disableVerticalSwipes: () => calls.push('disableVerticalSwipes'),
      setHeaderColor: (c: string) => calls.push(`header:${c}`), setBackgroundColor: (c: string) => calls.push(`bg:${c}`),
      setBottomBarColor: () => undefined, onEvent: () => undefined, offEvent: () => undefined,
      enableClosingConfirmation: () => calls.push('closing:on'), disableClosingConfirmation: () => calls.push('closing:off'),
      HapticFeedback: {
        impactOccurred: (s: string) => calls.push(`impact:${s}`),
        notificationOccurred: (s: string) => calls.push(`notify:${s}`),
        selectionChanged: () => calls.push('selection'),
      },
      BackButton: button('back'), MainButton: button('main'),
    }};
  });
  // The fixture cannot sign Telegram initData; the existing cookie session is reused.
  await page.route('**/api/auth/telegram', (route) => route.fulfill({json: {ok: true}}));
  await page.setViewportSize({width: 390, height: 844});
  await page.reload();
  await expect(page.getByRole('region', {name: 'Статус подписки'})).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.locator('html')).toHaveAttribute('data-surface', 'miniapp');
  const calls = () => page.evaluate(() => (window as any).__tgCalls as string[]);
  await expect.poll(calls).toEqual(expect.arrayContaining(['ready', 'expand', 'disableVerticalSwipes', 'header:#ffffff', 'main.setParams:Выбрать тариф']));
  expect(await page.evaluate(() => (window as any).Telegram.WebApp.BackButton.visible)).toBe(false);

  await page.getByRole('navigation', {name: 'Основные разделы'}).getByRole('button', {name: /Подключение/}).click();
  await expect.poll(calls).toEqual(expect.arrayContaining(['impact:light', 'selection', 'back.show']));
  // Native BackButton returns to the previous section.
  await page.evaluate(() => (window as any).Telegram.WebApp.BackButton.handlers.forEach((cb: () => void) => cb()));
  await expect(page.getByRole('region', {name: 'Статус подписки'})).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as any).Telegram.WebApp.BackButton.visible)).toBe(false);
  // MainButton opens the tariff list on a fresh account.
  await page.evaluate(() => (window as any).Telegram.WebApp.MainButton.handlers.forEach((cb: () => void) => cb()));
  await expect(page.getByRole('heading', {name: 'Тарифы', level: 2})).toBeVisible();
});
