import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

const KIND: Record<string, string> = {broadcast: "Рассылка", winback: "Возврат клиентов", retention: "Удержание", promotion: "Акция"};
const STATUS: Record<string, string> = {draft: "черновик", scheduled: "запланирована", running: "отправляется", paused: "приостановлена", completed: "завершена"};
const when = (v?: string | null) => v ? new Date(v).toLocaleString() : "—";

/** Automation: rules "event → conditions → actions" that the worker executes, and scheduled campaigns. */
export function Automation({data, request, reload, toast}: {data: any; request: Request; reload: () => void; toast: (m: string) => void}) {
  const [catalog, setCatalog] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/automation/catalog").then(setCatalog).catch((e: any) => setError(e.message)); }, [request]);
  if (!catalog) return <div className="card">{error ? <div role="alert" className="error">{error}</div> : <p className="muted">Загрузка…</p>}</div>;
  return <div className="grid2">
    <Rules rules={data?.rules || []} catalog={catalog} request={request} reload={reload} toast={toast}/>
    <Campaigns campaigns={data?.campaigns || []} catalog={catalog} request={request} reload={reload} toast={toast}/>
  </div>;
}

function summary(rule: any, catalog: any) {
  const ev = catalog.events.find((e: any) => e.id === rule.event);
  const c = rule.conditions || {};
  const parts = [ev ? ev.label : rule.event];
  if (c.days !== undefined) parts.push(`${c.days} дн.`);
  if (c.plan_ids?.length) parts.push(`тарифы ${c.plan_ids.join(", ")}`);
  if (c.min_amount) parts.push(`от ${c.min_amount}`);
  if (c.max_amount) parts.push(`до ${c.max_amount}`);
  const a = rule.actions || {};
  const acts = [a.notify ? (a.notify.telegram ? "уведомление + Telegram" : "уведомление") : null, a.wallet_bonus ? `бонус ${a.wallet_bonus.amount}` : null,
    a.promo_code ? `промокод −${a.promo_code.percent}% на ${a.promo_code.days} дн.` : null].filter(Boolean);
  return `${parts.join(" · ")} → ${acts.join(", ") || "нет действий"}`;
}

