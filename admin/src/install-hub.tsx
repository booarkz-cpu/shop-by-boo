import React, {useEffect, useState} from "react";
import {EmptyState, LoadState} from "./components/ui/state";
import {stepUp} from "./stepUp";

const API = process.env.NEXT_PUBLIC_API_URL || "";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const post = (body?: any): RequestInit => ({method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});
// Modules planned right here (the others need more input and open «Установка Remnawave → Модули серверов»).
const DIRECT = ["transports", "node_port", "hardening", "watchdog", "node_guard", "swap", "mss_clamp", "sni_scan", "mtproto", "geo_files"];
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
    if (op.action.kind === "tab" && op.action.tab === "install") {
      document.querySelector("[data-install-anti]")?.scrollIntoView({behavior: "smooth"}); return;
    }
    if (op.action.kind === "tab") return navigate(op.action.tab);
    if (op.action.name === "restore_files") {
      document.querySelector("[data-install-snapshots]")?.scrollIntoView({behavior: "smooth"});
      return toast("Выберите снапшот файлов в «Снапшоты серверов» и нажмите «Восстановить»");
    }
    if (op.action.kind === "action") return setActive(op);
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
    {active && state && active.action.name === "change_domain" && <DomainChange state={state} request={request} toast={toast} onClose={() => setActive(null)}/>}
    {active && state && active.action.kind === "action" && active.action.name !== "change_domain" && <ActionPlan title={active.title} text={active.text} state={state} request={request} toast={toast}
      body={{action: active.action.name}} onClose={() => setActive(null)}/>}
    {active && state && active.action.kind === "module" && <ModulePlan op={active} state={state} request={request} toast={toast} onClose={() => setActive(null)}/>}
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
    <AntiCensorship request={request} onFix={(id: string) => { const op = data.operations.find((o: any) => o.id === id); if (op) open(op); }}/>
    <Snapshots request={request} toast={toast} state={state}/>
    {state?.installation_id && <DangerZone state={state} request={request} toast={toast}/>}
  </div>;
}

const COMPONENTS: Record<string, string> = {panel: "Панель Remnawave", subscription_page: "Страница подписки", proxy: "Caddy (HTTPS панели и подписки)",
  node: "Нода", selfsteal: "Сайт SelfSteal", xray_checker: "Xray Checker"};

/** A plan of an installation action (snapshot, removal of a component) — «Запустить» asks for 2FA. */
function ActionPlan({title, text, state, request, toast, body, onClose, danger}: any) {
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  async function make() {
    setError("");
    try { setPlan(await request(`/api/admin/rw/installations/${state.installation_id}/actions`, post(body))); } catch (e: any) { setError(e.message); }
  }
  async function run() {
    setError("");
    try { await request(`/api/admin/rw/installations/${plan.id}/approve`, post({plan_sha256: plan.plan_sha256}));
      toast(`«${title}» запущено: журнал шагов — в «Установка Remnawave»`); onClose(); }
    catch (e: any) { setError(e.message); }
  }
  return <section className={`card ${danger ? "danger" : ""}`} data-install-action={body.action}>
    <h4>{title} — {state.server.name}</h4><p className="muted">{text}</p>
    {error && <div role="alert" className="error">{error}</div>}
    {!plan ? <div className="toolbar"><button className="primary" onClick={make}>Составить план</button><button onClick={onClose}>Отмена</button></div>
      : <div data-install-plan-steps><ol>{plan.plan.steps.map((s: any) => <li key={s.position}>{s.title}</li>)}</ol>
        <div className="toolbar"><button className={danger ? "danger" : "primary"} onClick={run}>Запустить</button><button onClick={() => setPlan(null)}>Изменить</button></div></div>}
  </section>;
}

