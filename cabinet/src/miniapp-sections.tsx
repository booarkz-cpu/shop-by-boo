"use client";
/** Mini App sections rendered from the app config (see app-config.tsx). */
import React, {useEffect, useMemo, useRef, useState} from "react";
import {Bell, CircleHelp, Clock, Copy, CreditCard, FileText, Flag, Gift, Globe2, Heart, Home, Info, KeyRound, LayoutList, Lock, Mail,
  MessageCircle, Phone, Plug, Receipt, RefreshCw, Rocket, Send, Server, Shield, Smartphone, Sparkles, Star, Trophy, Users, Wallet, WifiOff, Zap,
  Bitcoin, QrCode} from "lucide-react";
import {assetUrl, bundledBanner, useAppConfig, useText, type InfoPage} from "./app-config";
import {ContentBlocks} from "./public-pages";
import {StickerState} from "./stickers";
import {Skeleton, StatusBadge} from "./ui";
import {haptic, isTelegram, openAnyLink, openExternal, openInvoice, telegramFirstName} from "./telegram";

type Request = (path: string, options?: RequestInit) => Promise<any>;

const ICONS: Record<string, React.ComponentType<any>> = {
  home: Home, zap: Zap, shield: Shield, server: Server, wallet: Wallet, users: Users, gift: Gift, help: CircleHelp, message: MessageCircle,
  send: Send, phone: Phone, mail: Mail, card: CreditCard, sbp: QrCode, crypto: Bitcoin, star: Star, globe: Globe2, flag: Flag, info: Info,
  file: FileText, lock: Lock, list: LayoutList, trophy: Trophy, smartphone: Smartphone, plug: Plug, receipt: Receipt, bell: Bell, key: KeyRound,
  sparkles: Sparkles, rocket: Rocket, heart: Heart, clock: Clock,
};

export function ConfigIcon({name, className}: {name: string; className?: string}) {
  const Cmp = ICONS[name] || FileText;
  return <Cmp aria-hidden="true" className={className} />;
}

/** Section header image (corgi Lusi by default, replaceable in the admin panel). */
export function SectionBanner({kind, title}: {kind: string; title: string}) {
  const {config} = useAppConfig();
  const primary = assetUrl(config.banners?.[kind] || "");
  const fallback = bundledBanner(config, kind);
  const [src, setSrc] = useState(primary || fallback);
  useEffect(() => setSrc(primary || fallback), [primary, fallback]);
  if (!src) return null;
  return (
    <figure className="section-banner">
      <img src={src} alt={title} loading="lazy" onError={() => { if (src !== fallback && fallback) setSrc(fallback); else setSrc(""); }} />
    </figure>
  );
}

export function ConfigNotice() {
  const {status, reload} = useAppConfig();
  const t = useText();
  if (status !== "offline") return null;
  return (
    <div className="config-notice" role="status">
      <WifiOff aria-hidden="true" />
      <span>{t("offline")}</span>
      <button type="button" className="btn-ghost" onClick={reload}><RefreshCw aria-hidden="true" />{t("retry")}</button>
    </div>
  );
}

export function ConfigSkeleton() {
  return (
    <div className="boot" role="status" aria-label="Загрузка…">
      <div className="boot-bar"><Skeleton className="sk-brand" /><Skeleton className="sk-pill" /></div>
      <div className="boot-body">
        <Skeleton className="sk-banner" />
        <Skeleton className="sk-hero" />
        <div className="boot-tiles"><Skeleton className="sk-tile" /><Skeleton className="sk-tile" /><Skeleton className="sk-tile" /></div>
        <Skeleton className="sk-card" />
      </div>
    </div>
  );
}

