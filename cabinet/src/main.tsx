import {ButtonTree} from "./button-tree";
import {PersonalOffers} from "./personal-offers";
import {PublicPages} from "./public-pages";
import React, {useEffect, useState, useRef, useCallback} from "react";
import {Bell, CircleHelp, CreditCard, Gift, Handshake, Home, KeyRound, LayoutGrid, ListChecks, LogOut, Menu, Moon, Server, Smartphone, Sparkles, Sun, Trophy, UserRound, Users, Wallet, X, Zap, Plug, Receipt, FileText} from "lucide-react";
import {Overview, type Traffic} from "./overview";
import {Connection} from "./connection";
import {Plans} from "./plans";
import {ProfileCard} from "./profile";
import {Skeleton, StatusBadge} from "./ui";
import {haptic, initTelegram, isTelegram, openExternal, setClosingGuard, useBackButton, useMainButton} from "./telegram";
import {SubscriptionProfiles} from "./subscription-profiles";
import {Surveys} from "./surveys";
import {Giveaways} from "./giveaways";
import {PartnerPortal} from "./partner";
import {CustomerPasskeys, loginWithPasskey} from "./passkeys";
import {Workspace} from "./workspace";
import {AccountRecovery, AccountSecurity, accountLink} from "./account-recovery";
import {AccountMerge} from "./account-merge";
import type {AccountLink} from "./account-recovery";
import {DomLocalizer, LangProvider, detectLang, t, useLang} from "./i18n";
import {AppConfigProvider, useAppConfig} from "./app-config";
import {ConfigIcon, ConfigNotice, ConfigSkeleton, ConsentGate, Greeting, InfoSection, PromoCards, ReferralTerms, SectionBanner, SectionBoundary, ServerCatalog, SupportButtons, WalletTopup} from "./miniapp-sections";

const API = process.env.NEXT_PUBLIC_API_URL || "";
// The same bundle serves the web cabinet and the Telegram Mini App build
// (NEXT_PUBLIC_SURFACE=miniapp); a real Telegram launch switches surfaces at runtime too.
const MINI_APP = process.env.NEXT_PUBLIC_SURFACE === "miniapp" || isTelegram();
const NAV_ICON: Record<string, React.ReactNode> = {
  overview: <Home aria-hidden="true" />, plans: <Zap aria-hidden="true" />, trial: <Sparkles aria-hidden="true" />, connection: <Plug aria-hidden="true" />,
  servers: <Server aria-hidden="true" />, devices: <Smartphone aria-hidden="true" />, wallet: <Wallet aria-hidden="true" />, subscription: <LayoutGrid aria-hidden="true" />,
  payments: <Receipt aria-hidden="true" />, gifts: <Gift aria-hidden="true" />, referral: <Users aria-hidden="true" />, notifications: <Bell aria-hidden="true" />,
  security: <KeyRound aria-hidden="true" />, surveys: <ListChecks aria-hidden="true" />, giveaways: <Trophy aria-hidden="true" />, support: <CircleHelp aria-hidden="true" />,
  partner: <Handshake aria-hidden="true" />, custom: <FileText aria-hidden="true" />, info: <CircleHelp aria-hidden="true" />,
};
const BOTTOM_KINDS = ["overview", "plans", "connection", "wallet"];

type MenuKind = "info" | "partner" | "giveaways" | "surveys" | "overview" | "plans" | "trial" | "connection" | "support" | "servers" | "devices" | "wallet" | "payments" | "gifts" | "referral" | "security" | "notifications" | "subscription" | "custom";
type MenuItem = {slug: string; title: string; kind: MenuKind; body?: string; icon?: string};

const FALLBACK_MENU: MenuItem[] = [
  {slug:"partner", title:"Партнёрский кабинет", kind:"partner"},
  {slug: "overview", title: "Обзор", kind: "overview"},
  {slug: "plans", title: "Тарифы", kind: "plans"},
  {slug: "trial", title: "Пробный период", kind: "trial"},
  {slug: "connection", title: "Подключение", kind: "connection"},
  {slug: "servers", title: "Серверы", kind: "servers"},
  {slug: "wallet", title: "Кошелёк", kind: "wallet"},
  {slug: "subscription", title: "Моя подписка", kind: "subscription"},
  {slug: "payments", title: "Платежи", kind: "payments"},
  {slug: "gifts", title: "Подарки", kind: "gifts"},
  {slug: "referral", title: "Реферальная программа", kind: "referral"},
  {slug: "notifications", title: "Уведомления", kind: "notifications"},
  {slug: "security", title: "Безопасность", kind: "security"},
  {slug: "surveys", title: "Опросы", kind: "surveys"},
  {slug: "giveaways", title: "Конкурсы и призы", kind: "giveaways"},
  {slug: "support", title: "Поддержка", kind: "support"},
  {slug: "info", title: "Информация", kind: "info"},
];

const PLATFORM_ORDER = ["android", "ios", "tv", "windows", "macos", "linux"] as const;
const PLATFORM_LABELS: Record<string, string> = {
  android: "Android",
  ios: "iOS",
  tv: "TV",
  windows: "Windows",
  macos: "macOS",
  linux: "Linux",
};