/** v28.97.0 (N7): «Сменить домен панели» — the new domain, and whether the former one keeps serving subscriptions. */
function DomainChange({state, request, toast, onClose}: any) {
  const [domain, setDomain] = useState("");
  const [keep, setKeep] = useState(true);
  const [ready, setReady] = useState(false);
  const current = state.panel_domain;
  if (!current) return <section className="card" data-install-domain><p className="muted">На этом сервере нет панели Remnawave.</p>
    <button onClick={onClose}>Закрыть</button></section>;
  const value = domain.trim().toLowerCase();
  return <section className="card" data-install-domain>
    <h4>Сменить домен панели — {state.server.name}</h4>
    <p>Сейчас: <b>{current}</b>{state.panel_domain_aliases.length > 0 && <> · прежние, ещё работают: {state.panel_domain_aliases.join(", ")}</>}</p>
    {!ready ? <>
      <ol className="muted">
        <li>Добавьте у регистратора A-запись нового домена на {state.server.host} и подождите, пока она разойдётся.</li>
        <li>Оставьте прежний домен: ссылки подписок, уже добавленные клиентами в приложения, продолжат работать{state.separate_subpage ? " (у вас отдельная страница подписки — её ссылки не меняются)" : ""}.</li>
        <li>После смены нажмите «Подключить магазин» у установки в «Установка Remnawave», чтобы магазин ходил в панель по новому домену.</li>
      </ol>
      <label>Новый домен<input value={domain} onChange={e => setDomain(e.target.value)} placeholder="panel2.example.com" data-domain-new/></label>
      <label className="check"><input type="checkbox" checked={keep} onChange={e => setKeep(e.target.checked)} data-domain-keep/> Оставить {current} для подписок и API магазина (переадресация остального)</label>
      {state.panel_domain_aliases.length > 0 && <button onClick={() => { setDomain(current); setKeep(false); setReady(true); }} data-domain-drop>Прежние домены больше не нужны</button>}
      <div className="toolbar"><button className="primary" disabled={!value || value === current} onClick={() => setReady(true)}>Дальше</button><button onClick={onClose}>Отмена</button></div>
    </> : <ActionPlan title="Смена домена панели" text={value === current ? `Убрать прежние домены: ${state.panel_domain_aliases.join(", ")}` : `${current} → ${value}`}
      state={state} request={request} toast={toast} body={{action: "change_domain", new_panel_domain: value, keep_old_domain: keep}}
      onClose={() => { setReady(false); onClose(); }}/>}
  </section>;
}

function Snapshots({request, toast, state}: any) {
  const [restore, setRestore] = useState<string>("");
  const [list, setList] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<any>(null);
  useEffect(() => { request("/api/admin/install/snapshots-schedule").then(setPlan).catch(() => {}); }, []);
  async function saveSchedule() {
    setError("");
    try { setPlan(await request("/api/admin/install/snapshots-schedule", {method: "PUT", body: JSON.stringify({enabled: plan.enabled, time: plan.time, telegram: plan.telegram})}));
      toast(plan.enabled ? `Снапшоты каждый день в ${plan.time} МСК` : "Ежедневные снапшоты выключены"); }
    catch (e: any) { setError(e.message); }
  }
  const load = () => request("/api/admin/install/snapshots").then((x: any) => setList(x.snapshots)).catch((e: any) => setError(e.message));
  useEffect(() => { load(); }, []);
  async function download(name: string) {
    setError("");
    const url = `${API}/api/admin/install/snapshots/${encodeURIComponent(name)}`;
    let r = await fetch(url, {credentials: "include"});
    if (r.status === 428 && await stepUp((p, o) => request(p, o))) r = await fetch(url, {credentials: "include"});
    if (!r.ok) { setError(r.status === 428 ? "Скачивание не подтверждено" : `Не скачано (HTTP ${r.status})`); return; }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await r.blob());
    link.download = name.replace(/\.enc$/, "");
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    toast("Снапшот скачан");
  }
  return <section className="card" data-install-snapshots>
    <h4>Снапшоты серверов</h4>
    <p className="muted">Зашифрованы в магазине (последние 5 на сервер). Скачивание — с подтверждением 2FA; файлы — tar.gz, база панели — pg_dump.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {plan && <div className="toolbar" data-install-schedule>
      <label className="inline"><input type="checkbox" checked={plan.enabled} onChange={e => setPlan({...plan, enabled: e.target.checked})}/> Каждый день</label>
      <label>в (МСК)<input type="time" value={plan.time} onChange={e => setPlan({...plan, time: e.target.value})}/></label>
      <label className="inline"><input type="checkbox" checked={plan.telegram} onChange={e => setPlan({...plan, telegram: e.target.checked})}/> и в Telegram (чат и пароль — «Резервные копии»)</label>
      <button onClick={saveSchedule}>Сохранить</button>
      {plan.state?.last && <span className="muted">Последний запуск: {new Date(plan.state.last.at).toLocaleString("ru-RU")}
        {plan.state.last.sent ? `, в Telegram: ${plan.state.last.sent}` : ""}{plan.state.last.errors?.length ? `, замечания: ${plan.state.last.errors.join("; ")}` : ""}</span>}
    </div>}
    {list === null ? <p className="muted">Загрузка…</p> : list.length === 0 ? <p className="muted">Снапшотов пока нет: карточка «Снапшот сервера → скачать».</p> :
      <div className="table-wrap"><table><thead><tr><th>Когда</th><th>Сервер</th><th>Что</th><th>Размер</th><th/></tr></thead>
        <tbody>{list.map(s => <tr key={s.name}><td>{new Date(s.created_at).toLocaleString("ru-RU")}</td><td>#{s.server_id}</td>
          <td>{s.kind === "files" ? "Файлы компонентов" : "База панели"}</td><td>{(s.size / 1024).toFixed(0)} КБ</td>
          <td className="actions"><button onClick={() => download(s.name)}>Скачать</button>
            {s.kind === "files" && state?.installation_id && s.server_id === state.server.id &&
              <button onClick={() => setRestore(s.name)} data-restore={s.name}>Восстановить</button>}</td></tr>)}</tbody></table></div>}
    {restore && state && <ActionPlan danger title="Экстренное восстановление файлов" state={state} request={request} toast={toast}
      text={`Файлы компонентов вернутся из снапшота ${restore.replace(/\.enc$/, "")}; текущие сначала упакуются в копию на сервере и вернутся при ошибке. Затем компоненты перезапустятся. «Запустить» спросит 2FA.`}
      body={{action: "restore_files", snapshot: restore}} onClose={() => setRestore("")}/>}
  </section>;
}

