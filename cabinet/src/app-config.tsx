"use client";
/**
 * Data-driven Mini App: one JSON document from GET /api/app-config describes the theme,
 * navigation, section banners, promo cards, server categories, wallet amounts and payment
 * methods, referral terms, support buttons, info pages and the offer consent.
 *
 * Loading order: last good config from localStorage (instant paint) → network → bundled
 * mock-config.json when the API is unreachable (the UI then shows an offline notice with
 * a retry button). Telegram initData goes in X-Telegram-Init-Data so the server can greet
 * the user by name.
 */
import React, {createContext, useCallback, useContext, useEffect, useMemo, useState} from "react";
import mock from "./mock-config.json";

export type NavItem = {slug: string; title: string; kind: string; icon: string; banner: string; body?: string};
export type PromoCard = {id: string; title: string; text: string; discount: string; ends_at: string | null; button_text: string; link: string; image?: string};
export type ServerCategory = {id: string; title: string; icon: string; countries: string[]; match: string[]};
export type PaymentMethod = {id: string; title: string; icon: string; provider: string; yookassa_method: string; available: boolean};
export type InfoPage = {slug: string; title: string; kind: string};
export type AppConfig = {
  schema: number;
  version: string;
  offline?: boolean;
  brand: {name: string; bot_username: string; currency: string};
  theme: {vars: Record<string, string>};
  texts: Record<string, string>;
  navigation: NavItem[];
  banners: Record<string, string>;
  banner_keys: Record<string, string>;
  promos: PromoCard[];
  plans: any[];
  servers: {categories: ServerCategory[]; show_load: boolean};
  wallet: {currency: string; amounts: number[]; min: number; max: number; methods: PaymentMethod[]; stars: {enabled: boolean; rate: string; min_stars: number}};
  referral: {conditions: string; levels: string[]; withdraw_enabled: boolean; link_template: string};
  support: {buttons: {title: string; icon: string; link: string}[]; ticket_form: boolean};
  info: {pages: InfoPage[]};
  consent: {enabled: boolean; required_for_payment: boolean; version: string; text: string; page_slug: string};
  trial_days?: number;
  viewer: {first_name: string; username: string; language: string} | null;
};
export type ConfigState = {config: AppConfig; status: "loading" | "ready" | "offline"; error: string; reload: () => void};

const API = process.env.NEXT_PUBLIC_API_URL || "";
const BASE = process.env.NEXT_PUBLIC_BASE_PATH || "";
const CACHE_KEY = "rw_app_config_v1";
export const MOCK_CONFIG = mock as unknown as AppConfig;

const Ctx = createContext<ConfigState>({config: MOCK_CONFIG, status: "loading", error: "", reload: () => undefined});

function readCache(): AppConfig | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && parsed.schema === MOCK_CONFIG.schema ? parsed : null;
  } catch {
    return null;
  }
}

function writeCache(config: AppConfig) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({...config, viewer: null}));
  } catch {
    /* private mode or quota */
  }
}

/** Fills keys missing in an older server response from the bundled mock. */
export function withDefaults(config: Partial<AppConfig>): AppConfig {
  return {
    ...MOCK_CONFIG,
    ...config,
    texts: {...MOCK_CONFIG.texts, ...(config.texts || {})},
    theme: {vars: {...MOCK_CONFIG.theme.vars, ...(config.theme?.vars || {})}},
    wallet: {...MOCK_CONFIG.wallet, ...(config.wallet || {}), stars: {...MOCK_CONFIG.wallet.stars, ...(config.wallet?.stars || {})}},
    banner_keys: {...MOCK_CONFIG.banner_keys, ...(config.banner_keys || {})},
  } as AppConfig;
}

function rgb(hex: string): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
  return m ? `${parseInt(m[1], 16)} ${parseInt(m[2], 16)} ${parseInt(m[3], 16)}` : "";
}

function luminance(hex: string): number {
  const parts = rgb(hex).split(" ").map((x) => Number(x) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return parts.length === 3 ? 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2] : 0;
}