const PLATFORM_GUIDES: Record<string, string> = {
  android: "Установите совместимый VPN-клиент, импортируйте ссылку подписки и подключитесь.",
  ios: "Установите совместимый VPN-клиент из App Store, импортируйте ссылку подписки и подключитесь.",
  tv: "Откройте VPN-клиент на ТВ, добавьте подписку по ссылке или QR и активируйте профиль.",
  windows: "Установите клиент для Windows, импортируйте ссылку подписки и включите соединение.",
  macos: "Установите клиент для macOS, импортируйте ссылку подписки и подключитесь.",
  linux: "Установите клиент для Linux, импортируйте ссылку подписки через конфиг или URI.",
};

function csrf(): string {
  return decodeURIComponent(document.cookie.split("; ").find((x) => x.startsWith("rw_csrf="))?.split("=")[1] || "");
}

async function req(path: string, opts: RequestInit = {}) {
  const method = (opts.method || "GET").toString().toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((opts.headers as Record<string, string>) || {}),
  };
  if (method !== "GET") headers["X-CSRF-Token"] = csrf();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 12000);
  try {
    const r = await fetch(API + path, {...opts, headers, credentials:"include", signal: ctrl.signal});
    let d: any = {};
    try {
      d = await r.json();
    } catch {}
    if (!r.ok) throw Object.assign(
      Error(typeof d.detail==="string" ? d.detail : d.detail?.message || d.message || `HTTP ${r.status}`),
      {status:r.status, detail:d.detail},
    );
    return d;
  } finally {
    clearTimeout(timer);
  }
}

function pickProvider(providers: string[] | undefined): string {
  const list = Array.isArray(providers) ? providers.map(String) : [];
  const sandbox = list.find((p) => p.toLowerCase().includes("sandbox"));
  return sandbox || list[0] || "";
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString();
  } catch {
    return String(value);
  }
}

function isHtml(body?: string) {
  return Boolean(body && /<\/?[a-z][\s\S]*>/i.test(body));
}

function defaultPick(row: any) {
  const picked: Record<string, number> = {};
  for (const kind of ["devices", "traffic_gb", "days"]) {
    const opt = (row.options || []).find((o: any) => o.kind === kind && o.enabled !== false);
    if (opt) picked[kind] = opt.id;
  }
  return picked;
}

function constructorTotal(row: any, selected: Record<string, number>) {
  let sum = Number(row.base_price || 0);
  for (const kind of ["devices", "traffic_gb", "days"]) {
    const opt = (row.options || []).find((o: any) => o.id === selected[kind] && o.kind === kind);
    if (opt) sum += Number(opt.price || 0);
  }
  return Math.round(sum * 100) / 100;
}

function withServers(items: MenuItem[]) {
  const seenKinds = new Set<string>(), seenSlugs = new Set<string>();
  const result = items.filter(item => {
    if(seenSlugs.has(item.slug) || (item.kind!=="custom"&&seenKinds.has(item.kind)))return false;
    seenSlugs.add(item.slug);seenKinds.add(item.kind);return true;
  });
  for(const item of [...FALLBACK_MENU,{slug:"devices",title:"Устройства",kind:"devices" as MenuKind}]){
    if(!seenKinds.has(item.kind)&&!seenSlugs.has(item.slug)){result.push(item);seenKinds.add(item.kind);seenSlugs.add(item.slug)}
  }
  return result;
}

