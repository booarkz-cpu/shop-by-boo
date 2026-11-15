import React, {useMemo, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

const KIND: Record<string, string> = {
  payment_velocity: "Много платежей за сутки",
  fulfillment_failure_velocity: "Много неудачных выдач за сутки",
};
const STATUS: Record<string, string> = {open: "открыт", resolved: "решён", blocked: "мошенничество"};

/** Anti-fraud signals: scan, filter and record a decision with a note for each signal. */
export function Fraud({data, request, reload, toast}: {data: any; request: Request; reload: () => void; toast: (m: string) => void}) {
  const rows: any[] = Array.isArray(data) ? data : [];
  const [filter, setFilter] = useState("open");
  const [selected, setSelected] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const shown = useMemo(() => rows.filter(x => filter === "all" || x.status === filter), [rows, filter]);
  const current = rows.find(x => x.id === selected) || null;
  const counts = useMemo(() => rows.reduce((a: any, x: any) => ({...a, [x.status]: (a[x.status] || 0) + 1}), {}), [rows]);

  async function scan() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const r = await request("/api/admin/fraud/scan", {method: "POST"});
      toast(r.created ? `Новых сигналов: ${r.created}` : "Новых сигналов нет");
      reload();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function decide(status: string) {
    if (!current || busy) return;
    setBusy(true); setError("");
    try {
      await request(`/api/admin/fraud/${current.id}`, {method: "POST", body: JSON.stringify({status, note})});
      toast(status === "open" ? "Сигнал снова открыт" : status === "blocked" ? "Отмечено как мошенничество" : "Отмечено как ложная тревога");
      setSelected(null); setNote(""); reload();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  return <div className="grid2">
    <div className="card">
      <div className="toolbar">
        <h3>Антифрод</h3>
        <button className="primary" disabled={busy} onClick={scan}>Сканировать</button>
      </div>
      <p className="muted">Сканирование ищет за последние сутки клиентов с 10 и больше платежами и с 3 и больше неудачными выдачами. Повторное сканирование не создаёт дубли для открытых сигналов.</p>
      {error && <div role="alert" className="error">{error}</div>}
      <label className="field">Показать
        <select value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="open">Открытые ({counts.open || 0})</option>
          <option value="resolved">Решённые ({counts.resolved || 0})</option>
          <option value="blocked">Мошенничество ({counts.blocked || 0})</option>
          <option value="all">Все ({rows.length})</option>
        </select>
      </label>
      {shown.length === 0 ? <p className="muted">Сигналов нет.</p> :
        <div className="table-wrap"><table><thead><tr><th>ID</th><th>Клиент</th><th>Тип</th><th>Оценка</th><th>Статус</th><th>Создан</th><th></th></tr></thead>
          <tbody>{shown.map(x => <tr key={x.id} data-signal-id={x.id} aria-selected={x.id === selected}>
            <td>{x.id}</td><td>{x.user_id ?? "—"}</td><td>{KIND[x.kind] || x.kind}</td><td>{x.score}</td>
            <td>{STATUS[x.status] || x.status}</td><td>{x.created_at ? String(x.created_at).replace("T", " ").slice(0, 16) : "—"}</td>
            <td><button onClick={() => { setSelected(x.id); setNote(""); setError(""); }}>Решение</button></td>
          </tr>)}</tbody></table></div>}
    </div>
    <div className="card">
      <h3>Решение по сигналу</h3>
      {!current ? <p className="muted">Выберите сигнал в таблице. Перед решением откройте клиента в разделе «Клиенты»: платежи, устройства и обращения.</p> : <>
        <p><b>Сигнал #{current.id}</b> · клиент {current.user_id ?? "—"} · {KIND[current.kind] || current.kind} · оценка {current.score}</p>
        {current.details && <p className="muted">{current.details}</p>}
        {current.ip && <p className="muted">IP: {current.ip}</p>}
        <label className="field">Заметка к решению
          <textarea value={note} maxLength={2000} onChange={e => setNote(e.target.value)} placeholder="Почему принято решение" />
        </label>
        <p className="muted">Решение и заметка пишутся в журнал действий. Отметка «Мошенничество» не ограничивает клиента сама: оформите возврат и ограничьте клиента массовой операцией.</p>
        <div className="inline">
          {current.status !== "resolved" && <button disabled={busy} onClick={() => decide("resolved")}>Ложная тревога</button>}
          {current.status !== "blocked" && <button className="danger" disabled={busy} onClick={() => decide("blocked")}>Мошенничество</button>}
          {current.status !== "open" && <button disabled={busy} onClick={() => decide("open")}>Открыть снова</button>}
          <button disabled={busy} onClick={() => setSelected(null)}>Отмена</button>
        </div>
      </>}
    </div>
  </div>;
}
