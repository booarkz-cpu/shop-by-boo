import {expect, test} from '@playwright/test';

// v28.61.0 (stage 7): no black screens. Every section of the menu opens with its heading, without the
// error boundary, and fits a phone without horizontal scrolling.
const FAILED = /Раздел не удалось открыть|Панель не открылась|Application error/;

async function signIn(page: any) {
  await page.addInitScript(() => localStorage.setItem('rw_lang', 'ru'));
  await page.goto('/');
  await page.getByLabel('Email', {exact: true}).fill('browser@example.test');
  await page.getByLabel('Пароль', {exact: true}).fill('browser-only-password');
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page.locator('.hub-card').first()).toBeVisible();
}

for (const viewport of [{name: 'desktop', width: 1440, height: 900}, {name: 'phone', width: 390, height: 844}]) {
  test(`every section opens on ${viewport.name}`, async ({page}) => {
    test.setTimeout(240_000);
    await signIn(page);
    const labels: string[] = await page.locator('.sidebar nav button').evaluateAll(
      (buttons: HTMLElement[]) => buttons.map((b) => (b.getAttribute('aria-label') || b.innerText).trim()).filter(Boolean));
    expect(labels.length).toBeGreaterThan(70);
    const problems: string[] = [];
    const visited = new Set<string>();
    for (const label of labels) {
      if (visited.has(label)) continue;
      visited.add(label);
      // The section is opened from the desktop menu, then checked at the target width.
      await page.setViewportSize({width: 1440, height: 900});
      await page.evaluate((name: string) => {
        const button = [...document.querySelectorAll('.sidebar nav button')].find((b) => ((b.getAttribute('aria-label') || (b as HTMLElement).innerText).trim()) === name);
        (button as HTMLElement | undefined)?.click();
      }, label);
      await expect(page.locator('main h1').first()).toHaveText(label);
      await page.waitForLoadState('networkidle');
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await page.waitForTimeout(50);
      const text = await page.locator('main').innerText();
      if (FAILED.test(text)) problems.push(`${label}: error boundary`);
      // A section whose source is unavailable (no Remnawave in the browser stand) shows the reason and a retry.
      if (text.includes('Не удалось загрузить раздел') && !(text.includes('Повторить загрузку') && text.includes('Ответ сервера')))
        problems.push(`${label}: load error without reason or retry`);
      if (!text.trim()) problems.push(`${label}: empty main`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 1) problems.push(`${label}: ${overflow}px horizontal scroll`);
    }
    expect(visited.size).toBeGreaterThan(70);
    expect(problems).toEqual([]);
  });
}
