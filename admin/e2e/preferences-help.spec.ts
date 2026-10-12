import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("browser@example.test");
  await page
    .getByLabel("Пароль", { exact: true })
    .fill("browser-only-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.locator(".sidebar")).toBeVisible();
}

test("theme and language menus support keyboard focus and persist preferences", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("rw_lang", "ru"));
  await login(page);
  const theme = page.getByRole("button", { name: "Сменить тему", exact: true });
  await theme.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toBeVisible();
  await expect(
    page.getByRole("menuitemradio", { name: "Тёмная" }),
  ).toHaveAttribute("aria-checked", "true");
  await page.getByRole("menuitemradio", { name: "Светлая" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(theme).toBeFocused();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Выбрать язык", exact: true }).click();
  await page
    .getByRole("menuitemradio", { name: "English", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("button", { name: /Home/ })).toBeVisible();
  const language = page.getByRole("button", {
    name: "Choose language",
    exact: true,
  });
  await language.click();
  await expect(
    page.getByRole("menuitemradio", { name: "English", exact: true }),
  ).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(language).toBeFocused();
});

test("server theme default applies to a browser without a saved preference", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("rw_lang", "ru");
    localStorage.removeItem("rw_theme");
  });
  await page.route("**/api/public/branding", (route) =>
    route.fulfill({ json: { theme_default: "light" } }),
  );
  await login(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await page.evaluate(() => localStorage.getItem("rw_theme"))).toBe(
    "light",
  );
});

test("field help opens with focus and touch, stays in viewport and follows language", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem("rw_lang", "ru"));
  await page.goto("/");
  const email = page.getByLabel("Email", { exact: true });
  await email.focus();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await expect(page.getByRole("tooltip")).toContainText("email администратора");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Подсказка: Email", exact: true })
    .click();
  await expect(page.getByRole("tooltip")).toBeVisible();
  const bounds = await page.getByRole("tooltip").boundingBox();
  expect(bounds).not.toBeNull();
  if (bounds) {
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  }
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Выбрать язык", exact: true }).click();
  await page
    .getByRole("menuitemradio", { name: "English", exact: true })
    .click();
  await expect(email).toHaveAttribute(
    "aria-description",
    /administrator email/i,
  );
  await page.getByRole("button", { name: "Help: Email", exact: true }).click();
  await expect(page.getByRole("tooltip")).toContainText("administrator email");
  await expect(
    page.getByRole("heading", { name: "Sign in to the console" }),
  ).toBeVisible();
});

test("select supports keyboard choices, icons and disabled persisted identity", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("rw_lang", "ru"));
  await login(page);
  await page.getByRole("button", { name: /Новости и страницы/ }).click();
  const kind = page.getByRole("combobox", {
    name: "Тип страницы",
    exact: true,
  });
  await expect(page.locator("select[data-native-select]").first()).toBeHidden();
  await kind.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("listbox")).toBeVisible();
  await expect(
    page
      .getByRole("option", { name: "Юридическая страница", exact: true })
      .locator("svg")
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole("option", { name: "Новость", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("End");
  await expect(
    page.getByRole("option", { name: "Юридическая страница", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(kind).toContainText("Юридическая страница");
  await page.getByLabel("Slug", { exact: true }).fill("keyboard-select-page");
  await page
    .getByLabel("Заголовок", { exact: true })
    .fill("Keyboard legal page");
  await page
    .getByLabel("Текст блока", { exact: true })
    .fill("Keyboard accessible draft");
  await page
    .getByRole("button", { name: "Сохранить черновик", exact: true })
    .click();
  await expect(kind).toBeDisabled();
  await expect(
    page.getByRole("combobox", { name: "Язык", exact: true }),
  ).toBeDisabled();
});