export function Greeting({fallbackName}: {fallbackName?: string}) {
  const {config} = useAppConfig();
  const t = useText();
  const name = config.viewer?.first_name || telegramFirstName() || fallbackName || "";
  return (
    <header className="greeting">
      <h1>{name ? t("greeting", {name}) : t("greeting_anonymous")}</h1>
      <p>{t("home_subtitle")}</p>
    </header>
  );
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

export function countdown(ends: string | null | undefined, now: number): string {
  if (!ends) return "";
  const left = Math.floor((Date.parse(ends) - now) / 1000);
  if (!Number.isFinite(left) || left <= 0) return "";
  const d = Math.floor(left / 86400), h = Math.floor((left % 86400) / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
  return d > 0 ? `${d}д ${h}ч ${m}м` : `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Follows a config link: #section inside the app, https/tg links through Telegram. */
export function followLink(link: string, go: (slug: string) => void) {
  if (!link) return;
  if (link.startsWith("#")) { go(link.slice(1) || "overview"); return; }
  if (/^(https:|tg:)/.test(link)) openAnyLink(link);
}

export function PromoCards({go}: {go: (slug: string) => void}) {
  const {config} = useAppConfig();
  const t = useText();
  const promos = config.promos || [];
  const now = useNow(promos.some((p) => p.ends_at));
  const visible = promos.filter((p) => !p.ends_at || Date.parse(p.ends_at) > now);
  if (!visible.length) return null;
  return (
    <section className="promo-strip" aria-label={t("promo_title")}>
      <h2 className="section-title section-title-sm">{t("promo_title")}</h2>
      <div className="promo-cards">
        {visible.map((p) => {
          const left = countdown(p.ends_at, now);
          return (
            <article className={`promo-card${p.image ? " has-image" : ""}`} key={p.id} data-promo={p.id}>
              {p.image && <img className="promo-image" src={assetUrl(p.image)} alt="" loading="lazy" />}
              {p.discount && <span className="promo-discount">{p.discount}</span>}
              <h3>{p.title}</h3>
              {p.text && <p>{p.text}</p>}
              {left && <p className="promo-timer"><Clock aria-hidden="true" />{t("promo_ends_in")}: <b>{left}</b></p>}
              {p.button_text && p.link && <button type="button" className="btn-primary" onClick={() => followLink(p.link, go)}>{p.button_text}</button>}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function flagEmoji(country?: string): string {
  const code = (country || "").trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) return "🌐";
  return String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

export function groupServers(nodes: any[], categories: {id: string; title: string; icon: string; countries: string[]; match: string[]}[]) {
  const groups = categories.map((c) => ({...c, nodes: [] as any[]}));
  const other = {id: "other", title: categories.length ? "Другие" : "Все серверы", icon: "globe", countries: [], match: [], nodes: [] as any[]};
  for (const node of nodes) {
    const country = String(node.country || "").toUpperCase();
    const name = String(node.name || "").toLowerCase();
    const group = groups.find((g) => g.countries.includes(country) || g.match.some((w) => w && name.includes(w.toLowerCase())));
    (group || other).nodes.push(node);
  }
  return [...groups, other].filter((g) => g.nodes.length);
}

export function ServerCatalog({servers}: {servers: any}) {
  const {config} = useAppConfig();
  const t = useText();
  const nodes = servers?.nodes || [];
  const groups = useMemo(() => groupServers(nodes, config.servers?.categories || []), [nodes, config.servers]);
  if (!nodes.length) return <p className="section-sub">{servers?.error || t("servers_empty")}</p>;
  return (
    <div className="server-catalog">
      <p className="section-sub">Онлайн {servers?.online ?? 0} из {servers?.total ?? nodes.length}</p>
      {groups.map((g) => (
        <section className="server-group" key={g.id} data-category={g.id}>
          <h3><ConfigIcon name={g.icon} />{g.title}<span className="muted"> · {g.nodes.length}</span></h3>
          <div className="plan-list">
            {g.nodes.map((node: any, i: number) => (
              <article className="plan-item server-item" key={`${node.name}-${i}`}>
                <div className="server-name"><span className="server-flag" aria-hidden="true">{flagEmoji(node.country)}</span>
                  <div><h4>{node.name}</h4><p className="section-sub">{node.country || "—"}{config.servers?.show_load && typeof node.users_online === "number" ? ` · ${node.users_online} онлайн` : ""}</p></div>
                </div>
                <StatusBadge tone={node.status === "online" ? "ok" : node.status === "offline" ? "danger" : "idle"}>{node.status === "online" ? "Онлайн" : node.status === "offline" ? "Офлайн" : "Неизвестно"}</StatusBadge>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** Offer consent card; resolves once the customer accepted the current version. */
export function ConsentGate({request, force = false, onAccepted}: {request: Request; force?: boolean; onAccepted?: () => void}) {
  const {config} = useAppConfig();
  const t = useText();
  const consent = config.consent;
  const [accepted, setAccepted] = useState<boolean | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!consent?.enabled) return;
    let live = true;
    request("/api/me/consent").then((r) => live && setAccepted(Boolean(r.accepted) && r.version === consent.version)).catch(() => live && setAccepted(false));
    return () => { live = false; };
  }, [consent?.enabled, consent?.version, request, force]);
  if (!consent?.enabled || accepted === true || (accepted === null && !force)) return null;
  async function accept() {
    setBusy(true); setError("");
    try {
      await request("/api/me/consent", {method: "POST", body: JSON.stringify({version: consent.version, source: isTelegram() ? "miniapp" : "cabinet"})});
      setAccepted(true); haptic.notify("success"); onAccepted?.();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  return (
    <section className="form-card consent-card" aria-label={t("consent_title")}>
      <h3><Lock aria-hidden="true" />{t("consent_title")}</h3>
      <label className="consent-check">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        <span>{consent.text} · <a href={`#page/${consent.page_slug}`}>Открыть оферту</a></span>
      </label>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="button" className="btn-primary" disabled={!checked || busy} onClick={accept}>{t("consent_accept")}</button>
    </section>
  );
}

export function WalletTopup({request, balance, reload, flash, onConsentRequired}: {request: Request; balance: string; reload: () => Promise<void> | void; flash: (text: string, error?: boolean) => void; onConsentRequired: () => void}) {
  const {config} = useAppConfig();
  const t = useText();
  const wallet = config.wallet;
  const methods = (wallet.methods || []).filter((m) => m.available);
  const [amount, setAmount] = useState(String(wallet.amounts?.[2] ?? wallet.amounts?.[0] ?? 500));
  const [method, setMethod] = useState(methods[0]?.id || "");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const keys = useRef<Record<string, string>>({});
  useEffect(() => { if (!methods.some((m) => m.id === method)) setMethod(methods[0]?.id || ""); }, [methods.map((m) => m.id).join(","), method]);
  const selected = methods.find((m) => m.id === method);
  const value = Number(amount);
  const valid = Number.isFinite(value) && value >= wallet.min && value <= wallet.max;
  const stars = selected?.provider === "telegram_stars" && valid ? Math.ceil(value / Number(wallet.stars.rate || 1)) : 0;

  function keyFor(body: unknown) {
    const fp = JSON.stringify(body);
    keys.current[fp] ??= crypto.randomUUID();
    return [fp, keys.current[fp]] as const;
  }
  async function pay() {
    if (!selected || !valid || busy) return;
    setBusy(true);
    try {
      if (selected.provider === "telegram_stars") {
        const body = {amount: value};
        const [fp, key] = keyFor({...body, m: "stars"});
        const invoice = await request("/api/me/wallet/stars-invoice", {method: "POST", headers: {"Idempotency-Key": key}, body: JSON.stringify(body)});
        delete keys.current[fp];
        const status = await openInvoice(invoice.url);
        if (status === "paid") { flash("Оплата Stars получена, баланс пополнится через несколько секунд"); setTimeout(() => reload(), 2500); }
        else if (status === "unsupported") openAnyLink(invoice.url);
        else if (status === "failed") flash("Оплата Stars не прошла", true);
      } else {
        const body = {amount: value, provider: selected.provider, ...(selected.yookassa_method ? {method: selected.yookassa_method} : {})};
        const [fp, key] = keyFor(body);
        const r = await request("/api/me/wallet/topup", {method: "POST", headers: {"Idempotency-Key": key}, body: JSON.stringify(body)});
        delete keys.current[fp];
        if (r.url) {
          const target = new URL(r.url, location.origin);
          if (target.protocol !== "https:" && target.origin !== location.origin) throw Error("Некорректная ссылка оплаты");
          if (isTelegram() && target.origin !== location.origin) openExternal(target.href); else location.assign(target.href);
        } else { flash("Платёж создан"); await reload(); }
      }
    } catch (e: any) {
      if (e?.detail?.code === "consent_required") onConsentRequired();
      flash(e.message || "Ошибка", true);
    } finally { setBusy(false); }
  }
  async function redeem(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    try { await request("/api/me/payment/gift-card/redeem", {method: "POST", body: JSON.stringify({code: code.trim()})}); setCode(""); flash("Код активирован"); await reload(); }
    catch (err: any) { flash(err.message || "Ошибка", true); } finally { setBusy(false); }
  }
  return (
    <section className="wallet-topup">
      <div className="workspace-balance"><span>{t("wallet_balance")}</span><strong>{balance} {wallet.currency}</strong></div>
      <h3>{t("wallet_amount")}</h3>
      <div className="amount-chips" role="group" aria-label={t("wallet_amount")}>
        {(wallet.amounts || []).map((a) => (
          <button type="button" key={a} className={`chip ${Number(amount) === a ? "active" : ""}`} aria-pressed={Number(amount) === a} onClick={() => { setAmount(String(a)); haptic.select(); }}>{a} {wallet.currency}</button>
        ))}
      </div>
      <label className="field">Другая сумма<input type="number" inputMode="decimal" min={wallet.min} max={wallet.max} step="1" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
      <h3>{t("wallet_method")}</h3>
      {!methods.length && <p className="section-sub">Способы оплаты временно недоступны</p>}
      <div className="method-list" role="radiogroup" aria-label={t("wallet_method")}>
        {methods.map((m) => (
          <button type="button" role="radio" aria-checked={m.id === method} key={m.id} data-method={m.id} className={`method ${m.id === method ? "active" : ""}`} onClick={() => { setMethod(m.id); haptic.select(); }}>
            <ConfigIcon name={m.icon} /><span>{m.title}</span>
          </button>
        ))}
      </div>
      {stars > 0 && <p className="section-sub">К оплате: ⭐ {stars} Stars</p>}
      <button type="button" className="btn-primary" disabled={!selected || !valid || busy} onClick={pay}>{t("wallet_pay")}{valid ? ` · ${value} ${wallet.currency}` : ""}</button>
      <form className="workspace-form" onSubmit={redeem}>
        <label className="field">{t("wallet_code")}<input value={code} maxLength={128} onChange={(e) => setCode(e.target.value)} /></label>
        <button className="btn-ghost" disabled={busy || !code.trim()}>{t("wallet_code_apply")}</button>
      </form>
    </section>
  );
}

export function referralLink(template: string, code: string) {
  return template && code ? template.split("{code}").join(encodeURIComponent(code)) : "";
}

export function ReferralTerms({code, flash}: {code: string; flash: (text: string, error?: boolean) => void}) {
  const {config} = useAppConfig();
  const t = useText();
  const link = referralLink(config.referral?.link_template || "", code);
  const levels = (config.referral?.levels || []).filter((x) => Number(x) > 0);
  async function copy() {
    try { await navigator.clipboard.writeText(link); flash("Скопировано"); } catch { flash("Не удалось скопировать", true); }
  }
  return (
    <section className="form-card referral-terms">
      <p style={{whiteSpace: "pre-wrap"}}>{config.referral?.conditions}</p>
      {levels.length > 0 && <p className="section-sub">Вознаграждение по уровням: {levels.map((x) => `${Number(x)}%`).join(" / ")}</p>}
      {link && <>
        <h3>{t("referral_link")}</h3>
        <code className="referral-link">{link}</code>
        <div className="btn-row">
          <button type="button" className="btn-primary" onClick={copy}><Copy aria-hidden="true" />{t("referral_copy")}</button>
          {isTelegram() && <button type="button" className="btn-ghost" onClick={() => openAnyLink(`https://t.me/share/url?url=${encodeURIComponent(link)}`)}><Send aria-hidden="true" />Поделиться</button>}
        </div>
      </>}
    </section>
  );
}

export function SupportButtons({go}: {go: (slug: string) => void}) {
  const {config} = useAppConfig();
  const t = useText();
  const buttons = config.support?.buttons || [];
  if (!buttons.length) return null;
  return (
    <section className="support-buttons" aria-label={t("support_subtitle")}>
      <p className="section-sub">{t("support_subtitle")}</p>
      <div className="method-list">
        {buttons.map((b, i) => (
          <button type="button" key={`${b.title}-${i}`} className="method" onClick={() => followLink(b.link, go)}><ConfigIcon name={b.icon} /><span>{b.title}</span></button>
        ))}
      </div>
    </section>
  );
}

const INFO_ICON: Record<string, string> = {faq: "help", rules: "list", privacy: "lock", offer: "file", other: "info"};

/** Inline **bold** and https links of a document written in «Документы». */
function Inline({text}: {text: string}) {
  const parts = text.split(/(\*\*[^*]+\*\*|https:\/\/[^\s)]+)/g);
  return <>{parts.map((part, i) => part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <b key={i}>{part.slice(2, -2)}</b>
    : part.startsWith("https://") ? <a key={i} href={part} target="_blank" rel="noreferrer noopener">{part}</a> : <React.Fragment key={i}>{part}</React.Fragment>)}</>;
}