/** Maps config colours onto the cabinet design tokens (dark scheme only; light keeps its palette). */
export function applyTheme(vars: Record<string, string>, root: HTMLElement = document.documentElement) {
  const accent = vars["--cfg-accent"];
  for (const [key, value] of Object.entries(vars)) root.style.setProperty(key, value);
  if (rgb(accent)) {
    root.style.setProperty("--primary-rgb", rgb(accent));
    root.style.setProperty("--primary-hover", accent);
    root.style.setProperty("--primary-ink", accent);
    root.style.setProperty("--on-primary", luminance(accent) > 0.45 ? "#04120a" : "#ffffff");
  }
  if (vars["--cfg-accent-2"]) root.style.setProperty("--cyan", vars["--cfg-accent-2"]);
  if (rgb(vars["--cfg-danger"])) root.style.setProperty("--danger-rgb", rgb(vars["--cfg-danger"]));
  if (vars["--cfg-radius"]) root.style.setProperty("--radius", vars["--cfg-radius"]);
  if (root.dataset.theme !== "light") {
    if (vars["--cfg-bg"]) root.style.setProperty("--bg", vars["--cfg-bg"]);
    if (vars["--cfg-surface"]) root.style.setProperty("--surface", vars["--cfg-surface"]);
    if (vars["--cfg-text"]) root.style.setProperty("--text", vars["--cfg-text"]);
    if (vars["--cfg-muted"]) root.style.setProperty("--muted", vars["--cfg-muted"]);
  }
}

/** Resolves a banner/media path: API-served (/api, /media) or bundled (/assets). */
export function assetUrl(path: string): string {
  if (!path) return "";
  if (/^https:\/\//.test(path)) return path;
  if (path.startsWith("/assets/")) return BASE + path;
  if (path.startsWith("/api/") || path.startsWith("/media/")) return API + path;
  return "";
}

export function bundledBanner(config: AppConfig, kind: string): string {
  const key = config.banner_keys?.[kind];
  return key ? `${BASE}/assets/banners/${key}.jpg` : "";
}

export async function fetchConfig(initData: string, signal?: AbortSignal): Promise<AppConfig> {
  const headers: Record<string, string> = {Accept: "application/json"};
  if (initData) headers["X-Telegram-Init-Data"] = initData;
  const r = await fetch(API + "/api/app-config", {headers, credentials: "include", signal});
  if (!r.ok) throw Error(`HTTP ${r.status}`);
  const data = await r.json();
  if (!data || typeof data !== "object" || !Array.isArray(data.navigation)) throw Error("Некорректный конфиг");
  return withDefaults(data);
}

export function AppConfigProvider({children, initialConfig}: {children: React.ReactNode; initialConfig?: AppConfig}) {
  const [config, setConfig] = useState<AppConfig>(() => initialConfig || readCache() || MOCK_CONFIG);
  const [status, setStatus] = useState<ConfigState["status"]>(initialConfig ? "ready" : "loading");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    if (initialConfig) return;
    let live = true;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    const initData = (window as any).Telegram?.WebApp?.initData || "";
    setStatus((s) => (s === "offline" ? "loading" : s));
    fetchConfig(initData, ctrl.signal)
      .then((next) => {
        if (!live) return;
        setConfig(next);
        writeCache(next);
        setError("");
        setStatus("ready");
      })
      .catch((e: any) => {
        if (!live) return;
        setConfig((current) => (current.version === "mock" ? MOCK_CONFIG : {...current, offline: true}));
        setError(e?.name === "AbortError" ? "timeout" : e?.message || "network");
        setStatus("offline");
      })
      .finally(() => clearTimeout(timer));
    return () => {
      live = false;
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [attempt, initialConfig]);

  useEffect(() => {
    if (typeof document !== "undefined") applyTheme(config.theme?.vars || {});
  }, [config.theme]);

  const value = useMemo(() => ({config, status, error, reload}), [config, status, error, reload]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppConfig(): ConfigState {
  return useContext(Ctx);
}

/** Text from the config with {placeholders}; unknown keys fall back to the key itself. */
export function useText() {
  const {config} = useAppConfig();
  return useCallback((key: string, vars: Record<string, string | number> = {}) => {
    let text = config.texts?.[key] ?? MOCK_CONFIG.texts[key] ?? key;
    for (const [name, value] of Object.entries(vars)) text = text.split(`{${name}}`).join(String(value));
    return text;
  }, [config.texts]);
}
