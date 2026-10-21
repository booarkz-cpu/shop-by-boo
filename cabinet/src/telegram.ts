/**
 * Thin, defensive wrapper over the Telegram WebApp SDK (telegram-web-app.js).
 *
 * Every call is feature-checked against the client's Bot API version so older
 * Telegram apps and ordinary browsers keep working: outside Telegram all helpers
 * are no-ops and `isTelegram()` is false.
 */
import {useEffect, useRef} from "react";

type Haptic = {
  impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
  notificationOccurred?: (type: "error" | "success" | "warning") => void;
  selectionChanged?: () => void;
};
type TgButton = {
  show?: () => void;
  hide?: () => void;
  onClick?: (cb: () => void) => void;
  offClick?: (cb: () => void) => void;
  setParams?: (params: Record<string, unknown>) => void;
  showProgress?: (leaveActive?: boolean) => void;
  hideProgress?: () => void;
  enable?: () => void;
  disable?: () => void;
};
type Inset = {top?: number; bottom?: number; left?: number; right?: number};
export type TelegramWebApp = {
  initData?: string;
  version?: string;
  platform?: string;
  colorScheme?: "light" | "dark";
  themeParams?: Record<string, string | undefined>;
  viewportStableHeight?: number;
  safeAreaInset?: Inset;
  contentSafeAreaInset?: Inset;
  ready?: () => void;
  expand?: () => void;
  isVersionAtLeast?: (version: string) => boolean;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  setBottomBarColor?: (color: string) => void;
  disableVerticalSwipes?: () => void;
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  onEvent?: (event: string, cb: () => void) => void;
  offEvent?: (event: string, cb: () => void) => void;
  openLink?: (url: string, options?: {try_instant_view?: boolean}) => void;
  showConfirm?: (message: string, cb: (ok: boolean) => void) => void;
  HapticFeedback?: Haptic;
  BackButton?: TgButton;
  MainButton?: TgButton;
};

export function telegram(): TelegramWebApp | undefined {
  if (typeof window === "undefined") return undefined;
  const app = (window as any).Telegram?.WebApp as TelegramWebApp | undefined;
  // The SDK is also loaded in normal browsers; only a real launch carries initData.
  return app && typeof app.initData === "string" && app.initData.length > 0 ? app : undefined;
}

export function isTelegram(): boolean {
  return Boolean(telegram());
}

function atLeast(version: string): boolean {
  const app = telegram();
  try {
    return Boolean(app?.isVersionAtLeast?.(version));
  } catch {
    return false;
  }
}

function safely(action: () => void) {
  try {
    action();
  } catch {
    /* Unsupported methods throw WebAppMethodUnsupported on old clients; the UI keeps working. */
  }
}

export const haptic = {
  tap(style: "light" | "medium" | "heavy" | "rigid" | "soft" = "light") {
    const app = telegram();
    if (app && atLeast("6.1")) safely(() => app.HapticFeedback?.impactOccurred?.(style));
  },
  select() {
    const app = telegram();
    if (app && atLeast("6.1")) safely(() => app.HapticFeedback?.selectionChanged?.());
  },
  notify(type: "error" | "success" | "warning") {
    const app = telegram();
    if (app && atLeast("6.1")) safely(() => app.HapticFeedback?.notificationOccurred?.(type));
  },
};

const DARK = {bg: "#090d16", header: "#0b111d"};
const LIGHT = {bg: "#f3f6fb", header: "#ffffff"};