/** «Опасная зона»: one component off the server, or the whole installation — only after typing the server's name, then 2FA. */
function DangerZone({state, request, toast}: any) {
  const [what, setWhat] = useState("");
  const [typed, setTyped] = useState("");
  const [open, setOpen] = useState<any>(null);
  const confirmed = typed.trim() === state.server.name;
  const choices = Object.entries(COMPONENTS).filter(([k]) => k !== "proxy" || state.roles.includes("panel") || state.roles.includes("subscription_page"));
  return <section className="card danger" data-install-danger>
    <h4>Опасная зона</h4>
    <p className="muted">Удаление компонента останавливает и убирает его контейнеры; тома, файлы и копии остаются, вернуть — «Переустановить» установку.
      Перед удалением панели снимается копия её базы. «Очистить сервер» — удалить всю установку мастера с этого сервера.</p>
    <div className="grid-form">
      <label>Что удалить<select value={what} onChange={e => { setWhat(e.target.value); setOpen(null); }} data-danger-what>
        <option value="">— выберите —</option>{choices.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
        <option value="all">Очистить сервер (вся установка)</option></select></label>
      <label>Введите имя сервера «{state.server.name}»<input value={typed} onChange={e => setTyped(e.target.value)} data-danger-confirm/></label>
    </div>
    <button className="danger" disabled={!what || !confirmed} onClick={() => setOpen(what === "all" ? {action: "remove"} : {action: "remove_component", component: what})}>
      Составить план удаления</button>
    {open && <ActionPlan danger title={what === "all" ? "Очистить сервер" : `Удалить: ${COMPONENTS[what]}`} text="Проверьте шаги; «Запустить» спросит подтверждение 2FA."
      state={state} request={request} toast={toast} body={open} onClose={() => { setOpen(null); setTyped(""); setWhat(""); }}/>}
  </section>;
}

function ModulePlan({op, state, request, toast, onClose}: any) {
  const name = op.action.module;
  const [enabled, setEnabled] = useState(true);
  const [rate, setRate] = useState("150");
  const [ports, setPorts] = useState("443, 4443, 8443, 2053");
  const [guardMode, setGuardMode] = useState("enforce");
  const [swap, setSwap] = useState("1024");
  const [mtPort, setMtPort] = useState("9443");
  const [mtDomain, setMtDomain] = useState("www.cloudflare.com");
  const [proxies, setProxies] = useState<any[]>([]);
  const [plan, setPlan] = useState<any>(null);
  useEffect(() => {
    if (name === "mtproto") request("/api/admin/install/mtproto").then((x: any) => setProxies(x.proxies.filter((p: any) => p.server_id === state.server.id)))
      .catch(() => setProxies([]));
  }, [name, state.server.id]);
  const [error, setError] = useState("");
  function module() {
    const m: any = {name, enabled};
    const sid = state.server.id;
    if (name === "transports") Object.assign(m, {enabled: true, transports: enabled ? ["xhttp", "grpc", "hysteria2", "tls"] : [], fingerprint: "firefox"});
    if (name === "hardening") Object.assign(m, {enabled: true, server_ids: [sid], hardening: enabled ? {fail2ban: true, upgrades: true, bbr: true, admin_ips: []}
      : {fail2ban: false, upgrades: false, bbr: false, admin_ips: []}});
    if (["watchdog", "node_guard", "swap", "mss_clamp", "node_port", "sni_scan", "mtproto"].includes(name)) m.server_ids = [sid];
    if (name === "mtproto" && enabled) Object.assign(m, {mtproto_port: Number(mtPort), mtproto_domain: mtDomain.trim().toLowerCase()});
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
      {name === "geo_files" && <p className="muted wide">Списки обновляются у источника каждые 6 часов: «Включить» ещё раз ставит последнюю сборку.
        В правилах маршрутизации — <code>ext:ru-geosite.dat:ru-blocked</code>, <code>ext:ru-geoip.dat:ru-blocked</code>, <code>ext:ru-geosite.dat:ru-available-only-inside</code>.</p>}
      {name === "mtproto" && enabled && <>
        <label>Порт TCP<input type="number" min={1024} max={65535} value={mtPort} onChange={e => { setMtPort(e.target.value); setPlan(null); }}/></label>
        <label>Маскировка под сайт<input value={mtDomain} onChange={e => { setMtDomain(e.target.value); setPlan(null); }}/></label></>}
      {name === "swap" && enabled && <label>Размер, МБ<input type="number" min={256} max={16384} step={256} value={swap} onChange={e => { setSwap(e.target.value); setPlan(null); }}/></label>}
    </div>
    {name === "mtproto" && proxies.length > 0 && <div data-mtproto-links>{proxies.map(p => <p key={p.server_id}>
      Прокси работает: TCP {p.port}, маскировка под {p.domain}. Ссылка для клиентов: <a href={p.https} target="_blank" rel="noreferrer">{p.https}</a>{" "}
      <button className="link" onClick={() => { navigator.clipboard?.writeText(p.tg); toast("Ссылка tg:// скопирована"); }}>Скопировать tg://</button></p>)}</div>}
    {!plan ? <div className="toolbar"><button className="primary" onClick={make}>Составить план</button><button onClick={onClose}>Отмена</button></div>
      : <div data-install-plan-steps><ol>{plan.plan.steps.map((s: any) => <li key={s.position}>{s.title}</li>)}</ol>
        <div className="toolbar"><button className="primary" onClick={run}>Запустить</button><button onClick={() => setPlan(null)}>Изменить</button></div></div>}
  </section>;
}

/** «Анти-РКН» (v28.93.0): what the shop knows about every node as a checklist; «Исправить» opens the card that fixes it. */
function AntiCensorship({request, onFix}: {request: Request; onFix: (id: string) => void}) {
  const [nodes, setNodes] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/install/anti-censorship").then((x: any) => setNodes(x.nodes)).catch((e: any) => setError(e.message)); }, []);
  return <section className="card" data-install-anti>
    <h4>Анти-РКН: чек-лист нод</h4>
    <p className="muted">Что магазин знает о каждой ноде; по сети здесь ничего не проверяется — для этого «Проверить» в «SelfSteal».</p>
    {error && <div role="alert" className="error">{error}</div>}
    {nodes === null ? <p className="muted">Загрузка…</p> : nodes.length === 0 ? <p className="muted">Нод мастера пока нет.</p> :
      nodes.map(n => <details key={n.key} data-anti-node={n.key}><summary><b>{n.name}</b> {n.address} — {n.done} из {n.total}</summary>
        <ul className="checklist">{n.items.map((i: any) => <li key={i.key} data-ok={i.ok}>{i.ok ? "✅" : "⚠️"} {i.title}
          {!i.ok && <button className="link" onClick={() => onFix(i.fix)}>Исправить</button>}</li>)}</ul></details>)}
  </section>;
}
