import React, {useEffect, useState} from "react";
import {EmptyState, LoadState} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const post = (body?: any): RequestInit => ({method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});
// Modules planned right here (the others need more input and open «Установка Remnawave → Модули серверов»).
const DIRECT = ["transports", "node_port", "hardening", "watchdog", "node_guard", "swap", "mss_clamp"];
const STEPS: [string, string][] = [["prepared", "Подготовьте сервер"], ["panel", "Установите панель или ноду"], ["domain", "Подключите домен"]];

/** «Установка» (v28.92.0, N7): every operation on the servers in one catalogue — each card does its job or opens the section that does. */
export function InstallHub({request, toast, navigate}: {request: Request; toast: (t: string) => void; navigate: (tab: string) => void}) {
  const [servers, setServers] = useState<any[] | null>(null);
  const [server, setServer] = useState("");
  const [data, setData] = useState<any>(null);
  const [mode, setMode] = useState<"simple" | "expert">("simple");
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/rw/servers").then((x: any) => { setServers(x.servers); if (x.servers[0]) setServer(String(x.servers[0].id)); })
    .catch((e: any) => setError(e.message)); }, []);
  useEffect(() => { setActive(null); request(`/api/admin/install/catalogue${server ? `?server_id=${server}` : ""}`).then(setData).catch((e: any) => setError(e.message)); }, [server]);
  if (!data || !servers) return <section className="card"><LoadState error={error} label="Загрузка каталога…"/></section>;
  const q = query.trim().toLowerCase();
  const ops = data.operations.filter((o: any) => (mode === "expert" || o.simple) && (!q || `${o.title} ${o.text}`.toLowerCase().includes(q)));
  const state = data.state;
  function open(op: any) {
    if (op.action.kind === "tab") return navigate(op.action.tab);
    if (op.action.kind === "install" || !DIRECT.includes(op.action.module)) return navigate("rwInstaller");
    setActive(op);
  }
  return <div data-install-hub>
    <section className="card">
      <h3>Установка</h3>
      <p className="muted">Все операции с серверами в одном месте: карточка «по SSH» меняет сервер планом с подтверждением и откатом,
        «без SSH» работает через панель или магазин. Модули ставятся в установку, где есть выбранный сервер.</p>
      {error && <div role="alert" className="error">{error}</div>}
      <div className="toolbar">
        <label>Сервер<select value={server} onChange={e => setServer(e.target.value)} data-install-server>
          {servers.length === 0 && <option value="">— серверов нет —</option>}
          {servers.map(s => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}</select></label>
        <div className="segmented" role="group" aria-label="Режим">
          <button className={mode === "simple" ? "primary" : ""} onClick={() => setMode("simple")} data-install-mode="simple">Простой</button>
          <button className={mode === "expert" ? "primary" : ""} onClick={() => setMode("expert")} data-install-mode="expert">Экспертный</button>
        </div>
        <label>Поиск<input value={query} onChange={e => setQuery(e.target.value)} placeholder={`среди ${data.total} операций`} data-install-search/></label>
      </div>
      {servers.length === 0 && <EmptyState title="Нет серверов" hint="Добавьте VPS в «Установка Remnawave» — по SSH-ключу или паролю."
        action={<button onClick={() => navigate("rwInstaller")}>Добавить сервер</button>}/>}
      {state && <ol className="steps" data-install-steps>{STEPS.map(([key, title], i) => <li key={key} data-done={state.steps[key]}>
        {state.steps[key] ? "✅" : `${i + 1}.`} {title}</li>)}</ol>}
      {state && !state.installation_id && <p className="muted">На этом сервере ещё нет установки мастера: модули станут доступны после неё.</p>}
    </section>
    {active && state && <ModulePlan op={active} state={state} request={request} toast={toast} onClose={() => setActive(null)}/>}
    {Object.entries(data.groups).map(([gid, gtitle]: any) => {
      const list = ops.filter((o: any) => o.group === gid);
      if (!list.length) return null;
      return <section className="card" key={gid} data-install-group={gid}><h4>{gtitle}</h4><div className="cards">
        {list.map((o: any) => <div className="card" key={o.id} data-op={o.id}>
          <div className="toolbar"><b>{o.title}</b><span className={`badge ${o.ssh ? "" : "muted"}`}>{o.ssh ? "по SSH" : "без SSH"}</span></div>
          <p className="muted">{o.text}</p>
          <button className={o.action.kind === "tab" ? "" : "primary"} disabled={o.ready === false} title={o.ready === false ? "Сначала установка мастера на этом сервере (для нод — нода)" : ""}
            onClick={() => open(o)}>{o.action.kind === "tab" ? "Открыть" : "Установить"}</button>
        </div>)}</div></section>;
    })}
    {ops.length === 0 && <section className="card"><p className="muted">Ничего не найдено.</p></section>}
  </div>;
}

