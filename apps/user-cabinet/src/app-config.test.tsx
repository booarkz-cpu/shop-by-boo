import React from "react";
import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {AppConfigProvider, MOCK_CONFIG, applyTheme, useAppConfig, withDefaults, type AppConfig} from "./app-config";
import {ConfigNotice, ConsentGate, InfoSection, PromoCards, ReferralTerms, SectionBanner, ServerCatalog, SupportButtons, WalletTopup, countdown, flagEmoji, groupServers, referralLink} from "./miniapp-sections";

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

const cfg = (patch: Partial<AppConfig> = {}) => withDefaults({...MOCK_CONFIG, version: "test", offline: false, ...patch});
const wrap = (ui: React.ReactNode, config = cfg()) => render(<AppConfigProvider initialConfig={config}>{ui}</AppConfigProvider>);

it("mock config covers every screen the Mini App renders", () => {
  for (const key of ["theme", "texts", "navigation", "banners", "promos", "plans", "servers", "wallet", "referral", "support", "info", "consent"]) expect(MOCK_CONFIG).toHaveProperty(key);
  expect(MOCK_CONFIG.navigation.map((n) => n.kind)).toContain("info");
  expect(MOCK_CONFIG.banners.overview).toBe("/assets/banners/home.jpg");
  expect(MOCK_CONFIG.texts.wallet_title).toBe("Пополнение баланса");
});

it("falls back to the bundled mock and offers a retry when the API is unreachable", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(new Response(JSON.stringify({...MOCK_CONFIG, version: "live", offline: false, texts: {greeting: "Хей, {name}!"}}), {status: 200}));
  function Probe() { const {config, status} = useAppConfig(); return <p data-testid="probe">{status}:{config.version}:{config.texts.greeting}:{config.texts.wallet_title}</p>; }
  render(<AppConfigProvider><ConfigNotice /><Probe /></AppConfigProvider>);
  await screen.findByText(/Нет связи с сервером/);
  expect(screen.getByTestId("probe").textContent).toBe("offline:mock:Привет, {name}!:Пополнение баланса");
  fireEvent.click(screen.getByRole("button", {name: "Повторить"}));
  await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("ready:live:Хей, {name}!:Пополнение баланса"));
  expect(fetchMock.mock.calls[1][0]).toBe("/api/app-config");
  expect(JSON.parse(localStorage.getItem("rw_app_config_v1")!).version).toBe("live");
});

it("sends Telegram initData so the server can greet the user", async () => {
  (window as any).Telegram = {WebApp: {initData: "user=%7B%7D&hash=abc"}};
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({...MOCK_CONFIG, version: "x"}), {status: 200}));
  render(<AppConfigProvider><span /></AppConfigProvider>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect((fetchMock.mock.calls[0][1]!.headers as any)["X-Telegram-Init-Data"]).toBe("user=%7B%7D&hash=abc");
  delete (window as any).Telegram;
});

it("maps config colours onto the design tokens with a readable text colour", () => {
  const root = document.createElement("html");
  applyTheme({"--cfg-accent": "#39ff88", "--cfg-bg": "#010203", "--cfg-radius": "20px"}, root);
  expect(root.style.getPropertyValue("--primary-rgb")).toBe("57 255 136");
  expect(root.style.getPropertyValue("--on-primary")).toBe("#04120a");
  expect(root.style.getPropertyValue("--bg")).toBe("#010203");
  expect(root.style.getPropertyValue("--radius")).toBe("20px");
  const light = document.createElement("html"); light.dataset.theme = "light";
  applyTheme({"--cfg-accent": "#1d4ed8", "--cfg-bg": "#000000"}, light);
  expect(light.style.getPropertyValue("--on-primary")).toBe("#ffffff");
  expect(light.style.getPropertyValue("--bg")).toBe("");
});