function AppsNotice({apps, lang}: {apps: any[]; lang: string}) {
  if (!apps.length) return null;
  return (
    <section className="form-card stack apps-note">
      <h2 className="section-title">Приложения</h2>
      <p className="section-sub">Для Android и iOS есть отдельные приложения магазина.</p>
      <div className="plan-list">
        {apps.map((row) => {
          const title = lang === "en" ? row.title_en || row.title_ru : row.title_ru || row.title_en;
          const text = lang === "en" ? row.text_en || row.text_ru : row.text_ru || row.text_en;
          const fileHref = typeof row.download_url === "string" && /^\/api\/public\/apps\/(android-user|ios-user)\/download$/.test(row.download_url) ? API + row.download_url : "";
          const storeHref = typeof row.url === "string" && row.url.startsWith("https://") ? row.url : "";
          return (
            <article className="plan-item" key={row.id || title}>
              <div>
                <h3>{title}</h3>
                <p className="section-sub">{text}</p>
              </div>
              {fileHref && <a className="btn-primary" href={fileHref}>Скачать</a>}
              {typeof row.sha256 === "string" && /^[a-f0-9]{64}$/.test(row.sha256) && (
                <p className="section-sub">Контрольная сумма {row.sha256}</p>
              )}
              {storeHref && (
                <a className="btn-primary" href={storeHref} target="_blank" rel="noopener noreferrer">
                  Скачать по ссылке
                </a>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function App() {
  const {lang, setLang} = useLang();
  const {config, status: configStatus} = useAppConfig();
  const [needConsent, setNeedConsent] = useState(false);
  const [booting, setBooting] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [accountFlow,setAccountFlow]=useState<AccountLink|null>(accountLink);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [msgError, setMsgError] = useState(false);

  const [cfg, setCfg] = useState<any>({});
  const [menu, setMenu] = useState<MenuItem[]>(FALLBACK_MENU);
  const [tab, setTab] = useState(accountFlow?"overview":location.hash.slice(1)||"overview");
  const [dash, setDash] = useState<any>();
  const [profiles,setProfiles]=useState<any[]>([]);
  const [profileTarget,setProfileTarget]=useState("current");
  const purchaseKeys=useRef<Record<string,string>>({});
  const purchaseLocked=useRef(false);
  const [plans, setPlans] = useState<any[]>([]);
  const [constructors, setConstructors] = useState<any[]>([]);
  const [pick, setPick] = useState<Record<number, Record<string, number>>>({});
  const [servers, setServers] = useState<any>();
  const [provider, setProvider] = useState("");
  const [promo, setPromo] = useState(new URLSearchParams(location.search).get("promo")||"");
  const [connection, setConnection] = useState<any>();
  const [platform, setPlatform] = useState<string>("android");
  const [ticket, setTicket] = useState({subject: "", message: ""});
  const [copied, setCopied] = useState(false);
  const [shopApps, setShopApps] = useState<any[]>([]);
  const [clientLogo, setClientLogo] = useState("");
  const [devices, setDevices] = useState<any[]>([]);
  const [routing, setRouting] = useState<any>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [traffic, setTraffic] = useState<Traffic>(null);
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try {
      return localStorage.getItem("rw_cabinet_theme") === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  });
  const navStack = useRef<string[]>([]);

  function flash(text: string, error = false) {
    setMsg(text);
    setMsgError(error);
    if (text) haptic.notify(error ? "error" : "success");
  }
  useEffect(() => {
    if (!msg) return;
    const timer = setTimeout(() => setMsg(""), msgError ? 7000 : 3500);
    return () => clearTimeout(timer);
  }, [msg, msgError]);
  useEffect(() => initTelegram(), []);
  useEffect(() => {
    // Telegram dictates the scheme inside the Mini App; the web cabinet keeps the user's choice.
    if (isTelegram()) return;
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("rw_cabinet_theme", theme);
    } catch {
      /* private mode */
    }
  }, [theme]);
  const go = useCallback((slug: string) => {
    setTab((prev) => {
      if (prev !== slug) {
        navStack.current.push(prev);
        haptic.select();
      }
      return slug;
    });
    setDrawerOpen(false);
    window.scrollTo({top: 0});
  }, []);

  useEffect(()=>{const change=()=>setTab(location.hash.slice(1)||"overview");window.addEventListener("hashchange",change);return()=>window.removeEventListener("hashchange",change)},[]);
  useEffect(()=>{if(menu.some(m=>m.slug===tab))history.replaceState(null,"",`#${tab}`)},[tab,menu]);
  useEffect(()=>{if(!drawerOpen)return;const close=(e:KeyboardEvent)=>{if(e.key==="Escape")setDrawerOpen(false)};window.addEventListener("keydown",close);return()=>window.removeEventListener("keydown",close)},[drawerOpen]);

  async function loadPublic() {
    try {
      const conf = await req("/api/public/config");
      setCfg(conf);
      setProvider(pickProvider(conf.payment_providers));
      if (!localStorage.getItem("rw_lang")) setLang(detectLang(conf.default_language));
      document.title = conf.app_name ? `${conf.app_name} · ${t("Личный кабинет")}` : t("Личный кабинет");
    } catch {
      setCfg({});
    }
    try {
      const apps = await req("/api/public/apps");
      const logo = typeof apps?.logo_url === "string" && apps.logo_url.startsWith("/media/") && !apps.logo_url.includes("..") ? apps.logo_url : "";
      setClientLogo(logo);
      setShopApps(Array.isArray(apps?.apps) ? apps.apps.filter((row: any) => row && row.audience === "user" && row.enabled !== false) : []);
    } catch {
      setClientLogo("");
      setShopApps([]);
    }
  }

  useEffect(() => {
    // Navigation comes from the app config (cabinet menu + info); system pages missing there are added by withServers.
    if (config.version === "mock" || !Array.isArray(config.navigation) || !config.navigation.length) return;
    const items = config.navigation.filter((x) => x && x.slug && x.title).map((x) => ({slug: String(x.slug), title: String(x.title), kind: (x.kind || "custom") as MenuKind, body: x.body || "", icon: x.icon}));
    const next = withServers(items.some((m) => m.slug === "devices") ? items : [...items, {slug: "devices", title: "Устройства", kind: "devices" as MenuKind, body: ""}]);
    setMenu(next);
  }, [config.version]);

  async function loadMenu() {
    try {
      const items = await req("/api/public/cabinet-menu");
      const list: MenuItem[] = Array.isArray(items) ? items : items?.items || [];
      const normalized = list
        .filter((x) => x && x.slug && x.title)
        .map((x) => ({
          slug: String(x.slug),
          title: String(x.title),
          kind: (x.kind || "custom") as MenuKind,
          body: x.body || "",
        }));
      if (normalized.length) {
        const base = normalized.some((m) => m.slug === "devices") ? normalized : [...normalized, {slug:"devices", title:"Устройства", kind:"devices" as MenuKind, body:""}];
        const menuWithServers = withServers(base);
        setMenu(menuWithServers);
        setTab((prev) => ((prev==="pages"||prev.startsWith("page/")||menuWithServers.some((m) => m.slug === prev)) ? prev : menuWithServers[0].slug));
        return;
      }
    } catch {}
    const fallback = withServers([...FALLBACK_MENU, {slug:"devices", title:"Устройства", kind:"devices", body:""}]);
    setMenu(fallback);
  }

  async function loadConstructors() {
    try {
      const rows = await req("/api/tariff-constructors");
      const list = Array.isArray(rows) ? rows : [];
      setConstructors(list);
      setPick((prev) => {
        const next = {...prev};
        for (const row of list) if (!next[row.id]) next[row.id] = defaultPick(row);
        return next;
      });
    } catch {
      setConstructors([]);
    }
  }

  async function loadServers(authed: boolean) {
    try {
      setServers(await req(authed ? "/api/me/servers" : "/api/public/servers"));
    } catch {
      setServers({ok: false, nodes: [], error: "Corgi VPN недоступен"});
    }
  }

  async function loadSession() {
    const [dashboard, planList,profileList] = await Promise.all([req("/api/me/dashboard"), req("/api/plans"),req("/api/me/subscriptions")]);
    setProfiles(Array.isArray(profileList)?profileList:[]);
    setDash(dashboard);
    setPlans(Array.isArray(planList) ? planList : []);
    setAuthed(true);
    await Promise.all([loadConstructors(), loadServers(true), (async()=>{try{setTraffic(await req("/api/me/traffic"))}catch{setTraffic(null)}})(), (async()=>{try{setDevices(await req("/api/me/devices"))}catch{setDevices([])}})(), (async()=>{try{setRouting(await req("/api/me/routing/recommendation"))}catch{setRouting(null)}})()]);
    try {
      const info = await req("/api/me/connection-info");
      setConnection(info);
      const keys = Object.keys(info?.platforms || {});
      if (keys.length) setPlatform(keys.includes("android") ? "android" : keys[0]);
    } catch {
      setConnection(null);
    }
  }

  useEffect(() => {
    const tg = (window as any).Telegram?.WebApp;
    tg?.ready?.();
    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const sandboxPayment = params.get("sandbox_payment");
    (async () => {
      await loadPublic();
      await loadMenu();
      await loadConstructors();
      await loadServers(false);
      try {
        if (tg?.initData) {
          await req("/api/auth/telegram", {method: "POST", body: JSON.stringify({initData: tg.initData})});
        } else if (code) {
          await req("/api/auth/exchange", {method: "POST", body: JSON.stringify({code})});
          const url = new URL(location.href);
          url.searchParams.delete("code");
          history.replaceState({}, "", url.pathname + url.search + url.hash);
        }
        await loadSession();
        const gift=params.get("gift");
        if(gift){
          try{await req("/api/me/gifts/redeem",{method:"POST",body:JSON.stringify({code:gift})});flash("Подарок активирован");await loadSession()}catch(e:any){flash(e.message,true)}
          const url=new URL(location.href);url.searchParams.delete("gift");history.replaceState(null,"",url.pathname+url.search+url.hash);
        }
        if (sandboxPayment) {
          try {
            await req("/api/payments/sandbox/complete", {
              method: "POST",
              body: JSON.stringify({payment_id: sandboxPayment}),
            });
            flash(t("Платёж создан"));
            await loadSession();
          } catch (e: any) {
            flash(e.message || t("Ошибка"), true);
          }
          const url = new URL(location.href);
          url.searchParams.delete("sandbox_payment");
          history.replaceState({}, "", url.pathname + url.search + url.hash);
        }
      } catch (e: any) {
        setAuthed(false);
        if (code) flash(e.message || t("Ошибка"), true);
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  async function submitAuth(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    flash("");
    try {
      const path = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
      await req(path, {method: "POST", body: JSON.stringify({email: email.trim(), password, username: username.trim() || undefined})});
      await loadSession();
      flash(authMode === "login" ? t("Добро пожаловать") : t("Создать аккаунт"));
    } catch (err: any) {
      flash(err.message || t("Ошибка"), true);
    } finally {
      setBusy(false);
    }
  }

  async function authTelegram() {
    setBusy(true);
    flash("");
    try {
      const initData = (window as any).Telegram?.WebApp?.initData;
      if (!initData) throw Error("Telegram WebApp initData недоступен");
      await req("/api/auth/telegram", {method: "POST", body: JSON.stringify({initData})});
      await loadSession();
    } catch (err: any) {
      flash(err.message || t("Ошибка"), true);
    } finally {
      setBusy(false);
    }
  }

  function oauthRedirect(path: string) {
    location.href = API + path;
  }

  async function buySelection(body: Record<string, unknown>, wallet: boolean, gift = false) {
    if(purchaseLocked.current)return;
    purchaseLocked.current=true;
    setClosingGuard(true);
    const selected=profileTarget==="current"?dash?.subscription?.id:profileTarget==="new"?undefined:Number(profileTarget);
    if(!gift)body={...body,...(profileTarget==="new"?{new_subscription:true}:selected?{subscription_id:selected}:{})};
    const partner=new URLSearchParams(location.search).get("partner");
    if(!gift&&partner)body={...body,reseller_slug:partner};
    const fingerprint=JSON.stringify({body,wallet,gift,provider:wallet?"wallet":provider});
    purchaseKeys.current[fingerprint]??=crypto.randomUUID();
    const key=purchaseKeys.current[fingerprint];
    setBusy(true);
    flash("");
    try {
      if (gift) {
        const issued=await req("/api/me/gifts/purchase",{method:"POST",headers:{"Idempotency-Key":key},body:JSON.stringify(body)});
        await loadSession();
        flash("Подарочный код: " + issued.code);
      } else if (wallet) {
        await req("/api/me/wallet/spend", {
          method: "POST",
          headers: {"Idempotency-Key": key},
          body: JSON.stringify(body),
        });
        flash(t("Оплачено с баланса"));
        await loadSession();
      } else {
        const r = await req("/api/payments/create", {
          method: "POST",
          headers: {"Idempotency-Key": key},
          body: JSON.stringify({...body, provider: provider || undefined}),
        });
        if (r.url) {
          const target=new URL(r.url,location.origin);
          if(target.protocol!=="https:"&&target.origin!==location.origin)throw Error("Некорректная ссылка оплаты");
          // Inside Telegram the payment page opens in the in-app browser so the Mini App keeps its state.
          if(isTelegram()&&target.origin!==location.origin)openExternal(target.href);else location.href=target.href;
        }
        else {
          flash(t("Платёж создан"));
          await loadSession();
        }
      }
      delete purchaseKeys.current[fingerprint];
    } catch (err: any) {
      if (err?.detail?.code === "consent_required") setNeedConsent(true);
      flash(err.message || t("Ошибка"), true);
    } finally {
      purchaseLocked.current=false;
      setClosingGuard(false);
      setBusy(false);
    }
  }

  function buy(plan: any) {
    return buySelection({plan_id: plan.id, promo_code: promo || undefined}, false);
  }

  function buyWallet(plan: any) {
    return buySelection({plan_id: plan.id, promo_code: promo || undefined}, true);
  }

  function buyConstructor(row: any, wallet: boolean, gift = false) {
    const selected = pick[row.id] || defaultPick(row);
    return buySelection({
      constructor_id: row.id,
      device_option_id: selected.devices,
      traffic_option_id: selected.traffic_gb,
      days_option_id: selected.days,
      promo_code: promo || undefined,
    }, wallet, gift);
  }

  async function claimTrial(planId: number) {
    setBusy(true);
    flash("");
    try {
      const days = Number(cfg.trial_days || 3);
      await req("/api/me/trial", {method: "POST", body: JSON.stringify({plan_id: planId, days})});
      flash(t("Пробный период активирован"));
      await loadSession();
    } catch (err: any) {
      flash(err.message || t("Ошибка"), true);
    } finally {
      setBusy(false);
    }
  }

  async function copyLink(url: string) {
    try {
      await navigator.clipboard?.writeText(url);
      setCopied(true);
      flash(t("Скопировано"));
      setTimeout(() => setCopied(false), 1600);
    } catch {
      flash(t("Ошибка"), true);
    }
  }

  async function sendTicket(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    flash("");
    try {
      await req("/api/me/support/tickets", {method: "POST", body: JSON.stringify(ticket)});
      setTicket({subject: "", message: ""});
      flash(t("Тикет создан"));
    } catch (err: any) {
      flash(err.message || t("Ошибка"), true);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await req("/api/auth/logout", {method: "POST", body: "{}"});
    } catch {}
    setAuthed(false);
    setDash(undefined);
    setConnection(undefined);
  }

  const brand = config.brand?.name || cfg.app_name || cfg.bot_name || "VPN Shop by Corgi";
  const currency = cfg.currency || "₽";
  const sub = dash?.subscription;
  const subUrl = connection?.subscription_url || sub?.subscription_url || "";
  const activeItem = menu.find((m) => m.slug === tab) || menu[0];
  const platforms = connection?.platforms || {};
  const platformKeys: string[] = [
    ...PLATFORM_ORDER.filter((k) => k in platforms),
    ...Object.keys(platforms).filter((k) => !(PLATFORM_ORDER as readonly string[]).includes(k)),
  ];
  const apiGuide = platforms[platform] ? String(platforms[platform]) : "";
  const guideText = apiGuide || PLATFORM_GUIDES[platform] || "";
  const m=cfg.miniapp||{};
  function mediaUrl(value:string){if(!value)return "";try{const url=new URL(value,location.origin);return url.protocol==="https:" || (url.origin===location.origin&&url.pathname.startsWith("/media/")) ? url.href : ""}catch{return ""}}
  function runButton(button:any){
    if(button.type==="url"){const url=mediaUrl(button.url||"");if(url)window.open(url,"_blank","noopener,noreferrer")}
    else if(button.type==="plans"||button.type==="promo"){const plansTab=menu.find(x=>x.kind==="plans");if(plansTab)setTab(plansTab.slug);if(button.type==="promo")setPromo(button.code||"")}
    else if(button.type==="field")document.getElementById(`field-${button.field_key}`)?.scrollIntoView({behavior:"smooth"});
  }

  const homeSlug = (menu.find((m) => m.kind === "overview") || menu[0])?.slug || "overview";
  const slugOf = (kind: string) => menu.find((m) => m.kind === kind)?.slug || kind;
  const goKind = (kind: string) => go(slugOf(kind));
  // Config links use "#slug", "#kind" or "#page/<slug>".
  const goLink = (target: string) => (target.startsWith("page/") || menu.some((m) => m.slug === target) ? go(target) : goKind(target));
  const back = () => {
    const previous = navStack.current.pop();
    setTab(previous && menu.some((m) => m.slug === previous) ? previous : homeSlug);
  };
  useBackButton(MINI_APP && authed && tab !== homeSlug, back);
  const mainAction: [string, () => void] | null =
    !MINI_APP || !authed || !activeItem
      ? null
      : activeItem.kind === "overview"
        ? sub
          ? ["Продлить подписку", () => goKind("plans")]
          : ["Выбрать тариф", () => goKind("plans")]
        : activeItem.kind === "connection" && subUrl
          ? ["Копировать ссылку", () => copyLink(subUrl)]
          : null;
  useMainButton(mainAction?.[0] ?? null, () => mainAction?.[1](), busy);

  if(tab==="pages"||tab.startsWith("page/"))return <DomLocalizer><PublicPages request={req} route={tab} locale={lang}/></DomLocalizer>;

  if (booting || (configStatus === "loading" && config.version === "mock")) {
    if (MINI_APP) return <DomLocalizer><ConfigSkeleton /></DomLocalizer>;
    return (
      <DomLocalizer>
        <div className="boot" role="status" aria-label="Загрузка…">
          <div className="boot-bar"><Skeleton className="sk-brand" /><Skeleton className="sk-pill" /></div>
          <div className="boot-body">
            <Skeleton className="sk-hero" />
            <div className="boot-tiles"><Skeleton className="sk-tile" /><Skeleton className="sk-tile" /><Skeleton className="sk-tile" /></div>
            <Skeleton className="sk-card" />
          </div>
        </div>
      </DomLocalizer>
    );
  }

  const bottomItems = BOTTOM_KINDS.map((kind) => menu.find((m) => m.kind === kind)).filter(Boolean) as MenuItem[];
  const userName = dash?.user?.username || dash?.user?.email || brand;

  return (
    <DomLocalizer>
      <div className={`app-shell user-shell ${authed ? "is-authenticated" : ""} ${MINI_APP ? "is-miniapp" : ""}`}>
        <header className="topbar">
          {authed && (
            <button type="button" className="drawer-toggle icon-btn" aria-label="Открыть меню" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}>
              <Menu aria-hidden="true" />
            </button>
          )}
          <div className="brand-mark">
            {clientLogo ? <img className="brand-logo" src={API + clientLogo} alt="" /> : <span className="orb" aria-hidden />}
            <span>{brand}</span>
          </div>
          <div className="btn-row topbar-actions">
            {!isTelegram() && (
              <button type="button" className="icon-btn" aria-label="Сменить тему" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
                {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
              </button>
            )}
            <button type="button" className="icon-btn lang-btn" aria-label="Сменить язык" onClick={() => setLang(lang === "ru" ? "en" : "ru")}>
              {lang === "ru" ? "EN" : "RU"}
            </button>
            {authed && !MINI_APP && (
              <button type="button" className="icon-btn topbar-logout" aria-label="Выйти" title="Выйти" onClick={logout}>
                <LogOut aria-hidden="true" />
              </button>
            )}
          </div>
        </header>

        {!authed && (
          <header className="hero" style={MINI_APP&&mediaUrl(m.background_image)?{backgroundImage:`url(${mediaUrl(m.background_image)})`,backgroundSize:"cover"}:undefined}>
            <span className="eyebrow">Личный кабинет</span>
            <h1>{MINI_APP&&m.title?m.title:brand}</h1>
            <p>Безопасный доступ к сети</p>
          </header>
        )}
        {!authed && <AppsNotice apps={shopApps} lang={lang} />}
        {MINI_APP&&(m.image||m.instructions||(m.buttons||[]).length>0)&&(!authed||activeItem?.kind==="overview")&&<section className="miniapp-extras form-card">
          {mediaUrl(m.image)&&<img src={mediaUrl(m.image)} alt="" className="miniapp-banner"/>}
          {m.subtitle&&<h2>{m.subtitle}</h2>}{m.instructions&&<p>{m.instructions}</p>}
          <ButtonTree buttons={m.buttons||[]} run={runButton} request={req} assetBase={API}/>
          {(cfg.fields||[]).map((field:any)=><div id={`field-${field.key}`} key={field.key}><h3>{field.label}</h3><p>{field.value}</p></div>)}
        </section>}

        {accountFlow ? <AccountRecovery link={accountFlow} request={req} onClose={reset=>{setAccountFlow(null);if(reset)setAuthed(false)}}/> : !authed ? (
          <section className="auth-layout">
            <div className="form-card">
              <div className="auth-switch" role="tablist">
                <button type="button" role="tab" aria-selected={authMode === "login"} className={`tab ${authMode === "login" ? "active" : ""}`} onClick={() => setAuthMode("login")}>
                  Вход
                </button>
                <button type="button" role="tab" aria-selected={authMode === "register"} className={`tab ${authMode === "register" ? "active" : ""}`} onClick={() => setAuthMode("register")}>
                  Регистрация
                </button>
              </div>
              <form className="stack" onSubmit={submitAuth}>
                {authMode === "register" && (
                  <label className="field">
                    Имя пользователя
                    <input
                      type="text"
                      autoComplete="username"
                      maxLength={255}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="Как к вам обращаться"
                    />
                  </label>
                )}
                <label className="field">
                  Электронная почта
                  <input
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Электронная почта"
                  />
                </label>
                <label className="field">
                  Пароль
                  <input
                    type="password"
                    autoComplete={authMode === "login" ? "current-password" : "new-password"}
                    required
                    minLength={8}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Пароль"
                  />
                </label>
                <button className="btn-primary" type="submit" disabled={busy}>
                  {authMode === "login" ? "Войти" : "Создать аккаунт"}
                </button>
              </form>
              {authMode==="login"&&<div className="auth-links"><button type="button" className="btn-ghost" disabled={busy} onClick={async()=>{setBusy(true);try{await loginWithPasskey(req);await loadSession()}catch(e:any){flash(e.message)}finally{setBusy(false)}}}><KeyRound aria-hidden="true"/>Войти с ключом доступа</button><button type="button" className="btn-link" onClick={()=>setAccountFlow({kind:"request",token:""})}>Забыли пароль?</button></div>}
              <button type="button" className="btn-soft auth-toggle" onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}>
                {authMode === "login" ? "Нет аккаунта? Зарегистрироваться" : "Уже есть аккаунт? Войти"}
              </button>
            </div>

            <div className="form-card stack">
              <div className="divider">или</div>
              <button type="button" className="btn-oauth telegram" disabled={busy} onClick={authTelegram}>
                <span className="oauth-icon">TG</span>
                <span>Продолжить с Telegram</span>
              </button>
              {cfg.yandex_enabled && (
                <button type="button" className="btn-oauth yandex" disabled={busy} onClick={() => oauthRedirect("/api/auth/yandex")}>
                  <span className="oauth-icon">Я</span>
                  <span>Продолжить с Яндекс ID</span>
                </button>
              )}
              {cfg.vk_enabled && (
                <button type="button" className="btn-oauth vk" disabled={busy} onClick={() => oauthRedirect("/api/auth/vk")}>
                  <span className="oauth-icon">VK</span>
                  <span>Продолжить с VK ID</span>
                </button>
              )}
              {!cfg.yandex_enabled && !cfg.vk_enabled && (
                <p className="oauth-note">VK ID и Яндекс ID подключаются администратором через переменные окружения OAuth.</p>
              )}
            </div>
          </section>
        ) : (
          <div className="user-layout">
            <div className={`drawer-backdrop ${drawerOpen ? "open" : ""}`} onClick={() => setDrawerOpen(false)} aria-hidden="true" />
            <aside className={`user-sidebar ${drawerOpen ? "drawer-open" : ""}`} aria-label="Навигация кабинета">
              <div className="sidebar-heading">
                <span className="profile-avatar" aria-hidden="true">{String(userName).slice(0, 1).toUpperCase()}</span>
                <div>
                  <span className="sidebar-kicker">ЛИЧНЫЙ КАБИНЕТ</span>
                  <strong>{userName}</strong>
                  <span>{dash?.user?.email || "Ваш аккаунт"}</span>
                </div>
                <button type="button" className="icon-btn drawer-close" aria-label="Закрыть меню" onClick={() => setDrawerOpen(false)}>
                  <X aria-hidden="true" />
                </button>
              </div>
              <nav className="side-nav" aria-label="Разделы кабинета">
                {menu.map((item) => (
                  <button
                    key={item.slug}
                    type="button"
                    aria-current={tab === item.slug ? "page" : undefined}
                    className={`side-nav-item ${tab === item.slug ? "active" : ""}`}
                    onClick={() => go(item.slug)}
                  >
                    <span className="side-nav-icon" aria-hidden>{item.icon ? <ConfigIcon name={item.icon} /> : NAV_ICON[item.kind] || NAV_ICON.custom}</span>
                    <span>{item.title}</span>
                  </button>
                ))}
              </nav>
              <div className="sidebar-status">
                <span className="status-pulse" />
                <span>Ваш личный кабинет</span>
                <button type="button" className="btn-link" onClick={logout}>Выйти</button>
              </div>
            </aside>

            <main className="user-main">
              <ConfigNotice />
              <section className="panel" key={tab}>
                <SectionBoundary resetKey={tab}>
                {activeItem && !["custom", "partner"].includes(activeItem.kind) && <SectionBanner kind={activeItem.kind} title={activeItem.title} />}
                {activeItem?.kind === "overview" && (
                  <>
                    <Greeting fallbackName={dash?.user?.username || ""} />
                    <PromoCards go={goLink} />
                    <Overview sub={sub} user={dash?.user} traffic={traffic} subUrl={subUrl} currency={currency} api={API} copied={copied} onCopy={copyLink} go={goKind} formatDate={formatDate} />
                    <h3 className="section-title section-title-sm">{config.texts?.servers_title || "Серверы"}</h3>
                    <ServerCatalog servers={servers} />
                    <AppsNotice apps={shopApps} lang={lang} />
                  </>
                )}

                {activeItem?.kind === "plans" && <ConsentGate request={req} force={needConsent} onAccepted={() => setNeedConsent(false)} />}
                {activeItem?.kind === "plans" && (
                  <Plans plans={plans} constructors={constructors} pick={pick} setPick={setPick} defaultPick={defaultPick} constructorTotal={constructorTotal} promo={promo} setPromo={setPromo} providers={cfg.payment_providers || []} provider={provider} setProvider={setProvider} profiles={profiles} profileTarget={profileTarget} setProfileTarget={setProfileTarget} busy={busy} currency={currency} buy={buy} buyWallet={buyWallet} buyConstructor={buyConstructor} offers={<PersonalOffers request={req} onSelect={setPromo}/>} />
                )}

                {activeItem?.kind === "trial" && (
                  <>
                    <h2 className="section-title">Пробный период</h2>
                    <p className="section-sub">
                      Пробный период · {cfg.trial_days || 3} дней
                    </p>
                    <div className="plan-list">
                      {plans.map((p) => (
                        <article className="plan-item" key={p.id}>
                          <div>
                            <h3>{p.name}</h3>
                            <p className="section-sub" style={{margin: 0}}>
                              {cfg.trial_days || 3} дней бесплатно
                            </p>
                          </div>
                          <button type="button" className="btn-primary" disabled={busy} onClick={() => claimTrial(p.id)}>
                            Активировать пробный период
                          </button>
                        </article>
                      ))}
                      {!plans.length && <p className="section-sub">Выберите тариф для пробного периода</p>}
                    </div>
                  </>
                )}

                {activeItem?.kind === "connection" && (
                  <Connection subUrl={subUrl} api={API} copied={copied} onCopy={copyLink} platform={platform} platformKeys={platformKeys.length ? platformKeys : PLATFORM_ORDER} labels={PLATFORM_LABELS} onPlatform={setPlatform} guideText={guideText || apiGuide} goPlans={() => goKind("plans")} />
                )}

                {activeItem?.kind === "devices" && (
                  <>
                    <h2 className="section-title">Мои устройства</h2>
                    <p className="section-sub">Управляйте устройствами, которым разрешён доступ к VPN.</p>
                    <div className="plan-list">
                      <p className="section-sub">Устройства выбранной подписки. Выбрать другой профиль можно в «Моей подписке».</p>
                      {devices.map((device:any)=><article className="plan-item" key={device.id}><div><h3>{device.name}</h3><p className="section-sub">{device.platform || "unknown"} · {device.last_seen_at ? formatDate(device.last_seen_at) : "ещё не подключалось"}</p></div><StatusBadge tone={device.status === "active" ? "ok" : "warn"}>{device.status === "active" ? "Активно" : device.status}</StatusBadge></article>)}
                      {!devices.length && <p className="section-sub">Устройства появятся после первого подключения.</p>}
                    </div>
                    <div className="form-card stack" style={{marginTop:14}}>
                      <h3>Рекомендованный сервер</h3>
                      <p className="section-sub">Smart Routing выбирает доступную ноду по здоровью и нагрузке.</p>
                      {routing?.recommendation ? <div className="plan-item"><div><h3>{routing.recommendation.name}</h3><p className="section-sub">{routing.recommendation.country || "—"} · нагрузка {routing.recommendation.load}%</p></div><StatusBadge tone="ok">Рекомендуется</StatusBadge></div> : <p className="section-sub">Рекомендация пока недоступна.</p>}
                    </div>
                  </>
                )}

                {activeItem?.kind === "servers" && (
                  <>
                    <h2 className="section-title">Серверы</h2>
                    <p className="section-sub">Статус узлов без адресов и служебных данных</p>
                    <ServerCatalog servers={servers} />
                  </>
                )}

                {activeItem?.kind === "partner" && <><h2 className="section-title">{activeItem.title}</h2><PartnerPortal request={req}/></>}

                {["wallet","payments","gifts","referral","subscription","security","notifications","support"].includes(activeItem?.kind||"") && <>
                  <h2 className="section-title">{activeItem.title}</h2>
                  {activeItem.kind==="security"&&<><ProfileCard request={req} onSaved={loadSession}/><AccountSecurity request={req} onPasswordChanged={()=>{setAuthed(false);flash("Пароль изменён. Войдите снова.")}}/><CustomerPasskeys req={req}/><AccountMerge request={req} onMerged={loadSession}/></>}
                  {activeItem.kind==="subscription"&&<SubscriptionProfiles profiles={profiles} request={req} reload={loadSession}/>}
                  {activeItem.kind==="wallet"&&<><ConsentGate request={req} force={needConsent} onAccepted={()=>setNeedConsent(false)}/><WalletTopup request={req} balance={String(dash?.user?.wallet_balance ?? "0.00")} reload={loadSession} flash={flash} onConsentRequired={()=>setNeedConsent(true)}/></>}
                  {activeItem.kind==="referral"&&<ReferralTerms code={dash?.user?.referral_code||""} flash={flash}/>}
                  {activeItem.kind==="support"&&<SupportButtons go={goLink}/>}
                  <Workspace compact={["wallet","referral"].includes(activeItem.kind)} key={activeItem.kind+":"+(sub?.id||"none")} kind={activeItem.kind} request={req} reload={loadSession} plans={plans} provider={provider} botUsername={cfg.bot_username||""} providers={(cfg.payment_providers||[]).filter((p:string)=>["yookassa","rollypay","platega","sandbox"].includes(p))} currency={currency} api={API}/>
                </>}

                {activeItem?.kind === "info" && <><h2 className="section-title">{activeItem.title}</h2><InfoSection request={req} locale={lang} /></>}
                {activeItem?.kind === "surveys" && <Surveys request={req} reload={loadSession}/>}
                {activeItem?.kind === "giveaways" && <Giveaways request={req} reload={loadSession}/>}
                {activeItem?.kind === "custom" && (
                  <>
                    <h2 className="section-title">{activeItem.title || "Пользовательский раздел"}</h2>
                    <div className="custom-body" style={{whiteSpace: "pre-wrap"}}>{activeItem.body || ""}</div>
                  </>
                )}
                </SectionBoundary>
              </section>
            </main>

            <nav className="bottom-nav" aria-label="Основные разделы">
              {bottomItems.map((item) => (
                <button key={item.slug} type="button" aria-current={tab === item.slug ? "page" : undefined} className={tab === item.slug ? "active" : ""} onClick={() => go(item.slug)}>
                  {item.icon ? <ConfigIcon name={item.icon} /> : NAV_ICON[item.kind]}
                  <span>{item.title}</span>
                </button>
              ))}
              <button type="button" aria-expanded={drawerOpen} className={bottomItems.some((x) => x.slug === tab) ? "" : "active"} onClick={() => setDrawerOpen(true)}>
                <LayoutGrid aria-hidden="true" />
                <span>Ещё</span>
              </button>
            </nav>
          </div>
        )}

        {msg && <div className={`toast ${msgError ? "error" : ""}`} role={msgError ? "alert" : "status"}>{msg}</div>}
      </div>
    </DomLocalizer>
  );
}

export default function CabinetRoot() {
  return (
    <LangProvider>
      <AppConfigProvider>
        <App />
      </AppConfigProvider>
    </LangProvider>
  );
}
