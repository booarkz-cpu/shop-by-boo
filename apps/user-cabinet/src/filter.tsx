import React, {useEffect, useState} from "react";

/** v28.54 «Фильтр рекламы и детский режим» на подписке клиента. */
type RequestFn = (path: string, options?: RequestInit) => Promise<any>;

export function FilterSection({request}: {request: RequestFn}) {
  const [f, setF] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => request("/api/me/filter").then(setF).catch(() => setF(null));
  useEffect(() => { load(); }, [request]);
  if (!f || !f.enabled) return null;
  async function choose(mode: string) {
    setBusy(true); setError("");
    try { await request("/api/me/filter", {method: "PUT", body: JSON.stringify({mode, subscription_id: f.subscription_id})}); await load(); }
    catch (e: any) { setError(e.message || "Не получилось"); } finally { setBusy(false); }
  }
  return (
    <div className="workspace-form filter-section">
      <h3>Фильтр</h3>
      <p className="section-sub">Блокировка рекламы и трекеров или детский режим (без рекламы и сайтов для взрослых) работает на сервере — на всех ваших устройствах сразу.</p>
      <div className="btn-row">
        <button className={!f.mode ? "btn-primary" : "btn-ghost"} disabled={busy} onClick={() => choose("")}>Без фильтра</button>
        {f.modes.map((m: any) => <button key={m.key} className={f.mode === m.key ? "btn-primary" : "btn-ghost"} disabled={busy} onClick={() => choose(m.key)}>{m.title}</button>)}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