it("shows the section banner and falls back to the bundled image", () => {
  wrap(<SectionBanner kind="wallet" title="Кошелёк" />, cfg({banners: {wallet: "/media/bot-banner-topup-x.jpg"}}));
  const img = screen.getByRole("img", {name: "Кошелёк"}) as HTMLImageElement;
  expect(img.getAttribute("src")).toBe("/media/bot-banner-topup-x.jpg");
  fireEvent.error(img);
  expect(screen.getByRole("img", {name: "Кошелёк"}).getAttribute("src")).toBe("/assets/banners/topup.jpg");
});

it("renders promo cards with a live countdown and hides expired ones", () => {
  const go = vi.fn();
  const soon = new Date(Date.now() + 3_725_000).toISOString();
  wrap(<PromoCards go={go} />, cfg({promos: [
    {id: "a", title: "Скидка", text: "Только сегодня", discount: "-30%", ends_at: soon, button_text: "Выбрать", link: "#plans"},
    {id: "b", title: "Прошла", text: "", discount: "", ends_at: "2020-01-01T00:00:00Z", button_text: "", link: ""}]}));
  expect(screen.getByText("-30%")).toBeTruthy();
  expect(screen.getByText(/01:02:0\d/)).toBeTruthy();
  expect(screen.queryByText("Прошла")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "Выбрать"}));
  expect(go).toHaveBeenCalledWith("plans");
  expect(countdown(new Date(Date.now() + 2 * 86400_000 + 5000).toISOString(), Date.now())).toMatch(/^2д 0ч 0м$/);
});

it("groups servers by configured categories with flags", () => {
  const groups = groupServers([{name: "Frankfurt", country: "DE"}, {name: "msk-white-1", country: "RU"}, {name: "Tokyo", country: "JP"}],
    [{id: "eu", title: "Европа", icon: "globe", countries: ["DE"], match: []}, {id: "white", title: "Белые списки", icon: "shield", countries: [], match: ["white"]}]);
  expect(groups.map((g) => [g.id, g.nodes.length])).toEqual([["eu", 1], ["white", 1], ["other", 1]]);
  expect(flagEmoji("de")).toBe("🇩🇪");
  expect(flagEmoji("??")).toBe("🌐");
  wrap(<ServerCatalog servers={{ok: true, online: 1, total: 1, nodes: [{name: "Frankfurt", country: "DE", status: "online", users_online: 4}]}} />,
    cfg({servers: {categories: [{id: "eu", title: "Европа", icon: "globe", countries: ["DE"], match: []}], show_load: true}}));
  expect(screen.getByText("Европа")).toBeTruthy();
  expect(screen.getByText("DE · 4 онлайн")).toBeTruthy();
});

it("tops up the wallet with the chosen amount and method (YooKassa SBP)", async () => {
  const request = vi.fn(async () => ({id: "p", url: ""}));
  const flash = vi.fn();
  wrap(<WalletTopup request={request} balance="10.00" reload={async () => {}} flash={flash} onConsentRequired={() => {}} />, cfg({wallet: {...MOCK_CONFIG.wallet, amounts: [100, 500],
    methods: [{id: "card", title: "Карта", icon: "card", provider: "yookassa", yookassa_method: "", available: true},
      {id: "sbp", title: "СБП", icon: "sbp", provider: "yookassa", yookassa_method: "sbp", available: true},
      {id: "off", title: "Выключен", icon: "crypto", provider: "rollypay", yookassa_method: "", available: false}]}}));
  expect(screen.queryByText("Выключен")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "500 RUB"}));
  fireEvent.click(screen.getByRole("radio", {name: "СБП"}));
  fireEvent.click(screen.getByRole("button", {name: /Пополнить · 500/}));
  await waitFor(() => expect(request).toHaveBeenCalled());
  const [path, options] = request.mock.calls[0] as any;
  expect(path).toBe("/api/me/wallet/topup");
  expect(JSON.parse(options.body)).toEqual({amount: 500, provider: "yookassa", method: "sbp"});
  expect(options.headers["Idempotency-Key"]).toMatch(/^[a-f0-9-]{36}$/);
});

