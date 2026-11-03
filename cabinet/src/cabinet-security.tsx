import React, {useEffect, useState} from "react";
import {StatusBadge} from "./ui";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
const when = (v?: string | null) => (v ? new Date(v.endsWith("Z") || v.includes("+") ? v : v + "Z").toLocaleString() : "—");

/** «Устройства»: devices the VPN panel counts against the subscription limit (HWID), v28.63.0.
 *  The limit itself is enforced by Remnawave; here the customer sees it and frees a slot. */
export function HwidDevices({request}: {request: RequestFn}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const load = () => {
    setError("");
    request("/api/me/hwid-devices").then(setData).catch((e: any) => { setData(null); setError(e.message || "Не удалось загрузить устройства"); });
  };
  useEffect(load, []);
  async function act(path: string, ask: string, key: string) {
    if (!window.confirm(ask)) return;
    setBusy(key);
    try { await request(path, {method: "POST"}); load(); } catch (e: any) { setError(e.message || "Не удалось выполнить"); } finally { setBusy(""); }
  }
  if (error && !data) return <div className="form-card stack" data-hwid-devices="error"><h3>Устройства подписки</h3><p className="section-sub" role="alert">{error}</p><button type="button" className="btn-ghost" onClick={load}>Повторить</button></div>;
  if (!data) return <div className="form-card stack" data-hwid-devices="loading"><h3>Устройства подписки</h3><p className="section-sub">Загрузка…</p></div>;
  if (data.subscription === false) return <div className="form-card stack" data-hwid-devices="none"><h3>Устройства подписки</h3><p className="section-sub">Устройства появятся после покупки подписки и первого подключения к VPN.</p></div>;
  const devices: any[] = data.devices || [];
  return <div className="form-card stack" data-hwid-devices="ready">
    <h3>Устройства подписки</h3>
    <p className="section-sub">{data.limit ? `Подключено ${data.used} из ${data.limit}. ` : `Подключено устройств: ${data.used}. `}
      Новое устройство не подключится, если места заняты: удалите старое — его место освободится сразу.</p>
    {error && <p className="section-sub" role="alert">{error}</p>}
    {!devices.length && <p className="section-sub">Устройств пока нет: они появятся после первого подключения к VPN.</p>}
    {devices.map(d => <article className="plan-item" key={d.id} data-device={d.id}>
      <div><h3>{[d.platform, d.model].filter(Boolean).join(" · ") || "Устройство"}</h3>
        <p className="section-sub">{d.os_version ? `${d.os_version} · ` : ""}впервые {when(d.created_at)}, последнее подключение {when(d.updated_at)}</p></div>
      <button type="button" className="btn-ghost" disabled={!!busy} onClick={() => act(`/api/me/hwid-devices/${d.id}/delete`, "Удалить устройство? Оно потеряет доступ, пока не подключится снова.", d.id)}>
        {busy === d.id ? "Удаляем…" : "Удалить"}</button>
    </article>)}
    {devices.length > 1 && <button type="button" className="btn-ghost" disabled={!!busy} onClick={() => act("/api/me/hwid-devices/reset", "Удалить все устройства? Каждому придётся подключиться заново.", "all")}>
      {busy === "all" ? "Удаляем…" : "Удалить все устройства"}</button>}
  </div>;
}

/** «Сменить ссылку подписки» (v28.67.0): for a link that leaked — the VPN panel issues a new one, the old one stops
 *  working. Once per 10 minutes (the server enforces it). */
export function ResetSubscriptionLink({request}: {request: RequestFn}) {
  const [state, setState] = useState<{busy?: boolean; error?: string; url?: string}>({});
  async function reset() {
    if (!window.confirm("Сменить ссылку подписки? Старая перестанет работать: в VPN-приложении подписку нужно будет добавить заново.")) return;
    setState({busy: true});
    try { const out = await request("/api/me/subscription/reset-link", {method: "POST"}); setState({url: out.subscription_url}); }
    catch (e: any) { setState({error: e.message || "Не удалось сменить ссылку"}); }
  }
  return <div className="form-card stack" data-reset-subscription-link>
    <h3>Ссылка подписки</h3>
    <p className="section-sub">Если ссылкой мог воспользоваться кто-то другой, замените её: старая сразу перестанет работать.</p>
    {state.error && <p className="section-sub" role="alert">{state.error}</p>}
    {state.url && <p className="section-sub" role="status">Новая ссылка: <code>{state.url}</code>. Добавьте её в VPN-приложение заново.</p>}
    <button type="button" className="btn-ghost" disabled={state.busy} onClick={reset}>{state.busy ? "Меняем…" : "Сменить ссылку подписки"}</button>
  </div>;
}

/** «Безопасность»: every sign-in with its own «Завершить», the current one marked (v28.63.0). */
export function SessionsList({request, onCurrentRevoked}: {request: RequestFn; onCurrentRevoked: () => void}) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const load = () => { setError(""); request("/api/me/sessions").then(setRows).catch((e: any) => setError(e.message || "Не удалось загрузить сессии")); };
  useEffect(load, []);
  async function revoke(row: any) {
    if (!window.confirm(row.current ? "Завершить текущую сессию? Нужно будет войти снова." : "Завершить эту сессию?")) return;
    try {
      const out = await request(`/api/me/sessions/${row.id}/revoke`, {method: "POST"});
      if (out?.current) onCurrentRevoked(); else load();
    } catch (e: any) { setError(e.message || "Не удалось завершить сессию"); }
  }
  if (error && !rows) return <div data-sessions="error"><p className="section-sub" role="alert">{error}</p><button className="btn-ghost" onClick={load}>Повторить</button></div>;
  if (!rows) return <p className="section-sub">Загрузка…</p>;
  const active = rows.filter(r => r.active);
  return <div data-sessions="ready">
    <h3>Входы в кабинет и приложения</h3>
    {error && <p className="section-sub" role="alert">{error}</p>}
    {!active.length && <p className="section-sub">Активных сессий нет.</p>}
    {active.map(r => <article className="workspace-record" key={r.id} data-session={r.id}>
      <div><strong>{(r.user_agent || "Неизвестное устройство").slice(0, 80)}</strong>
        <p>IP {r.ip || "—"} · вход {when(r.created_at)} · активность {when(r.last_seen_at)}</p>
        {r.current && <StatusBadge tone="ok">Эта сессия</StatusBadge>}</div>
      <button className="btn-ghost" onClick={() => revoke(r)}>Завершить</button>
    </article>)}
  </div>;
}

/** The free trial: Lucy Mini when the owner configured a trial plan, otherwise null (any plan on sale). */
export function useTrialPlan(request: RequestFn) {
  const [plan, setPlan] = useState<any>(undefined);
  useEffect(() => { request("/api/public/trial").then(x => setPlan(x?.plan || null)).catch(() => setPlan(null)); }, []);
  return plan;
}
