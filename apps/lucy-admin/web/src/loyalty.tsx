import React, {useEffect, useState} from "react";

/** v28.51 «Уровни лояльности» (вкладка «Маркетинг»): уровни по стажу и сумме оплат, кешбэк, скидка, бонусные дни. */
type Request = (path: string, options?: RequestInit) => Promise<any>;

const FIELDS: [string, string][] = [["months", "Месяцев с нами, от"], ["spent", "Или оплат на сумму, от"], ["cashback_percent", "Кешбэк, %"], ["discount_percent", "Скидка, %"], ["bonus_days", "Дней в подарок при переходе"]];

export function LoyaltyAdmin({request, toast}: {request: Request; toast: (t: string) => void}) {
  const [d, setD] = useState<any>(null);
  const [c, setC] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/loyalty").then(x => { setD(x); setC(x.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Уровни лояльности</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const setLevel = (i: number, patch: any) => setC({...c, levels: c.levels.map((x: any, j: number) => j === i ? {...x, ...patch} : x)});
  async function save() { setError(""); try { setC(await request("/api/admin/loyalty", {method: "PUT", body: JSON.stringify({enabled: c.enabled, hold_days: c.hold_days, levels: c.levels})})); toast("Уровни сохранены"); load(); } catch (e: any) { setError(e.message); } }
  return (
    <div className="card">
      <h3>Уровни лояльности</h3>
      <p className="muted">Уровень достигается по стажу (месяцев с первой оплаты) или по сумме оплат — что наступит раньше. Кешбэк начисляется на баланс за оплаты после включения уровней, через «Удержание кешбэка» дней. При возврате платежа кешбэк списывается. Скидка не складывается с промокодом: действует большая.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Уровни включены</label>
        <label className="field">Удержание кешбэка, дней<input type="number" value={c.hold_days} onChange={e => setC({...c, hold_days: Number(e.target.value)})}/></label>
      </div>
      {c.levels.map((lv: any, i: number) => <div key={i}>
        <h4>{i + 1}. {lv.title} {d?.members ? <span className="muted">· клиентов: {d.members[lv.key] ?? 0}</span> : null}</h4>
        <div className="form-grid">
          <label className="field">Название<input value={lv.title} onChange={e => setLevel(i, {title: e.target.value})}/></label>
          <label className="field">Ключ<input value={lv.key} onChange={e => setLevel(i, {key: e.target.value})}/></label>
          {FIELDS.map(([k, label]) => <label key={k} className="field">{label}<input type="number" value={lv[k]} disabled={i === 0 && (k === "months" || k === "spent" || k === "bonus_days")} onChange={e => setLevel(i, {[k]: Number(e.target.value)})}/></label>)}
        </div>
        {i > 0 && <button onClick={() => setC({...c, levels: c.levels.filter((_: any, j: number) => j !== i)})}>Удалить уровень</button>}
      </div>)}
      <div className="inline">
        {c.levels.length < 8 && <button onClick={() => setC({...c, levels: [...c.levels, {key: `level${c.levels.length + 1}`, title: "Новый уровень", months: 24, spent: 10000, cashback_percent: 0, discount_percent: 0, bonus_days: 0}]})}>Добавить уровень</button>}
        <button className="primary" onClick={save}>Сохранить</button>
      </div>
      <p className="muted">Кешбэка начислено за 30 дней: {d?.cashback_30d ?? "0.00"} ₽</p>
    </div>
  );
}