/** Renders the small document format: "## " headings, "- " lists, paragraphs, FAQ items. */
export function DocText({page}: {page: {body?: string; items?: {question: string; answer: string}[]}}) {
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) { blocks.push(<p key={`p${blocks.length}`}>{para.map((l, i) => <React.Fragment key={i}>{i > 0 && <br />}<Inline text={l} /></React.Fragment>)}</p>); para = []; }
    if (list.length) { blocks.push(<ul key={`l${blocks.length}`}>{list.map((l, i) => <li key={i}><Inline text={l} /></li>)}</ul>); list = []; }
  };
  for (const raw of (page.body || "").split("\n")) {
    const line = raw.trimEnd();
    if (line.startsWith("## ")) { flush(); blocks.push(<h3 key={`h${blocks.length}`}>{line.slice(3)}</h3>); }
    else if (/^[-*] /.test(line)) { if (para.length) { const keep = list; list = []; flush(); list = keep; } list.push(line.slice(2)); }
    else if (!line.trim()) flush();
    else { if (list.length) { const keep = para; para = []; flush(); para = keep; } para.push(line); }
  }
  flush();
  return <div className="doc-text">
    {blocks}
    {(page.items || []).length > 0 && <div className="faq-list">{page.items!.map((item, i) => <details key={i} className="faq-item"><summary>{item.question}</summary><p><Inline text={item.answer} /></p></details>)}</div>}
  </div>;
}

