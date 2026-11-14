import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

/** «Аналитика → Юнит-экономика»: сколько стоит и сколько приносит клиент из каждого источника. */
export function UnitEconomics({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [months, setMonths] = useState(3);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [spend, setSpend] = useState({source: "", month: new Date().toISOString().slice(0, 7), amount: ""});
  const load = () => request(`/api/admin/analytics/economics?months=${months}`).then(setData).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request, months]);
  async function saveSpend() {
    setError("");
    try {
      await request("/api/admin/analytics/economics/spend", {method: "PUT", body: JSON.stringify({...spend, amount: Number(spend.amount || 0)})});
      toast("Расход сохранён"); setSpend({...spend, amount: ""}); load();
    } catch (e: any) { setError(e.message); }
  }
  return (
    <div className="card">
      <div className="toolbar"><h3>Юнит-экономика по источникам</h3>
        <select aria-label="Период" value={months} onChange={e => setMonths(Number(e.target.value))}>{[1, 3, 6, 12].map(m => <option key={m} value={m}>{m} мес.</option>)}</select>
      </div>
      <p className="muted">Источник — первая ссылка клиента: бот <code>t.me/ваш_бот?start=src_vk_ads</code> (вместе с рефералом — <code>ref_КОД__src_vk_ads</code>), кабинет или Mini App <code>?utm_source=vk_ads</code>. Расходы на рекламу вносятся по месяцам ниже.</p>
      {error ? <p className="error">{error}</p> : null}
      {!data ? <p>Загрузка…</p> : data.sources.length === 0 ? <p className="muted">За период новых клиентов не было.</p> : (
        <table className="table">
          <thead><tr><th>Источник</th><th>Новых</th><th>Платящих</th><th>Конверсия</th><th>Выручка</th><th>Расход</th><th>CAC</th><th>Выручка на платящего</th><th>ROMI</th></tr></thead>
          <tbody>{data.sources.map((s: any) => (
            <tr key={s.source}><td><b>{s.source}</b></td><td>{s.new_customers}</td><td>{s.paying_customers}</td><td>{s.conversion}%</td>
              <td>{s.revenue}</td><td>{s.spend}</td><td>{s.cac ?? "—"}</td><td>{s.revenue_per_payer ?? "—"}</td>
              <td>{s.romi === null ? "—" : `${s.romi}%`}</td></tr>
          ))}</tbody>
        </table>
      )}
      <div className="toolbar">
        <input placeholder="Источник (vk_ads)" value={spend.source} onChange={e => setSpend({...spend, source: e.target.value})}/>
        <input type="month" value={spend.month} onChange={e => setSpend({...spend, month: e.target.value})}/>
        <input type="number" min="0" placeholder="Расход, ₽" value={spend.amount} onChange={e => setSpend({...spend, amount: e.target.value})}/>
        <button disabled={!spend.source.trim()} onClick={saveSpend}>Сохранить расход</button>
      </div>
      <p className="muted">ROMI = (выручка − расход) / расход. Выручка считается по клиентам, пришедшим за период, за всё время их оплат.</p>
    </div>
  );
}
