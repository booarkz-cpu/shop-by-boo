import React, {useEffect, useState} from "react";

/** v28.49 «Правила платежей»: антифрод поверх базовой оценки риска — подбор карт, новые аккаунты, много аккаунтов с одного адреса, чарджбэки, стоп-лист. */
type Request = (path: string, options?: RequestInit) => Promise<any>;

export function PaymentFraud({request, toast}: {request: Request; toast: (t: string) => void}) {
  const [c, setC] = useState<any>(null);
  const [r, setR] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => Promise.all([request("/api/admin/fraud/payment-rules"), request("/api/admin/fraud/payment-reviews?days=7")])
    .then(([cfg, rev]) => { setC(cfg); setR(rev); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Правила платежей</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const n = (k: string, label: string) => <label>{label}<input type="number" value={c[k]} onChange={e => setC({...c, [k]: Number(e.target.value)})}/></label>;
  const list = (k: string, label: string, numbers = false) => <label>{label}<textarea rows={2} value={(c[k] || []).join("\n")}
    onChange={e => setC({...c, [k]: e.target.value.split(/[\s,;]+/).filter(Boolean).map((x: string) => numbers ? Number(x) : x).filter((x: any) => !numbers || Number.isFinite(x))})}/></label>;
  async function save() { setError(""); try { setC(await request("/api/admin/fraud/payment-rules", {method: "PUT", body: JSON.stringify(c)})); toast("Правила платежей сохранены"); } catch (e: any) { setError(e.message); } }
  return (
    <div className="card">
      <h3>Правила платежей</h3>
      <p className="muted">Баллы правил прибавляются к базовой оценке риска. При пороге «проверка» платёж проходит, но вы получаете сообщение. При пороге «отказ» платёж отклоняется. Правила действуют на покупку тарифов и на пополнение кошелька.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Включено</label>
        <label><input type="checkbox" checked={!!c.alert} onChange={e => setC({...c, alert: e.target.checked})}/> Сообщать в Telegram</label>
      </div>
      <h4>Подбор карт</h4>
      <div className="form-grid">{n("failed_24h", "Неудачных оплат за сутки, от")}{n("failed_points", "Баллов за подбор карт")}</div>
      <h4>Новый аккаунт</h4>
      <div className="form-grid">{n("new_account_hours", "Аккаунт моложе, часов")}{n("new_account_amount", "Сумма оплаты от, ₽")}{n("new_account_points", "Баллов за новый аккаунт")}</div>
      <h4>Общий адрес и чарджбэки</h4>
      <div className="form-grid">{n("accounts_per_ip", "Аккаунтов с одного адреса за сутки, от")}{n("accounts_points", "Баллов за общий адрес")}{n("chargeback_points", "Баллов за каждый чарджбэк")}</div>
      <h4>Стоп-листы</h4>
      <p className="muted">По одному значению в строке. Платёж из стоп-листа отклоняется сразу.</p>
      <div className="form-grid stoplists">{list("block_ips", "Адреса (IP)")}{list("block_emails", "E-mail")}{list("block_telegram_ids", "Telegram ID", true)}{list("block_user_ids", "ID клиентов", true)}</div>
      <button className="primary" onClick={save}>Сохранить</button>
      <h4>За 7 дней</h4>
      {!r ? null : <>
        <p className="muted">На проверке: {r.reviews.length}, отклонено: {r.blocked.length}.</p>
        <table className="table"><thead><tr><th>Когда</th><th>Клиент</th><th>Сумма / платёж</th><th>Риск</th><th>Признаки</th></tr></thead><tbody>
          {r.reviews.slice(0, 30).map((x: any) => <tr key={`r${x.payment_id}`}><td>{x.at.slice(0, 16).replace("T", " ")}</td><td>#{x.user_id}</td><td>{x.amount} · #{x.payment_id} {x.status}</td><td>{x.score} · проверка</td><td>{JSON.stringify(x.signals)}</td></tr>)}
          {r.blocked.slice(0, 30).map((x: any, i: number) => <tr key={`b${i}`}><td>{x.at.slice(0, 16).replace("T", " ")}</td><td>#{x.user_id}</td><td>—</td><td>{x.score} · отказ</td><td>{x.details}</td></tr>)}
        </tbody></table>
      </>}
    </div>
  );
}
