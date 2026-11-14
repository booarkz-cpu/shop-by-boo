import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

/** «Серверы → Монитор блокировок»: пробы в регионах клиентов, что заблокировано и что сделано автоматически. */
export function BlockMonitor({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [error, setError] = useState("");
  const [probe, setProbe] = useState({name: "", region: "RU"});
  const [created, setCreated] = useState<any>(null);
  const load = () => request("/api/admin/block-monitor").then((d: any) => { setData(d); setCfg(d.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  async function save() {
    setError("");
    try {
      const ports = String(cfg.node_ports_text ?? (cfg.node_ports || []).join(", ")).split(/[\s,]+/).filter(Boolean).map(Number);
      await request("/api/admin/block-monitor", {method: "PUT", body: JSON.stringify({enabled: cfg.enabled, fail_streak: Number(cfg.fail_streak),
        node_ports: ports, reorder_mirrors: cfg.reorder_mirrors, fallback_squad_uuid: (cfg.fallback_squad_uuid || "").trim(), auto_fallback_squad: cfg.auto_fallback_squad})});
      toast("Монитор блокировок сохранён"); load();
    } catch (e: any) { setError(e.message); }
  }
  async function addProbe() {
    setError("");
    try { setCreated(await request("/api/admin/block-monitor/probes", {method: "POST", body: JSON.stringify(probe)})); setProbe({name: "", region: probe.region}); load(); }
    catch (e: any) { setError(e.message); }
  }
  async function removeProbe(id: string) {
    try { await request(`/api/admin/block-monitor/probes/${id}`, {method: "DELETE"}); toast("Проба удалена"); load(); } catch (e: any) { setError(e.message); }
  }
  if (!data || !cfg) return <div className="card"><h3>Монитор блокировок</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const blocked = Object.entries(data.blocked || {}) as [string, any][];
  return (
    <div className="card">
      <h3>Монитор блокировок</h3>
      <p className="muted">Пробы на серверах в регионах клиентов каждые 5 минут проверяют адреса API и ноды. Если все пробы региона не могут подключиться, а магазин видит адрес работающим, — это блокировка: приходит сообщение в Telegram, приложения получают резервный адрес первым, по желанию всем добавляется резервный профиль.</p>
      {error ? <p className="error">{error}</p> : null}
      {blocked.length ? <div className="alert">{blocked.map(([t, v]) => <div key={t}>Заблокировано в {v.regions.join(", ")}: <b>{v.label}</b> ({t})</div>)}</div> : <p>Блокировок не видно.</p>}
      {data.fallback_active ? <p className="muted">Резервный профиль сейчас добавлен всем клиентам.</p> : null}
      {data.fallback_error ? <p className="error">Резервный профиль: {data.fallback_error}</p> : null}
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={e => setCfg({...cfg, enabled: e.target.checked})}/> Реагировать на блокировки</label>
      <label>Неудач подряд для блокировки<input type="number" min={1} max={20} value={cfg.fail_streak} onChange={e => setCfg({...cfg, fail_streak: e.target.value})}/></label>
      <label>Порты нод для проверки<input value={cfg.node_ports_text ?? (cfg.node_ports || []).join(", ")} onChange={e => setCfg({...cfg, node_ports_text: e.target.value})}/></label>
      <label className="check"><input type="checkbox" checked={cfg.reorder_mirrors} onChange={e => setCfg({...cfg, reorder_mirrors: e.target.checked})}/> Заблокированный адрес API — в конец списка для приложений</label>
      <label>UUID резервного Internal Squad (Reality, XHTTP…)<input value={cfg.fallback_squad_uuid || ""} onChange={e => setCfg({...cfg, fallback_squad_uuid: e.target.value})}/></label>
      <label className="check"><input type="checkbox" checked={cfg.auto_fallback_squad} onChange={e => setCfg({...cfg, auto_fallback_squad: e.target.checked})}/> Пока нода заблокирована, добавлять всем клиентам резервный профиль</label>
      <div className="toolbar"><button className="primary" onClick={save}>Сохранить</button></div>

      <h4>Пробы</h4>
      {data.probes.length === 0 ? <p className="muted">Проб нет. Добавьте сервер в регионе клиентов, например недорогой VPS в России.</p> : (
        <table className="table"><thead><tr><th>Проба</th><th>Регион</th><th>Последний отчёт</th><th></th></tr></thead>
          <tbody>{data.probes.map((p: any) => <tr key={p.id}><td>{p.name}</td><td>{p.region}</td><td>{p.last_seen_at ? `${String(p.last_seen_at).slice(0, 16).replace("T", " ")} UTC${p.fresh ? "" : " — молчит"}` : "ещё не было"}</td>
            <td><button onClick={() => removeProbe(p.id)}>Удалить</button></td></tr>)}</tbody></table>
      )}
      <div className="toolbar">
        <input placeholder="Название (Москва, VPS)" value={probe.name} onChange={e => setProbe({...probe, name: e.target.value})}/>
        <input placeholder="Регион" value={probe.region} onChange={e => setProbe({...probe, region: e.target.value})}/>
        <button disabled={!probe.name.trim()} onClick={addProbe}>Добавить пробу</button>
      </div>
      {created ? <div className="alert">Выполните на сервере пробы (команда показывается один раз):<pre style={{whiteSpace: "pre-wrap"}}>{created.install}</pre></div> : null}

      {data.targets.length ? <>
        <h4>Что проверяется</h4>
        <table className="table"><thead><tr><th>Адрес</th>{data.probes.map((p: any) => <th key={p.id}>{p.name}</th>)}</tr></thead>
          <tbody>{data.targets.map((t: any) => <tr key={t.target}><td>{t.label}<div className="muted">{t.target}</div></td>
            {data.probes.map((p: any) => { const r = t.results?.[p.id]; return <td key={p.id}>{!r ? "—" : r.ok ? `ok · ${r.ms} мс` : `нет (${r.fails}) ${r.error || ""}`}</td>; })}</tr>)}</tbody></table>
      </> : null}
    </div>
  );
}
