"use client";
/** Family plans, the public service status and Telegram Stars subscriptions for the cabinet and Mini App. */
import React, {useEffect, useState} from "react";
import {useAppConfig} from "./app-config";
import {isTelegram, openAnyLink, openInvoice} from "./telegram";
import {StatusBadge} from "./ui";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Flash = (text: string, error?: boolean) => void;
const date = (v?: string | null) => (v ? new Date(v).toLocaleDateString() : "—");

/** Invitation code from ?family= (cabinet link) or the bot deep link start=family_<code>. */
export function familyCodeFromUrl(search = typeof location === "undefined" ? "" : location.search): string {
  const params = new URLSearchParams(search);
  const raw = params.get("family") || (params.get("tgWebAppStartParam") || params.get("startapp") || "").replace(/^family_/, "");
  return /^[A-Za-z0-9]{6,32}$/.test(raw) ? raw : "";
}

export function FamilySection({request, flash, reload}: {request: Request; flash: Flash; reload?: () => Promise<void> | void}) {
  const [data, setData] = useState<any>(null);
  const [code, setCode] = useState(familyCodeFromUrl());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    try { setData(await request("/api/me/family")); setError(""); } catch (e: any) { setError(e.message || "Не удалось загрузить семью"); }
  }
  useEffect(() => { load(); }, []);
  async function act(fn: () => Promise<any>, ok: string) {
    if (busy) return;
    setBusy(true);
    try { await fn(); flash(ok); await load(); await reload?.(); } catch (e: any) { flash(e.message || "Ошибка", true); } finally { setBusy(false); }
  }
  const post = (path: string, body?: any) => request(path, {method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});
  async function share(link: string) {
    try {
      if ((navigator as any).share) await (navigator as any).share({title: "Семейная подписка", url: link});
      else { await navigator.clipboard.writeText(link); flash("Ссылка скопирована"); }
    } catch { /* closed share sheet */ }
  }
  if (error) return <div className="workspace-alert error" role="alert">{error}<button className="btn-ghost" onClick={load}>Обновить</button></div>;
  if (!data) return <p role="status">Загрузка…</p>;
  return <div className="family-section">
    <h2 className="section-title">Семейная подписка</h2>
    <p className="section-sub">Пригласите близких: каждый получит свой VPN-ключ с тем же сроком, трафиком и устройствами, что у вашей подписки. Продлеваете вы — продлевается у всех.</p>
    {data.owned.length === 0 && data.member_of.length === 0 && <p className="section-sub">Семейные места есть в тарифах с пометкой «семья». Если вас пригласили, введите код ниже.</p>}
    {data.owned.map((g: any) => <article className="form-card family-card" key={g.subscription_id} data-family-owner={g.subscription_id}>
      <div className="family-head"><strong>{g.name || `Подписка №${g.subscription_id}`}</strong><span>{`Занято мест: ${g.used} из ${g.seats}`}</span></div>
      {g.invite ? <>
        <code className="family-code">{g.invite.code}</code>
        <div className="btn-row">
          {(g.invite.bot || g.invite.cabinet) && <button className="btn-primary" onClick={() => share(g.invite.bot || g.invite.cabinet)}>Отправить приглашение</button>}
          <button className="btn-ghost" disabled={busy} onClick={() => act(() => post(`/api/me/family/${g.subscription_id}/invite?rotate=1`), "Новый код создан, старый больше не работает")}>Сменить код</button>
        </div>
      </> : <button className="btn-primary" disabled={busy} onClick={() => act(() => post(`/api/me/family/${g.subscription_id}/invite`), "Приглашение создано")}>Создать приглашение</button>}
      {g.members.length > 0 && <ul className="family-members">{g.members.map((m: any) => <li key={m.id}>
        <span>{m.name || "Участник"}</span>
        <StatusBadge tone={m.error ? "danger" : m.synced ? "ok" : "warn"}>{m.error ? "Ошибка подключения" : m.synced ? "Подключён" : "Подключается"}</StatusBadge>
        <button className="btn-ghost" disabled={busy} onClick={() => confirm(`Убрать ${m.name || "участника"} из семьи? Его VPN отключится.`) && act(() => request(`/api/me/family/members/${m.id}`, {method: "DELETE"}), "Участник удалён")}>Убрать</button>
      </li>)}</ul>}
    </article>)}
    {data.member_of.map((m: any) => <article className="form-card family-card" key={m.id} data-family-member={m.id}>
      <div className="family-head"><strong>{`Вы в семье ${m.owner}`}</strong><span>{`Действует до ${date(m.expires_at)}`}</span></div>
      <p className="section-sub">Ключ подключения — в разделе «Подключение» (подписка «Семейная подписка»).</p>
      <button className="btn-ghost" disabled={busy} onClick={() => confirm("Выйти из семьи? VPN этой подписки отключится.") && act(() => request(`/api/me/family/members/${m.id}`, {method: "DELETE"}), "Вы вышли из семьи")}>Выйти из семьи</button>
    </article>)}
    <form className="workspace-form" onSubmit={(e) => { e.preventDefault(); act(() => post("/api/me/family/join", {code: code.trim()}), "Вы в семье! VPN-ключ появится в «Подключении»").then(() => setCode("")); }}>
      <label className="field">Код приглашения<input value={code} onChange={(e) => setCode(e.target.value)} maxLength={32} required placeholder="Например: aB3x9Kq2"/></label>
      <button className="btn-primary" disabled={busy || !code.trim()}>Присоединиться</button>
    </form>
  </div>;
}

const LEVEL: Record<string, [any, string]> = {ok: ["ok", "Все серверы работают"], degraded: ["warn", "Часть серверов недоступна"], down: ["danger", "Серверы недоступны"], unknown: ["warn", "Статус уточняется"]};

