import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

const NAMES: Record<string, string> = {yookassa: "ЮKassa", rollypay: "RollyPay", platega: "Platega", cryptobot: "CryptoBot", freekassa: "Freekassa"};

/** «Платёжные агенты»: очередь касс. Заказ уходит в первую включённую, настроенную и не остывающую кассу. */
export function PaymentQueue({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [rows, setRows] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => request("/api/admin/v41/providers").then((r: any[]) => setRows([...r].sort((a, b) => a.priority - b.priority))).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  async function save(next: any[], text: string) {
    setBusy(true); setError("");
    try {
      // Priorities 10, 20, 30… keep room for manual edits and make the order explicit.
      for (const [i, row] of next.entries()) {
        await request(`/api/admin/v41/providers/${row.provider}`, {method: "PUT", body: JSON.stringify({enabled: row.enabled, priority: (i + 1) * 10})});
      }
      toast(text); await load();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  function move(i: number, delta: number) {
    const next = [...rows]; const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    save(next, "Очередь касс сохранена");
  }
  function toggle(i: number) {
    const next = rows.map((r, k) => k === i ? {...r, enabled: !r.enabled} : r);
    save(next, next[i].enabled ? `${NAMES[next[i].provider] || next[i].provider} включена` : `${NAMES[next[i].provider] || next[i].provider} выключена`);
  }
  async function reset(provider: string) {
    setBusy(true);
    try { await request(`/api/admin/v41/providers/${provider}/reset`, {method: "POST"}); toast("Касса снова принимает оплаты"); await load(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  const ready = rows.filter(r => r.enabled && r.configured);
  return (
    <div className="card">
      <h3>Очередь касс</h3>
      <p className="muted">Заказ уходит в первую кассу сверху, которая включена, настроена и не остывает. Три ошибки подряд — касса остывает 5 минут, заказы идут в следующую; об этом приходит сообщение в Telegram.</p>
      {error ? <p className="error">{error}</p> : null}
      {ready.length < 2 ? <div className="alert">Готовых касс: {ready.length}. Добавьте ключи хотя бы одной резервной кассы — иначе при сбое основной оплаты встанут.</div> : null}
      <table className="table">
        <thead><tr><th>#</th><th>Касса</th><th>Ключи</th><th>Состояние</th><th>Успешно / ошибки</th><th></th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.provider}>
              <td>{i + 1}</td>
              <td><b>{NAMES[r.provider] || r.provider}</b></td>
              <td>{r.configured ? "заданы" : <span className="muted">нет — «Настройки без перезапуска»</span>}</td>
              <td>{!r.enabled ? "выключена" : r.cooling ? `остывает до ${String(r.circuit_open_until).slice(11, 16)} UTC` : r.configured ? "принимает" : "не настроена"}</td>
              <td>{r.success_count} / {r.failure_count}</td>
              <td className="toolbar">
                <button disabled={busy || i === 0} onClick={() => move(i, -1)} aria-label="Выше">↑</button>
                <button disabled={busy || i === rows.length - 1} onClick={() => move(i, 1)} aria-label="Ниже">↓</button>
                <button disabled={busy} onClick={() => toggle(i)}>{r.enabled ? "Выключить" : "Включить"}</button>
                {r.cooling ? <button className="primary" disabled={busy} onClick={() => reset(r.provider)}>Вернуть в работу</button> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** «Кассы за период»: конверсия, выручка и время до оплаты по каждой кассе. */
export function ProviderReport({request}: {request: Request}) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request(`/api/admin/payments/providers-report?days=${days}`).then(setData).catch(e => setError(e.message)); }, [request, days]);
  return (
    <div className="card">
      <div className="toolbar"><h3>Кассы за период</h3>
        <select value={days} onChange={e => setDays(Number(e.target.value))} aria-label="Период">
          {[7, 30, 90].map(d => <option key={d} value={d}>{d} дней</option>)}
        </select>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {!data ? <p>Загрузка…</p> : data.providers.length === 0 ? <p className="muted">За период заказов не было.</p> : (
        <table className="table">
          <thead><tr><th>Касса</th><th>Заказов</th><th>Оплачено</th><th>Конверсия</th><th>Выручка</th><th>До оплаты, мин (медиана)</th></tr></thead>
          <tbody>{data.providers.map((p: any) => (
            <tr key={p.provider}><td><b>{NAMES[p.provider] || p.provider}</b>{data.best === p.provider ? " · лучшая" : ""}</td>
              <td>{p.orders}</td><td>{p.paid}</td><td>{p.conversion}%</td><td>{p.revenue}</td><td>{p.median_minutes_to_pay ?? "—"}</td></tr>
          ))}</tbody>
        </table>
      )}
      {data?.best ? <p className="muted">Лучшая конверсия — {NAMES[data.best] || data.best}. Если она не первая в очереди, поднимите её выше.</p> : null}
    </div>
  );
}