function ModulePlan({op, state, request, toast, onClose}: any) {
  const name = op.action.module;
  const [enabled, setEnabled] = useState(true);
  const [rate, setRate] = useState("150");
  const [ports, setPorts] = useState("443, 4443, 8443, 2053");
  const [guardMode, setGuardMode] = useState("enforce");
  const [swap, setSwap] = useState("1024");
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  function module() {
    const m: any = {name, enabled};
    const sid = state.server.id;
    if (name === "transports") Object.assign(m, {enabled: true, transports: enabled ? ["xhttp", "grpc", "hysteria2", "tls"] : [], fingerprint: "firefox"});
    if (name === "hardening") Object.assign(m, {enabled: true, server_ids: [sid], hardening: enabled ? {fail2ban: true, upgrades: true, bbr: true, admin_ips: []}
      : {fail2ban: false, upgrades: false, bbr: false, admin_ips: []}});
    if (["watchdog", "node_guard", "swap", "mss_clamp", "node_port"].includes(name)) m.server_ids = [sid];
    if (name === "node_guard") Object.assign(m, {guard_rate: Number(rate), guard_mode: guardMode,
      guard_ports: ports.split(/[\s,]+/).filter(Boolean).map(Number)});
    if (name === "swap") m.swap_mb = Number(swap);
    return m;
  }
  async function make() {
    setError("");
    try { setPlan(await request(`/api/admin/rw/installations/${state.installation_id}/actions`, post({action: "module", module: module()}))); }
    catch (e: any) { setError(e.message); }
  }
  async function run() {
    setError("");
    try { await request(`/api/admin/rw/installations/${plan.id}/approve`, post({plan_sha256: plan.plan_sha256}));
      toast(`«${op.title}» запущено: журнал шагов — в «Установка Remnawave»`); onClose(); }
    catch (e: any) { setError(e.message); }
  }
  return <section className="card" data-install-plan={name}>
    <h4>{op.title} — {state.server.name}</h4>
    <p className="muted">{op.text}</p>
    {error && <div role="alert" className="error">{error}</div>}
    <div className="grid-form">
      <label>Действие<select value={enabled ? "on" : "off"} onChange={e => { setEnabled(e.target.value === "on"); setPlan(null); }}>
        <option value="on">Включить</option><option value="off">{name === "transports" ? "Оставить только TCP + REALITY" : "Выключить"}</option></select></label>
      {name === "node_guard" && enabled && <>
        <label>Новых соединений в секунду с одного адреса<input type="number" min={5} max={5000} value={rate} onChange={e => { setRate(e.target.value); setPlan(null); }}/></label>
        <label>Порты<input value={ports} onChange={e => { setPorts(e.target.value); setPlan(null); }}/></label>
        <label>Режим<select value={guardMode} onChange={e => { setGuardMode(e.target.value); setPlan(null); }}>
          <option value="enforce">Банить на 10 минут</option><option value="observe">Только считать</option></select></label></>}
      {name === "swap" && enabled && <label>Размер, МБ<input type="number" min={256} max={16384} step={256} value={swap} onChange={e => { setSwap(e.target.value); setPlan(null); }}/></label>}
    </div>
    {!plan ? <div className="toolbar"><button className="primary" onClick={make}>Составить план</button><button onClick={onClose}>Отмена</button></div>
      : <div data-install-plan-steps><ol>{plan.plan.steps.map((s: any) => <li key={s.position}>{s.title}</li>)}</ol>
        <div className="toolbar"><button className="primary" onClick={run}>Запустить</button><button onClick={() => setPlan(null)}>Изменить</button></div></div>}
  </section>;
}