export function StatusSection({api, request}: {api: string; request?: Request}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState(false);
  const [sub, setSub] = useState<boolean | null>(null);
  useEffect(() => { if (request) request("/api/me/status/subscription").then((r: any) => setSub(!!r.subscribed)).catch(() => setSub(null)); }, [request]);
  async function toggle() {
    if (!request || sub === null) return;
    try { const r = await request("/api/me/status/subscription", {method: sub ? "DELETE" : "POST"}); setSub(!!r.subscribed); } catch { /* the button stays as it was */ }
  }
  async function load() {
    try { const r = await fetch(api + "/api/public/service-status", {headers: {Accept: "application/json"}}); if (!r.ok) throw Error(); setData(await r.json()); setError(false); } catch { setError(true); }
  }
  useEffect(() => { load(); const t = setInterval(load, 60000); return () => clearInterval(t); }, []);
  if (error && !data) return <div className="workspace-alert error" role="alert">Не удалось получить статус<button className="btn-ghost" onClick={load}>Повторить</button></div>;
  if (!data) return <p role="status">Загрузка…</p>;
  const [tone, label] = LEVEL[data.status] || LEVEL.unknown;
  return <div className="status-section" data-status={data.status}>
    <h2 className="section-title">Состояние сервиса</h2>
    <div className="form-card status-head"><StatusBadge tone={tone}>{label}</StatusBadge><span>{`Онлайн ${data.servers.online} из ${data.servers.total} · проверено ${new Date(data.checked_at + (String(data.checked_at).endsWith("Z") ? "" : "Z")).toLocaleTimeString()}`}</span></div>
    {(data.components || []).length > 0 && <div className="form-card">{data.components.map((c: any) => <p key={c.name}><StatusBadge tone={c.status === "operational" ? "ok" : c.status === "outage" ? "danger" : "warn"}>{c.name}</StatusBadge> {c.message}</p>)}</div>}
    {data.incidents.length > 0 && <div className="form-card"><h3>Известные проблемы</h3>{data.incidents.map((i: any, n: number) => <p key={n}><b>{i.title}</b> · с {date(i.since)}</p>)}</div>}
    <div className="status-countries">{data.countries.map((c: any) => <div className="status-country" key={c.country}>
      <span>{c.country}</span><StatusBadge tone={c.online === c.total ? "ok" : c.online ? "warn" : "danger"}>{`${c.online}/${c.total}`}</StatusBadge></div>)}</div>
    <div className="form-card status-subscribe">
      {request && sub !== null && <button type="button" className="btn-ghost" onClick={toggle}>{sub ? "🔕 Не сообщать о сбоях" : "🔔 Сообщать о сбоях и восстановлении"}</button>}
      <a className="btn-ghost" href={`${api}/status`} target="_blank" rel="noopener">Страница статуса</a>
    </div>
  </div>;
}

/** «Оплатить звёздами с автопродлением»: a monthly Telegram Stars subscription for a 30-day plan. */
export function StarsSubscribe({plans, request, flash, subscriptionId}: {plans: any[]; request: Request; flash: Flash; subscriptionId?: number | null}) {
  const {config} = useAppConfig();
  const [busy, setBusy] = useState(false);
  const [mine, setMine] = useState<any[]>([]);
  const stars = config.wallet?.stars;
  const monthly = plans.filter((p) => Number(p.duration_days) === 30);
  const load = () => request("/api/me/stars-subscriptions").then(setMine).catch(() => setMine([]));
  useEffect(() => { if (stars?.enabled && stars?.subscriptions) load(); }, [stars?.enabled, stars?.subscriptions]);
  if (!stars?.enabled || !stars?.subscriptions || !isTelegram() || monthly.length === 0) return null;
  const rate = Number(stars.rate || 1);
  async function subscribe(plan: any) {
    if (busy) return;
    setBusy(true);
    try {
      const r = await request("/api/me/stars-subscriptions", {method: "POST", body: JSON.stringify({plan_id: plan.id, ...(subscriptionId ? {subscription_id: subscriptionId} : {})})});
      const status = await openInvoice(r.url);
      if (status === "paid") { flash("Подписка Stars оформлена: продление каждые 30 дней"); setTimeout(load, 2500); }
      else if (status === "unsupported") openAnyLink(r.url);
      else if (status === "failed") flash("Оплата Stars не прошла", true);
    } catch (e: any) { flash(e.message || "Ошибка", true); } finally { setBusy(false); }
  }
  async function cancel(row: any) {
    if (!confirm("Отменить продление за Stars? Подписка доработает до конца оплаченного месяца.")) return;
    try { await request(`/api/me/stars-subscriptions/${row.id}/cancel`, {method: "POST"}); flash("Продление за Stars отменено"); load(); } catch (e: any) { flash(e.message || "Ошибка", true); }
  }
  return <div className="form-card stars-subscribe">
    <h3>⭐ Автопродление за Telegram Stars</h3>
    <p className="section-sub">Telegram списывает звёзды раз в 30 дней, отменить можно в любой момент здесь или в настройках Telegram.</p>
    <div className="btn-row">{monthly.map((p) => <button key={p.id} className="btn-primary" disabled={busy} onClick={() => subscribe(p)}>
      {`${p.name} · ⭐ ${Math.ceil(Number(p.price) / rate)} в месяц`}</button>)}</div>
    {mine.filter((m) => m.status === "active").map((m) => <p key={m.id} className="section-sub">
      {`${m.plan || "Подписка"}: ⭐ ${m.stars} в месяц · продлений ${m.renewals}`} <button className="btn-ghost" onClick={() => cancel(m)}>Отменить продление</button></p>)}
  </div>;
}
