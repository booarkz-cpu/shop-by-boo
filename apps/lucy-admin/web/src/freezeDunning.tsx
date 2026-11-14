import React, {useEffect, useState} from "react";

/** v28.50 «Заморозка подписки» и «Повторные попытки автопродления» (вкладка «Тарифы»). */
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (t: string) => void};

const date = (v?: string) => v ? new Date(v + (v.endsWith("Z") ? "" : "Z")).toLocaleString("ru-RU", {dateStyle: "short", timeStyle: "short"}) : "—";

export function FreezeAdmin({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [c, setC] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/freeze").then(x => { setD(x); setC(x.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Заморозка подписки</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const n = (k: string, label: string) => <label className="field">{label}<input type="number" value={c[k]} onChange={e => setC({...c, [k]: Number(e.target.value)})}/></label>;
  async function save() { setError(""); try { setC(await request("/api/admin/freeze", {method: "PUT", body: JSON.stringify(c)})); toast("Правила заморозки сохранены"); load(); } catch (e: any) { setError(e.message); } }
  async function thaw(id: number) { if (!confirm("Разморозить подписку сейчас? Неиспользованные дни заморозки вычтутся из срока.")) return; try { await request(`/api/admin/freeze/${id}/thaw`, {method: "POST"}); toast("Подписка разморожена"); load(); } catch (e: any) { setError(e.message); } }
  return (
    <div className="card">
      <h3>Заморозка подписки</h3>
      <p className="muted">Клиент ставит оплаченную подписку на паузу вместо отмены: VPN выключается, оплаченные дни сохраняются, срок сдвигается на время заморозки. Покупка, подарок или бонусные дни размораживают подписку.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Клиенты могут замораживать подписку</label>
        <label><input type="checkbox" checked={!!c.paid_only} onChange={e => setC({...c, paid_only: e.target.checked})}/> Только оплаченные подписки</label>
      </div>
      <div className="form-grid">{n("min_days", "Минимум дней за раз")}{n("max_days", "Максимум дней за раз")}{n("year_days", "Всего дней за год")}{n("year_times", "Заморозок за год")}{n("min_left_days", "Должно оставаться дней, от")}</div>
      <button className="primary" onClick={save}>Сохранить</button>
      <h4>Сейчас заморожено: {d?.frozen_now ?? 0} · за 30 дней: {d?.started_30d ?? 0}</h4>
      {d?.items?.length ? <table className="table"><thead><tr><th>Подписка</th><th>Клиент</th><th>С</th><th>До</th><th>Дней</th><th/></tr></thead><tbody>
        {d.items.map((x: any) => <tr key={x.subscription_id}><td>#{x.subscription_id}</td><td>#{x.user_id}</td><td>{date(x.since)}</td><td>{date(x.until)}</td><td>{x.days}</td>
          <td><button onClick={() => thaw(x.subscription_id)}>Разморозить</button></td></tr>)}
      </tbody></table> : <p className="muted">Замороженных подписок нет.</p>}
    </div>
  );
}

export function DunningAdmin({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [c, setC] = useState<any>(null);
  const [hours, setHours] = useState("");
  const [error, setError] = useState("");
  const load = () => request("/api/admin/dunning").then(x => { setD(x); setC(x.config); setHours((x.config.retry_hours || []).join(", ")); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Повторные попытки автопродления</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  async function save() {
    setError("");
    const retry_hours = hours.split(/[\s,;]+/).filter(Boolean).map(Number).filter(Number.isFinite);
    try { setC(await request("/api/admin/dunning", {method: "PUT", body: JSON.stringify({...c, retry_hours})})); toast("Повторные попытки сохранены"); load(); } catch (e: any) { setError(e.message); }
  }
  return (
    <div className="card">
      <h3>Повторные попытки автопродления</h3>
      <p className="muted">Что делать, если банк отклонил списание за продление. Пока правила выключены, действует прежняя схема: повтор через 2, 4 … 72 часа, 72 часа льготы, после третьего отказа автопродление выключается без сообщения клиенту.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Включено</label>
        <label><input type="checkbox" checked={!!c.notify} onChange={e => setC({...c, notify: e.target.checked})}/> Сообщать клиенту о каждом отказе</label>
        <label><input type="checkbox" checked={!!c.wallet_fallback} onChange={e => setC({...c, wallet_fallback: e.target.checked})}/> Продлевать с баланса, если хватает денег</label>
      </div>
      <div className="form-grid">
        <label className="field">Повторы через, часов (по порядку)<input value={hours} onChange={e => setHours(e.target.value)} placeholder="24, 72, 120"/></label>
        <label className="field">Отказов до выключения автопродления<input type="number" value={c.max_failures} onChange={e => setC({...c, max_failures: Number(e.target.value)})}/></label>
        <label className="field">VPN работает после неудачи, часов<input type="number" value={c.grace_hours} onChange={e => setC({...c, grace_hours: Number(e.target.value)})}/></label>
      </div>
      <button className="primary" onClick={save}>Сохранить</button>
      <h4>Сейчас</h4>
      <p className="muted">Ждут повторного списания: {d?.past_due ?? 0} · автопродление выключено после отказов: {d?.switched_off ?? 0} · работают в льготном режиме: {d?.in_grace ?? 0} · продлено с баланса за 30 дней: {d?.wallet_30d ?? 0}</p>
    </div>
  );
}