export function InfoSection({request, locale}: {request: Request; locale: string}) {
  const {config} = useAppConfig();
  const pages: InfoPage[] = config.info?.pages || [];
  const [open, setOpen] = useState<InfoPage | null>(null);
  const [page, setPage] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let live = true;
    setPage(null); setError("");
    const url = open.source === "info"
      ? `/api/public/info-pages/${encodeURIComponent(open.kind)}?lang=${["en", "uk"].includes(locale) ? locale : "ru"}`
      : `/api/public/pages/${encodeURIComponent(open.slug)}?locale=${locale === "en" ? "en" : "ru"}`;
    request(url)
      .then((p) => live && setPage(p)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [open, locale, request]);
  const top = React.useRef<HTMLElement>(null);
  // The document's own banner replaces the «Информация» one at the top of the screen.
  useEffect(() => { if (page && open?.source === "info") top.current?.scrollIntoView?.({block: "start"}); }, [page, open]);
  if (open) return (
    <article className="info-page" ref={top}>
      <button type="button" className="btn-link" onClick={() => setOpen(null)}>← Все документы</button>
      {error && <p role="alert" className="error">{error}</p>}
      {!page && !error && <Skeleton className="sk-card" />}
      {page && open.source === "info" && <><SectionBanner kind={open.kind} title={page.title} /><h2 className="section-title">{page.title}</h2><DocText page={page} /></>}
      {page && open.source !== "info" && <><h2 className="section-title">{page.title}</h2>{page.summary && <p className="section-sub">{page.summary}</p>}<ContentBlocks blocks={page.blocks || []} /></>}
    </article>
  );
  return (
    <div className="method-list info-list">
      {!pages.length && <p className="section-sub">Документы пока не опубликованы</p>}
      {pages.map((p) => (
        <button type="button" key={p.slug} className="method" data-info={p.kind} onClick={() => setOpen(p)}><ConfigIcon name={INFO_ICON[p.kind] || "info"} /><span>{p.title}</span></button>
      ))}
    </div>
  );
}

/** Keeps the rest of the Mini App usable when one section fails to render. */
export class SectionBoundary extends React.Component<{children: React.ReactNode; resetKey: string}, {failed: boolean}> {
  state = {failed: false};
  static getDerivedStateFromError() { return {failed: true}; }
  componentDidUpdate(prev: {resetKey: string}) { if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({failed: false}); }
  componentDidCatch(error: unknown) { console.error("section render failed", error); }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <StickerState sticker="bugs" tone="error" title="Раздел не открылся" text="Люси уже ловит ошибку. Попробуйте ещё раз — остальные разделы работают.">
        <button type="button" className="btn-ghost" onClick={() => this.setState({failed: false})}><RefreshCw aria-hidden="true" />Повторить</button>
      </StickerState>
    );
  }
}
