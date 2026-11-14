import React, {useEffect, useState} from "react";
import {EmptyState, LoadState} from "./components/ui/state";

/** v28.73 «Журнал уведомлений касс» (вкладка «Кассы»): принятые и отклонённые уведомления. */
type Request = (path: string, options?: RequestInit) => Promise<any>;
const when = (v?: string) => (v ? String(v).slice(0, 16).replace("T", " ") : "—");
const STATUS: Record<string, string> = {processed: "обработано", retry: "ждёт повтора", processing: "обрабатывается", verified: "проверено"};

export function PaymentJournal({request}: {request: Request}) {
  const [d, setD] = useState<any>(null);
  const [provider, setProvider] = useState("");
  const [days, setDays] = useState(7);
  const [error, setError] = useState("");
  const load = () => { setError(""); request(`/api/admin/payments/events?provider=${encodeURIComponent(provider)}&days=${days}&limit=100`).then(setD).catch(e => setError(e.message)); };
  useEffect(() => { load(); }, [request, provider, days]);
  if (!d) return <LoadState error={error} onRetry={load} label="Загрузка журнала уведомлений…"/>;
  const providers = Array.from(new Set([...d.accepted.map((x: any) => x.provider), ...d.refused.map((x: any) => x.provider)])).sort();
  return (
    <div className="card">
      <div className="toolbar"><h3>Журнал уведомлений касс</h3>
        <div className="inline">
          <label>Касса<select value={provider} onChange={e => setProvider(e.target.value)}><option value="">все</option>{providers.map((p: any) => <option key={p} value={p}>{p}</option>)}</select></label>
          <label>Период<select value={days} onChange={e => setDays(Number(e.target.value))}><option value={1}>сутки</option><option value={7}>7 дней</option><option value={30}>30 дней</option></select></label>
          <button onClick={load}>Обновить</button>
        </div>
      </div>
      <p className="muted">Уведомление кассы — только подсказка: оплату магазин всегда перепроверяет у самой кассы, а повторное уведомление не выдаёт подписку второй раз. «Отклонённые» — неверная подпись, другая сумма или заказ, либо касса не подтвердила оплату; тело таких запросов не сохраняется.</p>
      {error ? <p className="error">{error}</p> : null}
      <p>Обработано: <b>{d.summary.processed}</b> · ждут повтора: <b>{d.summary.retry}</b> · в работе: <b>{d.summary.processing}</b> · отклонено: <b>{d.summary.refused}</b></p>
      <h4>Принятые</h4>
      {!d.accepted.length ? <EmptyState title="Уведомлений за период нет" hint="Если оплаты были, проверьте адрес уведомлений в кабинете кассы."/> :
        <table className="table"><thead><tr><th>Время</th><th>Касса</th><th>Заказ</th><th>Сумма</th><th>Статус</th><th>Попыток</th><th>Ошибка</th></tr></thead><tbody>
          {d.accepted.map((e: any) => <tr key={e.provider + e.event_id}><td>{when(e.received_at)}</td><td>{e.provider}</td>
            <td><span className="mono">{e.order_id || `#${e.payment_id ?? "—"}`}</span></td><td>{e.amount ? `${e.amount} ${e.currency || ""}` : "—"}</td>
            <td>{STATUS[e.status] || e.status}</td><td>{e.attempts}</td><td>{e.error || "—"}</td></tr>)}
        </tbody></table>}
      <h4>Отклонённые</h4>
      {!d.refused.length ? <EmptyState title="Отклонённых уведомлений нет"/> :
        <table className="table"><thead><tr><th>Время</th><th>Касса</th><th>Ответ</th><th>Причина</th></tr></thead><tbody>
          {d.refused.map((r: any, i: number) => <tr key={i}><td>{when(r.at)}</td><td>{r.provider}</td><td>HTTP {r.status}</td><td>{r.reason}</td></tr>)}
        </tbody></table>}
    </div>
  );
}