function Rules({rules, catalog, request, reload, toast}: any) {
  const blank = {name: "", event: "subscription.expiring", days: "", plan_ids: "", min_amount: "", max_amount: "", daily_limit: "500",
    notify: true, title: "", body: "", telegram: true, bonus: "", promo_percent: "", promo_days: "2"};
  const [f, setF] = useState<any>(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<Record<number, number>>({});
  const ev = catalog.events.find((e: any) => e.id === f.event);
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});

  async function create(e: React.FormEvent) {
    e.preventDefault(); if (busy) return; setBusy(true); setError("");
    const conditions: any = {daily_limit: Number(f.daily_limit || 500)};
    if (ev?.days && f.days !== "") conditions.days = Number(f.days);
    if (f.plan_ids.trim()) conditions.plan_ids = f.plan_ids.split(",").map((x: string) => Number(x.trim())).filter(Boolean);
    if (f.event === "payment.paid") { if (f.min_amount) conditions.min_amount = f.min_amount; if (f.max_amount) conditions.max_amount = f.max_amount; }
    const actions: any = {};
    if (f.notify) actions.notify = {title: f.title, body: f.body, telegram: f.telegram};
    if (f.bonus) actions.wallet_bonus = {amount: f.bonus};
    if (f.promo_percent) actions.promo_code = {percent: Number(f.promo_percent), days: Number(f.promo_days || 2)};
    try {
      await request("/api/admin/enterprise/rules", {method: "POST", body: JSON.stringify({name: f.name, event: f.event, conditions, actions, enabled: false, priority: 100})});
      toast("Правило создано выключенным: проверьте и включите"); setF(blank); reload();
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function toggle(rule: any, enabled: boolean) {
    try { await request(`/api/admin/v3/automation/${rule.id}/toggle`, {method: "POST", body: JSON.stringify({enabled})}); toast(enabled ? "Правило включено" : "Правило выключено"); reload(); }
    catch (err: any) { setError(err.message); }
  }
  async function check(rule: any) {
    try { const r = await request(`/api/admin/automation/rules/${rule.id}/preview`); setPending({...pending, [rule.id]: r.pending}); }
    catch (err: any) { setError(err.message); }
  }
  async function preset(id: string) {
    if (busy) return; setBusy(true); setError("");
    try { await request(`/api/admin/automation/presets/${id}`, {method: "POST"}); toast("Готовый сценарий добавлен выключенным: проверьте текст и включите"); reload(); }
    catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function remove(rule: any) {
    try { await request(`/api/admin/automation/rules/${rule.id}`, {method: "DELETE"}); toast("Правило удалено"); reload(); }
    catch (err: any) { setError(err.message); }
  }

  return <div className="card">
    <h3>Правила автоматизации</h3>
    <p className="muted">Включённые правила выполняются фоновым процессом каждые {Math.round(catalog.tick_seconds / 60)} минут. Каждое действие выполняется один раз для каждого клиента и события; клиенты, подходившие до создания правила, не затрагиваются. В тексте можно использовать {catalog.placeholders.join(", ")}.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {(catalog.presets || []).length > 0 && <div className="automation-presets">
      <h4>Готовые сценарии</h4>
      <p className="muted">Возврат ушедших клиентов, пробный период без покупки, напоминание о продлении, трафик на исходе. Сценарий создаётся выключенным; промокод в нём одноразовый и личный.</p>
      {catalog.presets.map((p: any) => <div className="automation-row" key={p.id} data-preset={p.id}>
        <div><b>{p.name}</b><span className="muted">{p.body}</span></div>
        <button disabled={busy} onClick={() => preset(p.id)}>{`Добавить сценарий «${p.name}»`}</button>
      </div>)}
    </div>}
    {rules.length === 0 && <p className="muted">Правил пока нет.</p>}
    {rules.map((r: any) => <div className="automation-row" key={r.id} data-rule-id={r.id}>
      <div><b>{r.name}</b><span>{summary(r, catalog)}</span><span className="muted">Выполнено: {r.run_count} · последний запуск {when(r.last_run_at)}{pending[r.id] !== undefined ? ` · ожидают: ${pending[r.id]}` : ""}</span></div>
      <div className="inline">
        <label className="inline"><input type="checkbox" checked={!!r.enabled} onChange={e => toggle(r, e.target.checked)}/>Включено</label>
        <button onClick={() => check(r)}>Проверить</button>
        <button className="danger" onClick={() => remove(r)}>Удалить</button>
      </div>
    </div>)}
    <h4>Новое правило</h4>
    <form onSubmit={create} className="plan-form">
      <label className="field">Название правила<input required maxLength={255} value={f.name} onChange={set("name")}/></label>
      <label className="field">Событие<select value={f.event} onChange={set("event")}>{catalog.events.map((e: any) => <option key={e.id} value={e.id}>{e.label}</option>)}</select></label>
      {ev && <p className="muted">{ev.hint}</p>}
      {ev?.days && <label className="field">{`Дни (по умолчанию ${ev.days[0]})`}<input type="number" min={ev.days[1]} max={ev.days[2]} value={f.days} onChange={set("days")}/></label>}
      <label className="field">Только тарифы (ID через запятую, пусто — все)<input value={f.plan_ids} onChange={set("plan_ids")}/></label>
      {f.event === "payment.paid" && <>
        <label className="field">Сумма оплаты от<input type="number" min="0" step="0.01" value={f.min_amount} onChange={set("min_amount")}/></label>
        <label className="field">Сумма оплаты до<input type="number" min="0" step="0.01" value={f.max_amount} onChange={set("max_amount")}/></label>
      </>}
      <label className="field">Не больше выполнений в сутки<input type="number" min="1" max="10000" value={f.daily_limit} onChange={set("daily_limit")}/></label>
      <label className="inline"><input type="checkbox" checked={f.notify} onChange={set("notify")}/>Отправить уведомление</label>
      {f.notify && <>
        <label className="field">Заголовок уведомления<input maxLength={120} value={f.title} onChange={set("title")}/></label>
        <label className="field">Текст уведомления<textarea maxLength={2000} rows={3} value={f.body} onChange={set("body")}/></label>
        <label className="inline"><input type="checkbox" checked={f.telegram} onChange={set("telegram")}/>Также сообщением в Telegram</label>
      </>}
      <label className="field">{`Бонус на баланс (до ${catalog.max_bonus}, пусто — без бонуса)`}<input type="number" min="0" step="0.01" max={catalog.max_bonus} value={f.bonus} onChange={set("bonus")}/></label>
      <label className="field">{`Личный промокод, % скидки (до ${catalog.max_promo_percent || 90}, пусто — без промокода)`}<input type="number" min="5" max={catalog.max_promo_percent || 90} value={f.promo_percent} onChange={set("promo_percent")}/></label>
      {f.promo_percent && <label className="field">Промокод действует, дней<input type="number" min="1" max="30" value={f.promo_days} onChange={set("promo_days")}/></label>}
      {f.promo_percent && !f.notify && <p className="muted">Промокод отправляется в уведомлении — включите уведомление и вставьте {"{promo}"} в текст.</p>}
      <button className="primary" disabled={busy || !f.name}>Создать правило</button>
    </form>
  </div>;
}

function Campaigns({campaigns, catalog, request, reload, toast}: any) {
  const blank = {name: "", kind: "broadcast", segment: "all", text: "", button_text: "", button_url: "", starts_at: ""};
  const [f, setF] = useState<any>(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.value});

  async function save(status: string) {
    if (busy) return; setBusy(true); setError("");
    const body = {name: f.name, kind: f.kind, status, audience: {segment: f.segment},
      content: {text: f.text, ...(f.button_text ? {button_text: f.button_text, button_url: f.button_url} : {})},
      starts_at: f.starts_at ? new Date(f.starts_at).toISOString() : null, ends_at: null};
    try { await request("/api/admin/enterprise/campaigns", {method: "POST", body: JSON.stringify(body)}); toast(status === "scheduled" ? "Кампания запланирована" : "Черновик сохранён"); setF(blank); reload(); }
    catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function schedule(c: any) {
    try {
      await request(`/api/admin/enterprise/campaigns/${c.id}`, {method: "PUT", body: JSON.stringify({name: c.name, kind: c.kind, status: "scheduled", audience: c.audience, content: c.content, starts_at: c.starts_at, ends_at: c.ends_at})});
      toast("Кампания запланирована"); reload();
    } catch (err: any) { setError(err.message); }
  }
  async function remove(c: any) {
    try { await request(`/api/admin/automation/campaigns/${c.id}`, {method: "DELETE"}); toast("Кампания удалена"); reload(); }
    catch (err: any) { setError(err.message); }
  }

  return <div className="card">
    <h3>Кампании</h3>
    <p className="muted">Запланированная кампания уходит в очередь рассылок Telegram в указанное время (без времени — при ближайшем запуске фонового процесса). Счётчики «отправлено» и «ошибки» берутся из рассылки.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {campaigns.length === 0 && <p className="muted">Кампаний пока нет.</p>}
    {campaigns.map((c: any) => <div className="automation-row" key={c.id} data-campaign-id={c.id}>
      <div><b>{c.name}</b><span>{KIND[c.kind] || c.kind} · {STATUS[c.status] || c.status} · старт {when(c.starts_at)}</span><span className="muted">Отправлено: {c.sent_count} · ошибки: {c.failed_count}</span></div>
      <div className="inline">
        {(c.status === "draft" || c.status === "paused") && <button onClick={() => schedule(c)}>Запланировать</button>}
        {c.status !== "running" && <button className="danger" onClick={() => remove(c)}>Удалить</button>}
      </div>
    </div>)}
    <h4>Новая кампания</h4>
    <div className="plan-form">
      <label className="field">Название кампании<input maxLength={255} value={f.name} onChange={set("name")}/></label>
      <label className="field">Тип<select value={f.kind} onChange={set("kind")}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="field">Кому<select value={f.segment} onChange={set("segment")}>{catalog.segments.map((s: any) => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>
      <label className="field">Текст сообщения<textarea maxLength={4096} rows={4} value={f.text} onChange={set("text")}/></label>
      <label className="field">Текст кнопки (необязательно)<input maxLength={100} value={f.button_text} onChange={set("button_text")}/></label>
      <label className="field">Адрес кнопки (HTTPS)<input value={f.button_url} onChange={set("button_url")}/></label>
      <label className="field">Начало отправки<input type="datetime-local" value={f.starts_at} onChange={set("starts_at")}/></label>
      <div className="inline">
        <button disabled={busy || !f.name} onClick={() => save("draft")}>Сохранить черновик</button>
        <button className="primary" disabled={busy || !f.name || !f.text} onClick={() => save("scheduled")}>Запланировать</button>
      </div>
    </div>
  </div>;
}
