import React, {useEffect, useState} from "react";

/** v28.45 «Здоровье касс»: таблица возможностей, проба ключей, уведомления, которые не пришли, «лучшая касса первой». */
type Request = (path: string, options?: RequestInit) => Promise<any>;
const when = (v?: string) => (v ? String(v).slice(0, 16).replace("T", " ") : "—");

export function GatewayHealth({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [notes, setNotes] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => Promise.all([request("/api/admin/gateways"), request("/api/admin/gateways/notifications?days=7")])
    .then(([g, n]) => { setData(g); setNotes(n); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  async function act(fn: () => Promise<any>, text: string) {
    setBusy(true); setError("");
    try { const r = await fn(); toast(text); await load(); return r; } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  const cfg = data?.config || {};
  const set = (k: string, v: any) => setData({...data, config: {...cfg, [k]: v}});
  const num = (k: string, label: string, min: number, max: number) => (
    <label>{label}<input type="number" min={min} max={max} value={cfg[k] ?? ""} onChange={e => set(k, Number(e.target.value))}/></label>);
  return (
    <div className="card">
      <div className="toolbar"><h3>Здоровье касс</h3>
        <button disabled={busy} onClick={() => act(() => request("/api/admin/gateways/probe", {method: "POST"}), "Проба касс выполнена")}>Проверить кассы сейчас</button>
      </div>
      <p className="muted">Каждые несколько часов магазин делает одну проверочную операцию в каждой настроенной кассе. Если касса подряд не отвечает или не принимает ключи, она выходит из очереди, а вы получаете сообщение. Как только проверка пройдёт, касса вернётся в очередь.</p>
      {error ? <p className="error">{error}</p> : null}
      {!data ? <p>Загрузка…</p> : <>
        <table className="table">
          <thead><tr><th>Касса</th><th>Ключи</th><th>Проба</th><th>Подпись уведомлений</th><th>Проверка перед выдачей</th><th>Возвраты</th><th>Автоплатежи</th></tr></thead>
          <tbody>{data.gateways.map((g: any) => (
            <tr key={g.name}>
              <td><b>{g.title}</b><div className="muted">{g.webhook}</div></td>
              <td>{g.configured ? "заданы" : <span className="muted">нет: {g.missing_keys.join(", ")}</span>}</td>
              <td>{!g.probe ? "—" : g.probe.ok ? `✅ ${g.probe.latency_ms} мс · ${when(g.probe.at)}` : `❌ ${g.probe.error}${g.probe.taken_out ? " · вне очереди" : ""}`}</td>
              <td>{g.signature}</td><td>{g.recheck}</td><td>{g.refunds ? "API" : "в кабинете кассы"}</td><td>{g.recurring ? "да" : "нет"}</td>
            </tr>))}</tbody>
        </table>
        <h4>Уведомления за 7 дней</h4>
        {!notes?.providers?.length ? <p className="muted">Оплат за период не было.</p> : (
          <table className="table">
            <thead><tr><th>Касса</th><th>Оплачено</th><th>Без уведомления</th><th>Доля</th><th>Зависли в ожидании</th></tr></thead>
            <tbody>{notes.providers.map((p: any) => (
              <tr key={p.provider}><td>{p.provider}</td><td>{p.paid}</td><td>{p.without_notification}</td>
                <td>{p.missing_share >= (cfg.missing_alert_share || 20) && p.paid >= 5 ? <b>{p.missing_share}%</b> : `${p.missing_share}%`}</td><td>{p.stuck_pending}</td></tr>))}</tbody>
          </table>)}
        <p className="muted">«Без уведомления» значит, что оплату нашла сверка, а касса о ней не сообщила. Проверьте адрес уведомлений и ключ подписи в кабинете кассы.</p>
        <h4>Настройки</h4>
        <div className="toolbar">
          <label><input type="checkbox" checked={!!cfg.probe_enabled} onChange={e => set("probe_enabled", e.target.checked)}/> Проба касс</label>
          {num("probe_hours", "Каждые, ч", 1, 72)}{num("fail_threshold", "Ошибок подряд до вывода", 1, 10)}{num("cooldown_hours", "Вне очереди, ч", 1, 168)}
          {num("notify_minutes", "Ожидание уведомления, мин", 5, 1440)}{num("missing_alert_share", "Тревога при доле без уведомления, %", 1, 100)}
        </div>
        <div className="toolbar">
          <label><input type="checkbox" checked={!!cfg.auto_priority} onChange={e => set("auto_priority", e.target.checked)}/> Лучшая касса первой (раз в сутки по конверсии)</label>
          {num("auto_days", "За дней", 1, 90)}{num("auto_min_orders", "Минимум заказов", 5, 10000)}
          <button className="primary" disabled={busy} onClick={() => act(() => request("/api/admin/gateways/config", {method: "PUT", body: JSON.stringify(cfg)}), "Настройки здоровья касс сохранены")}>Сохранить</button>
          <button disabled={busy} onClick={async () => { const r = await act(() => request("/api/admin/gateways/auto-priority?dry_run=true", {method: "POST"}), "Расчёт готов"); if (r) setPlan(r); }}>Показать новый порядок</button>
        </div>
        {plan ? <p className="muted">Сейчас: {plan.before.join(" → ") || "—"}. По конверсии: {plan.after.join(" → ") || "—"}{plan.changed ? "" : " (без изменений)"}.</p> : null}
      </>}
    </div>
  );
}