/** Mirrors Telegram's scheme, viewport and safe areas into <html> attributes/CSS variables. */
function syncChrome(app: TelegramWebApp) {
  const root = document.documentElement;
  const scheme = app.colorScheme === "light" ? "light" : "dark";
  root.dataset.theme = scheme;
  root.dataset.surface = "miniapp";
  const colors = scheme === "light" ? LIGHT : DARK;
  if (atLeast("6.1")) {
    safely(() => app.setHeaderColor?.(colors.header));
    safely(() => app.setBackgroundColor?.(colors.bg));
  }
  if (atLeast("7.10")) safely(() => app.setBottomBarColor?.(colors.header));
  const accent = app.themeParams?.button_color;
  if (accent && /^#[0-9a-f]{6}$/i.test(accent)) root.style.setProperty("--tg-accent", accent);
  if (app.viewportStableHeight) root.style.setProperty("--tg-viewport", `${app.viewportStableHeight}px`);
  const safe = app.safeAreaInset || {};
  const content = app.contentSafeAreaInset || {};
  root.style.setProperty("--tg-safe-top", `${(safe.top || 0) + (content.top || 0)}px`);
  root.style.setProperty("--tg-safe-bottom", `${(safe.bottom || 0) + (content.bottom || 0)}px`);
}

/** Call once on boot. Returns a cleanup function. */
export function initTelegram(): () => void {
  const app = telegram();
  if (!app) return () => undefined;
  safely(() => app.ready?.());
  safely(() => app.expand?.());
  if (atLeast("7.7")) safely(() => app.disableVerticalSwipes?.());
  const sync = () => syncChrome(app);
  sync();
  const events = ["themeChanged", "viewportChanged", "safeAreaChanged", "contentSafeAreaChanged"];
  events.forEach((event) => safely(() => app.onEvent?.(event, sync)));
  // Light haptic feedback for every actionable control, like native Telegram UI.
  const onClick = (event: MouseEvent) => {
    const target = (event.target as HTMLElement | null)?.closest("button:not(:disabled),a[href],[role='tab'],[role='radio']");
    if (target) haptic.tap(target.matches(".btn-primary,.primary") ? "medium" : "light");
  };
  document.addEventListener("click", onClick, {capture: true});
  return () => {
    events.forEach((event) => safely(() => app.offEvent?.(event, sync)));
    document.removeEventListener("click", onClick, {capture: true});
  };
}

/** Shows Telegram's native back button while `visible`; it calls `onBack`. */
export function useBackButton(visible: boolean, onBack: () => void) {
  const handler = useRef(onBack);
  handler.current = onBack;
  useEffect(() => {
    const app = telegram();
    if (!app?.BackButton || !atLeast("6.1")) return;
    const button = app.BackButton;
    const click = () => handler.current();
    safely(() => button.onClick?.(click));
    safely(() => (visible ? button.show?.() : button.hide?.()));
    return () => {
      safely(() => button.offClick?.(click));
      safely(() => button.hide?.());
    };
  }, [visible]);
}

/** Drives Telegram's native bottom MainButton. `text: null` hides it. */
export function useMainButton(text: string | null, onClick: () => void, busy = false) {
  const handler = useRef(onClick);
  handler.current = onClick;
  useEffect(() => {
    const app = telegram();
    const button = app?.MainButton;
    if (!button) return;
    if (!text) {
      safely(() => button.hide?.());
      return;
    }
    const click = () => handler.current();
    safely(() => button.setParams?.({text, is_visible: true, is_active: !busy}));
    safely(() => (busy ? button.showProgress?.(false) : button.hideProgress?.()));
    safely(() => button.onClick?.(click));
    return () => {
      safely(() => button.offClick?.(click));
      safely(() => button.hideProgress?.());
      safely(() => button.hide?.());
    };
  }, [text, busy]);
}

/** Asks Telegram to confirm closing the app while a payment is being created. */
export function setClosingGuard(active: boolean) {
  const app = telegram();
  if (!app || !atLeast("6.2")) return;
  safely(() => (active ? app.enableClosingConfirmation?.() : app.disableClosingConfirmation?.()));
}

/** Opens external links (payment pages, app stores) through Telegram when embedded. */
export function openExternal(url: string) {
  const app = telegram();
  if (app?.openLink) {
    safely(() => app.openLink?.(url));
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}