it("pays with Telegram Stars through openInvoice", async () => {
  const openInvoice = vi.fn((url: string, cb: (s: string) => void) => cb("paid"));
  (window as any).Telegram = {WebApp: {initData: "x", openInvoice, isVersionAtLeast: () => true}};
  const request = vi.fn(async () => ({url: "https://t.me/$inv", stars: 334}));
  const flash = vi.fn();
  wrap(<WalletTopup request={request} balance="0" reload={async () => {}} flash={flash} onConsentRequired={() => {}} />, cfg({wallet: {...MOCK_CONFIG.wallet, amounts: [500],
    stars: {enabled: true, rate: "1.5", min_stars: 10}, methods: [{id: "stars", title: "Telegram Stars", icon: "star", provider: "telegram_stars", yookassa_method: "", available: true}]}}));
  fireEvent.click(screen.getByRole("button", {name: "500 RUB"}));
  expect(screen.getByText("К оплате: ⭐ 334 Stars")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: /Пополнить/}));
  await waitFor(() => expect(openInvoice).toHaveBeenCalledWith("https://t.me/$inv", expect.any(Function)));
  expect((request.mock.calls[0] as any)[0]).toBe("/api/me/wallet/stars-invoice");
  await waitFor(() => expect(flash).toHaveBeenCalledWith(expect.stringContaining("Stars")));
  delete (window as any).Telegram;
});

it("asks for the offer consent and stores it", async () => {
  let accepted = false;
  const request = vi.fn(async (path: string, o?: RequestInit) => {
    if (o?.method === "POST") { accepted = true; return {accepted: true}; }
    return {accepted, version: "v2"};
  });
  const done = vi.fn();
  wrap(<ConsentGate request={request} onAccepted={done} />, cfg({consent: {enabled: true, required_for_payment: true, version: "v2", text: "Принимаю оферту", page_slug: "offer"}}));
  await screen.findByText(/Принимаю оферту/);
  const button = screen.getByRole("button", {name: "Принимаю"}) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() => expect(done).toHaveBeenCalled());
  expect(JSON.parse(String((request.mock.calls.find((c: any) => c[1]?.method === "POST") as any)[1].body))).toEqual({version: "v2", source: "cabinet"});
  expect(screen.queryByRole("button", {name: "Принимаю"})).toBeNull();
});

it("builds the referral link and support buttons from the config", () => {
  expect(referralLink("https://t.me/bot?start=ref_{code}", "AB C")).toBe("https://t.me/bot?start=ref_AB%20C");
  const go = vi.fn();
  wrap(<><ReferralTerms code="LUSI" flash={() => {}} /><SupportButtons go={go} /></>, cfg({
    referral: {...MOCK_CONFIG.referral, link_template: "https://t.me/corgi?start=ref_{code}", conditions: "10% с каждой оплаты"},
    support: {ticket_form: true, buttons: [{title: "FAQ", icon: "help", link: "#info"}]}}));
  expect(screen.getByText("https://t.me/corgi?start=ref_LUSI")).toBeTruthy();
  expect(screen.getByText("10% с каждой оплаты")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "FAQ"}));
  expect(go).toHaveBeenCalledWith("info");
});

it("lists info pages and opens one", async () => {
  const request = vi.fn(async () => ({title: "Публичная оферта", summary: "Условия", blocks: [{kind: "text", title: "1. Предмет", text: "Сервис VPN", label: "", url: "", items: []}]}));
  wrap(<InfoSection request={request} locale="ru" />);
  fireEvent.click(screen.getByRole("button", {name: "Публичная оферта"}));
  await screen.findByText("1. Предмет");
  expect((request.mock.calls[0] as any)[0]).toBe("/api/public/pages/offer?locale=ru");
  fireEvent.click(screen.getByRole("button", {name: "← Все документы"}));
  expect(screen.getByRole("button", {name: "Частые вопросы"})).toBeTruthy();
});
