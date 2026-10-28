import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const mb = (n: number) => `${Math.round((n || 0) / 1024 / 1024)} МБ`;

/** «Резервные копии → Горячий резерв»: потоковая копия базы на втором сервере и агент, который следит за основным. */
export function HotStandby({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [issued, setIssued] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/standby").then((d: any) => { setData(d); setCfg(d.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  async function save() {
    setError("");
    try {
      await request("/api/admin/standby", {method: "PUT", body: JSON.stringify({enabled: cfg.enabled, lag_alert_seconds: Number(cfg.lag_alert_seconds)})});
      toast("Горячий резерв сохранён"); load();
    } catch (e: any) { setError(e.message); }
  }
  async function token() {
    if (data?.token_set && !window.confirm("Старый агент перестанет отчитываться, пока не получит новый токен. Продолжить?")) return;
    try { setIssued(await request("/api/admin/standby/token", {method: "POST"})); load(); } catch (e: any) { setError(e.message); }
  }
  if (!data || !cfg) return <div className="card"><h3>Горячий резерв</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const repl = data.replication || {};
  const beat = data.heartbeat || {};
  return (
    <div className="card">
      <h3>Горячий резерв</h3>
      <p className="muted">Второй сервер держит потоковую копию базы (отставание — секунды). Если основной сервер пропадёт, резерв сообщит в Telegram,
        а переключение — одна команда <code>bash scripts/hot-standby.sh promote</code> на резерве (или автоматически, если включить в агенте).
        Настройка: <code>hot-standby.sh primary IP_резерва</code> здесь и <code>hot-standby.sh standby IP_основного</code> на резерве.</p>
      {error ? <p className="error">{error}</p> : null}
      {data.problems?.length ? <div className="alert">{data.problems.map((p: any) => <div key={p.key}><b>{p.title}</b> — {p.detail}</div>)}</div> : null}
      {!repl.supported ? <p className="muted">База не PostgreSQL или статус репликации недоступен{repl.error ? `: ${repl.error}` : ""}.</p>
        : repl.in_recovery ? <p>Этот сервер сейчас <b>резерв</b> (база только читается).</p>
        : <table className="table"><thead><tr><th>Реплика</th><th>Состояние</th><th>Отставание</th><th>Не применено</th></tr></thead>
          <tbody>{repl.replicas.length === 0 ? <tr><td colSpan={4}>Реплик нет</td></tr> : repl.replicas.map((r: any) =>
            <tr key={r.address}><td>{r.address}</td><td>{r.state}</td><td>{r.lag_seconds} с</td><td>{mb(r.behind_bytes)}</td></tr>)}</tbody></table>}
      {repl.slots?.length ? <p className="muted">Слоты: {repl.slots.map((s: any) => `${s.name} — ${s.active ? "активен" : "не активен"}, держит ${mb(s.retained_bytes)}`).join("; ")}</p> : null}
      <p>Агент резерва: {beat.at ? <>{data.heartbeat_fresh ? "на связи" : "молчит"}, последний отчёт {String(beat.at).slice(0, 16).replace("T", " ")} UTC
        {beat.lag_seconds != null ? `, отставание ${beat.lag_seconds} с` : ""}{beat.auto_promote ? ", автоповышение включено" : ", автоповышение выключено"}</> : "ещё не отчитывался"}</p>
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={e => setCfg({...cfg, enabled: e.target.checked})}/> Резерв настроен — предупреждать, если он не получает данные</label>
      <label>Порог отставания для предупреждения, с<input type="number" min={10} max={86400} value={cfg.lag_alert_seconds} onChange={e => setCfg({...cfg, lag_alert_seconds: e.target.value})}/></label>
      <div className="toolbar"><button className="primary" onClick={save}>Сохранить</button><button onClick={token}>{data.token_set ? "Новый токен агента" : "Команда установки агента"}</button></div>
      {issued ? <div className="alert">Выполните на резервном сервере (команда показывается один раз; подставьте IP основного):<pre style={{whiteSpace: "pre-wrap"}}>{issued.install}</pre></div> : null}
    </div>
  );
}
