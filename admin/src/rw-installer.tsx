import React, {useEffect, useRef, useState} from "react";
import {EmptyState, LoadState, SuccessNote} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (text: string) => void};
const API = "/api/admin/rw";
const post = (body?: unknown): RequestInit => ({method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});

const MODE_HINTS: Record<string, string> = {
  panel_node: "Панель, база, Valkey, Caddy (HTTPS) и нода на одном сервере. Нода сразу появляется в панели.",
  panel: "Только панель с базой, Valkey и Caddy. Ноды добавляются позже режимом «Добавить ноду».",
  node: "Одна нода для панели, к которой уже подключён магазин (REMNAWAVE_URL и REMNAWAVE_TOKEN).",
  panel_subpage: "Панель и страница подписки на одном сервере, у каждой свой домен.",
  subpage: "Страница подписки на отдельном сервере для панели, подключённой к магазину.",
  distributed: "Панель на одном сервере, ноды — на других, страница подписки — на отдельном или на сервере панели.",
  add_node: "Несколько нод сразу к панели, подключённой к магазину.",
};
const STATUS: Record<string, string> = {
  new: "не проверен", ready: "готов", check_failed: "проверка не пройдена", unreachable: "нет связи", installed: "установлено",
  removed: "удалено", planned: "план", queued: "в очереди", running: "выполняется", succeeded: "готово", failed: "ошибка",
  cancelled: "отменено", pending: "ждёт", done: "выполнен", skipped: "пропущен", rolled_back: "отменён (откат)",
};
const ROLE: Record<string, string> = {panel: "панель", node: "нода", subscription_page: "страница подписки"};
const NEED_PANEL = ["panel_node", "panel", "panel_subpage", "distributed"];

function Checks({checks}: {checks: any[]}) {
  if (!checks?.length) return null;
  return <ul className="checks" data-rw-checks>{checks.map((c: any) =>
    <li key={c.key} data-status={c.status}><b>{c.status === "ok" ? "✓" : c.status === "warn" ? "!" : "✗"}</b> {c.detail}</li>)}</ul>;
}

/** «Серверы → Установка Remnawave» (v28.66.0, stage 10): the server registry, the installation wizard in seven
 *  modes, the plan to approve, and the Deployment Agent's jobs with step logs. Nothing runs on a server before the
 *  administrator approves the exact plan shown (its SHA-256); every command is a fixed script of the backend. */
export function RwInstaller({request, toast}: Props) {
  const [meta, setMeta] = useState<any>(null);
  const [servers, setServers] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [opened, setOpened] = useState<number | null>(null);
  const load = () => {
    setError("");
    Promise.all([request(`${API}/meta`), request(`${API}/servers`), request(`${API}/installations`)])
      .then(([m, s, j]) => { setMeta(m); setServers(s.servers); setJobs(j.installations); })
      .catch((e: any) => setError(e.message));
  };
  useEffect(load, []);
  const active = jobs.some(j => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => request(`${API}/installations`).then(j => setJobs(j.installations)).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [active]);
  if (!meta) return <LoadState error={error} onRetry={load} label="Загрузка мастера установки…"/>;
  return <div data-rw-installer>
    <Registry servers={servers} request={request} toast={toast} reload={load}/>
    <Wizard meta={meta} servers={servers} request={request} toast={toast} onQueued={(id: number) => { setOpened(id); load(); }}/>
    <Jobs jobs={jobs} servers={servers} request={request} toast={toast} opened={opened} setOpened={setOpened} reload={load}/>
  </div>;
}

function Registry({servers, request, toast, reload}: {servers: any[]; request: Request; toast: (t: string) => void; reload: () => void}) {
  const empty = {name: "", host: "", ssh_port: "22", ssh_user: "root", auth_method: "key", private_key: "", password: "", purpose: ["panel", "node"] as string[]};
  const [form, setForm] = useState(empty);
  const [scan, setScan] = useState<any>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [shown, setShown] = useState<number | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const set = (k: string) => (e: any) => { setForm({...form, [k]: e.target.value}); if (k === "host" || k === "ssh_port") { setScan(null); setConfirmed(false); } };
  const purpose = (role: string) => (e: any) => setForm({...form, purpose: e.target.checked ? [...form.purpose, role] : form.purpose.filter(r => r !== role)});
  async function getFingerprint() {
    setError(""); setBusy("scan");
    try { setScan(await request(`${API}/servers/scan`, post({host: form.host, ssh_port: Number(form.ssh_port)}))); setConfirmed(false); }
    catch (e: any) { setError(e.message); } finally { setBusy(""); }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setError(""); setBusy("save");
    try {
      await request(`${API}/servers`, post({name: form.name, host: form.host, ssh_port: Number(form.ssh_port), ssh_user: form.ssh_user,
        auth_method: form.auth_method, ...(form.auth_method === "key" ? {private_key: form.private_key} : {password: form.password}),
        host_key_fingerprint: scan.fingerprint, purpose: form.purpose}));
      toast(`Сервер ${form.name} добавлен — нажмите «Проверить»`); setForm(empty); setScan(null); setConfirmed(false); reload();
    } catch (err: any) { setError(err.message); } finally { setBusy(""); }
  }
  async function check(id: number) {
    setBusy(`check-${id}`); setError("");
    try { const s = await request(`${API}/servers/${id}/check`, post()); toast(`${s.name}: ${STATUS[s.status] || s.status}`); setShown(id); reload(); }
    catch (e: any) { setError(e.message); reload(); } finally { setBusy(""); }
  }
  async function remove(id: number) {
    setError("");
    try { await request(`${API}/servers/${id}`, {method: "DELETE"}); toast("Сервер удалён из реестра"); setRemoving(null); reload(); }
    catch (e: any) { setError(e.message); }
  }
  return <div className="card" data-rw-registry>
    <h3>Серверы для Remnawave</h3>
    <p className="muted">VPS, на которые мастер ставит панель, ноды и страницу подписки. Ключ или пароль SSH хранятся зашифрованными и не показываются.
      Вход только по сохранённому отпечатку ключа сервера: сверьте его с тем, что показывает хостинг или команда <code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code> на сервере.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {servers.length === 0 ? <EmptyState title="Серверов пока нет" hint="Добавьте VPS ниже: адрес, пользователь и ключ SSH."/> :
      <div className="table-wrap"><table>
        <thead><tr><th>Сервер</th><th>Адрес</th><th>Состояние</th><th>Система</th><th>Ресурсы</th><th>Компоненты</th><th></th></tr></thead>
        <tbody>{servers.map(s => <React.Fragment key={s.id}><tr data-rw-server={s.name}>
          <td><b>{s.name}</b><div className="muted">{(s.purpose || []).map((r: string) => ROLE[r]).join(", ")}</div></td>
          <td>{s.ssh_user}@{s.host}:{s.ssh_port}<div className="muted mono">{s.host_key_fingerprint}</div></td>
          <td data-status={s.status}>{STATUS[s.status] || s.status}<div className="muted">{s.last_checked_at ? new Date(s.last_checked_at).toLocaleString() : "не проверялся"}</div></td>
          <td>{s.os || "—"}{s.arch ? ` · ${s.arch}` : ""}</td>
          <td>{s.cpu_cores ? `${s.cpu_cores} CPU · ${s.ram_mb} МБ · ${s.disk_gb} ГБ свободно` : "—"}</td>
          <td>{(s.roles || []).map((r: string) => ROLE[r]).join(", ") || "—"}</td>
          <td className="actions">
            <button onClick={() => check(s.id)} disabled={busy === `check-${s.id}`}>{busy === `check-${s.id}` ? "Проверка…" : "Проверить"}</button>
            {s.checks?.length > 0 && <button onClick={() => setShown(shown === s.id ? null : s.id)}>{shown === s.id ? "Скрыть" : "Отчёт"}</button>}
            {removing === s.id ? <button className="danger" onClick={() => remove(s.id)}>Точно удалить</button>
              : <button onClick={() => setRemoving(s.id)} disabled={(s.roles || []).length > 0} title={(s.roles || []).length ? "Сначала «Удаление» в мастере" : ""}>Удалить</button>}
          </td></tr>
          {shown === s.id && <tr><td colSpan={7}><Checks checks={s.checks}/></td></tr>}
        </React.Fragment>)}</tbody>
      </table></div>}
    <form onSubmit={save} className="grid-form" data-rw-add-server>
      <h4>Добавить сервер</h4>
      <label>Название<input value={form.name} onChange={set("name")} required minLength={2} maxLength={80} placeholder="fi-hel-1"/></label>
      <label>IP-адрес или имя хоста<input value={form.host} onChange={set("host")} required maxLength={253} placeholder="203.0.113.10"/></label>
      <label>Порт SSH<input type="number" min={1} max={65535} value={form.ssh_port} onChange={set("ssh_port")} required/></label>
      <label>Пользователь<input value={form.ssh_user} onChange={set("ssh_user")} required pattern="[a-z_][a-z0-9_-]*"/></label>
      <label>Способ входа<select value={form.auth_method} onChange={set("auth_method")}>
        <option value="key">Ключ SSH (рекомендуется)</option><option value="password">Пароль</option></select></label>
      {form.auth_method === "key"
        ? <label className="wide">Закрытый ключ (Ed25519, ECDSA или RSA, без пароля)<textarea value={form.private_key} onChange={set("private_key")} rows={4} required
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" spellCheck={false} autoComplete="off"/></label>
        : <label>Пароль<input type="password" value={form.password} onChange={set("password")} required autoComplete="new-password"/></label>}
      <fieldset className="wide"><legend>Назначение</legend>
        {Object.entries(ROLE).map(([k, v]) => <label key={k} className="inline"><input type="checkbox" checked={form.purpose.includes(k)} onChange={purpose(k)}/> {v}</label>)}
      </fieldset>
      <div className="wide">
        <button type="button" onClick={getFingerprint} disabled={!form.host || busy === "scan"}>{busy === "scan" ? "Подключение…" : "Получить отпечаток ключа сервера"}</button>
        {scan && <div data-rw-fingerprint><p>Ключ сервера {scan.key_type}: <code>{scan.fingerprint}</code></p>
          <label className="inline"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/> Отпечаток совпадает с показанным хостингом или командой на сервере</label></div>}
      </div>
      <div className="wide"><button className="primary" disabled={!scan || !confirmed || busy === "save"}>Сохранить сервер</button></div>
    </form>
  </div>;
}

function Wizard({meta, servers, request, toast, onQueued}: {meta: any; servers: any[]; request: Request; toast: (t: string) => void; onQueued: (id: number) => void}) {
  const [f, setF] = useState<any>({mode: "panel_node", panel_server_id: "", node_server_ids: [] as string[], subpage_server_id: "", panel_domain: "",
    sub_domain: "", node_domain: "", tls: "acme", acme_email: "", node_port: "2222", node_name: "node", country_code: "XX", firewall: true, panel_access: "open"});
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => { setF({...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value}); setPlan(null); };
  const usable = servers.filter(s => s.status !== "new" && s.status !== "unreachable");
  const m = f.mode;
  const needPanel = NEED_PANEL.includes(m);
  const needNodes = ["node", "add_node", "distributed"].includes(m);
  const needSub = ["panel_subpage", "subpage", "distributed"].includes(m);
  const pick = (k: string, label: string, required: boolean) => <label>{label}<select value={f[k]} onChange={set(k)} required={required}>
    <option value="">{required ? "— выберите —" : "— нет —"}</option>{usable.map(s => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}</select></label>;
  function body() {
    const n = (v: string) => v ? Number(v) : null;
    return {mode: m, panel_server_id: needPanel ? n(f.panel_server_id) : null,
      node_server_ids: m === "panel_node" ? [] : needNodes ? f.node_server_ids.map(Number) : [],
      subpage_server_id: m === "panel_subpage" ? null : needSub ? n(f.subpage_server_id) : null,
      panel_domain: needPanel ? f.panel_domain || null : null, sub_domain: needSub ? f.sub_domain || null : null,
      node_domain: f.node_domain || null, tls: f.tls, acme_email: f.acme_email || null, node_port: Number(f.node_port),
      node_name: f.node_name, country_code: f.country_code.toUpperCase(), firewall: f.firewall,
      panel_access: needPanel ? f.panel_access : "open"};
  }
  async function makePlan(e: React.FormEvent) {
    e.preventDefault(); setError(""); setBusy(true);
    try { setPlan(await request(`${API}/installations/plan`, post(body()))); }
    catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function approve() {
    setError(""); setBusy(true);
    try { const out = await request(`${API}/installations/${plan.id}/approve`, post({plan_sha256: plan.plan_sha256}));
      toast(`Установка №${out.id} запущена`); setPlan(null); onQueued(out.id); }
    catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function drop() {
    try { await request(`${API}/installations/${plan.id}/cancel`, post()); } catch { /* the plan stays as «план» */ }
    setPlan(null);
  }
  return <div className="card" data-rw-wizard>
    <h3>Мастер установки Remnawave</h3>
    <p className="muted">Панель {meta.images.panel.split("@")[0]}, нода и страница подписки — образы закреплены по SHA-256 и проверены живыми тестами.
      HTTPS даёт Caddy на сервере Remnawave (порты 80 и 443 этого сервера должны быть свободны); общий Caddy магазина не меняется.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {usable.length === 0 && <EmptyState title="Нет проверенных серверов" hint="Добавьте сервер выше и нажмите «Проверить»."/>}
    <form onSubmit={makePlan} className="grid-form">
      <label className="wide">Режим<select value={m} onChange={set("mode")} data-rw-mode>{meta.modes.map((x: any) => <option key={x.key} value={x.key}>{x.title}</option>)}</select>
        <span className="muted">{MODE_HINTS[m]}</span></label>
      {needPanel && pick("panel_server_id", m === "panel_node" ? "Сервер (панель и нода)" : "Сервер панели", true)}
      {needPanel && <label>Домен панели<input value={f.panel_domain} onChange={set("panel_domain")} required placeholder="panel.example.com"/></label>}
      {needNodes && <label className="wide">Серверы нод<select multiple value={f.node_server_ids} required size={Math.min(5, Math.max(2, usable.length))}
        onChange={e => { setF({...f, node_server_ids: Array.from(e.target.selectedOptions).map(o => o.value)}); setPlan(null); }}>
        {usable.map(s => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}</select></label>}
      {needSub && m !== "panel_subpage" && pick("subpage_server_id", "Сервер страницы подписки", m === "subpage")}
      {needSub && <label>Домен страницы подписки<input value={f.sub_domain} onChange={set("sub_domain")} required={m !== "distributed" || !!f.subpage_server_id} placeholder="sub.example.com"/></label>}
      {needPanel && <label>Доступ к панели<select value={f.panel_access} onChange={set("panel_access")}>
        <option value="open">Открыт по адресу панели</option><option value="cookie">Только по секретной ссылке (страницы панели скрыты)</option></select></label>}
      {(needPanel || needSub) && <label>Сертификат<select value={f.tls} onChange={set("tls")}>
        <option value="acme">Let's Encrypt (домены уже указывают на сервер)</option><option value="internal">Внутренний Caddy (проверка, без публичного DNS)</option></select></label>}
      {(needPanel || needSub) && f.tls === "acme" && <label>Email для Let's Encrypt<input type="email" value={f.acme_email} onChange={set("acme_email")} required/></label>}
      {(needNodes || m === "panel_node") && <>
        <label>Порт ноды<input type="number" min={1024} max={65535} value={f.node_port} onChange={set("node_port")}/></label>
        <label>Имя ноды в панели<input value={f.node_name} onChange={set("node_name")} pattern="[A-Za-z0-9_-]{3,24}"/></label>
        <label>Страна (код)<input value={f.country_code} onChange={set("country_code")} pattern="[A-Za-z]{2}" maxLength={2}/></label>
        <label className="inline"><input type="checkbox" checked={f.firewall} onChange={set("firewall")}/> Открыть порт ноды только для адреса панели (если включён ufw)</label>
      </>}
      <div className="wide"><button className="primary" disabled={busy || usable.length === 0}>Составить план</button></div>
    </form>
    {plan && <div className="plan" data-rw-plan>
      <h4>{plan.plan.title}: что произойдёт</h4>
      <p className="muted">Панель: {plan.plan.panel}. План №{plan.id}, SHA-256 <code>{plan.plan_sha256.slice(0, 16)}…</code></p>
      {Object.entries(plan.plan.servers).map(([id, s]: any) => <div key={id}><b>{s.name}</b> ({s.host}) — {s.roles.map((r: string) => ROLE[r]).join(", ")}
        <ul>{s.changes.map((c: string, i: number) => <li key={i}>{c}</li>)}</ul></div>)}
      <ol data-rw-plan-steps>{plan.plan.steps.map((s: any) => <li key={s.position}>{s.title}</li>)}</ol>
      <details><summary>Образы</summary><ul>{Object.entries(plan.plan.images).map(([k, v]: any) => <li key={k}><code>{v}</code></li>)}</ul></details>
      <button className="primary" onClick={approve} disabled={busy}>Запустить по этому плану</button> <button onClick={drop}>Отменить план</button>
    </div>}
  </div>;
}

const ACTIONS: [string, string, boolean][] = [["diagnose", "Диагностика", false], ["update", "Обновить", true], ["restore", "Восстановить базу панели", true],
  ["reinstall", "Переустановить", true], ["remove", "Удалить", true]];

function Jobs({jobs, servers, request, toast, opened, setOpened, reload}: any) {
  const names = Object.fromEntries(servers.map((s: any) => [s.id, s.name]));
  return <div className="card" data-rw-jobs>
    <h3>Задачи Deployment Agent</h3>
    {jobs.length === 0 ? <EmptyState title="Задач ещё не было" hint="Составьте план в мастере и запустите его."/> :
      <div className="table-wrap"><table>
        <thead><tr><th>№</th><th>Задача</th><th>Серверы</th><th>Состояние</th><th>Прогресс</th><th>Начата</th><th>Завершена</th><th></th></tr></thead>
        <tbody>{jobs.map((j: any) => <React.Fragment key={j.id}><tr data-rw-job={j.id} data-status={j.status}>
          <td>{j.id}</td><td>{j.title}{j.source_installation_id ? <div className="muted">к установке №{j.source_installation_id}</div> : null}</td>
          <td>{j.server_ids.map((id: number) => names[id] || `#${id}`).join(", ")}</td>
          <td>{STATUS[j.status] || j.status}{j.current_step && <div className="muted">{j.current_step}</div>}{j.error && <div className="error">{j.error}</div>}</td>
          <td><progress max={100} value={j.progress}/> {j.progress}%</td>
          <td>{j.started_at ? new Date(j.started_at).toLocaleString() : "—"}</td><td>{j.finished_at ? new Date(j.finished_at).toLocaleString() : "—"}</td>
          <td><button onClick={() => setOpened(opened === j.id ? null : j.id)}>{opened === j.id ? "Скрыть" : "Журнал"}</button></td></tr>
          {opened === j.id && <tr><td colSpan={8}><JobDetail id={j.id} request={request} toast={toast} reload={reload}/></td></tr>}
        </React.Fragment>)}</tbody>
      </table></div>}
  </div>;
}

function JobDetail({id, request, toast, reload}: {id: number; request: Request; toast: (t: string) => void; reload: () => void}) {
  const [job, setJob] = useState<any>(null);
  const [error, setError] = useState("");
  const [creds, setCreds] = useState<any>(null);
  const [confirm, setConfirm] = useState("");
  const [staged, setStaged] = useState<any>(null);
  const [planned, setPlanned] = useState<any>(null);
  const live = useRef(true);
  const load = () => request(`${API}/installations/${id}`).then(x => { if (live.current) setJob(x); }).catch((e: any) => setError(e.message));
  useEffect(() => { live.current = true; load(); return () => { live.current = false; }; }, [id]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [job?.status]);
  if (!job) return <LoadState error={error} onRetry={load} label="Загрузка журнала…"/>;
  const act = async (fn: () => Promise<void>) => { setError(""); try { await fn(); } catch (e: any) { setError(e.message); } };
  const cancel = () => act(async () => { setJob(await request(`${API}/installations/${id}/cancel`, post())); reload(); });
  const action = (a: string, extra: Record<string, string> = {}) => act(async () => { setPlanned(await request(`${API}/installations/${id}/actions`, post({action: a, ...extra}))); setConfirm(""); });
  const runPlanned = () => act(async () => {
    const out = await request(`${API}/installations/${planned.id}/approve`, post({plan_sha256: planned.plan_sha256}));
    toast(`Задача №${out.id} запущена`); setPlanned(null); reload();
  });
  const showCreds = () => act(async () => setCreds(await request(`${API}/installations/${id}/credentials`, post())));
  const connect = () => act(async () => setStaged(await request(`${API}/installations/${id}/connect-shop`, post())));
  const apply = () => act(async () => {
    await request(`/api/admin/runtime-settings/changes/${staged.change.id}/apply`, post({expected_version: staged.change.base_version, fingerprint: staged.change.fingerprint}));
    toast("Магазин подключён к новой панели"); setStaged(null);
  });
  const isInstall = job.action === "install";
  return <div data-rw-job-detail={id}>
    {error && <div role="alert" className="error">{error}</div>}
    <ol className="steps">{job.steps.map((s: any) => <li key={s.id} data-status={s.status} data-kind={s.kind}>
      <b>{s.title}</b> — {STATUS[s.status] || s.status}
      {s.log && <pre className="log">{s.log}</pre>}</li>)}</ol>
    {["queued", "running"].includes(job.status) && <button onClick={cancel} disabled={job.cancel_requested}>
      {job.cancel_requested ? "Остановка после текущего шага…" : "Остановить и откатить"}</button>}
    {isInstall && job.status === "succeeded" && <div className="actions" data-rw-actions>
      {job.result?.panel_url && <a href={job.result.panel_url} target="_blank" rel="noreferrer">{job.result.panel_url}</a>}
      {job.params?.panel_server_id && <button onClick={showCreds}>Показать вход в панель</button>}
      {job.params?.panel_server_id && job.params?.tls === "acme" && <button onClick={connect}>Подключить магазин к этой панели</button>}
      {job.params?.panel_server_id && <button onClick={() => action("update", {panel_access: job.params?.panel_access === "cookie" ? "open" : "cookie"})}>
        {job.params?.panel_access === "cookie" ? "Открыть доступ к панели" : "Закрыть доступ к панели"}</button>}
      {ACTIONS.filter(([a]) => a !== "restore" || job.params?.panel_server_id).map(([a, label, risky]) =>
        risky && confirm !== a ? <button key={a} onClick={() => setConfirm(a)}>{label}</button>
          : <button key={a} className={risky ? "danger" : ""} onClick={() => action(a)}>{risky ? `Составить план: ${label.toLowerCase()}` : label}</button>)}
    </div>}
    {creds && <SuccessNote>Панель {creds.panel_url}: администратор <code>{creds.username}</code>, пароль <code>{creds.password}</code>.
      {creds.access_url ? <> Вход только по секретной ссылке: <code>{creds.access_url}</code> (откройте один раз — браузер запомнит доступ на 30 дней).</> : null} Просмотр записан в журнал действий.</SuccessNote>}
    {staged && <div data-rw-staged><p>Подготовлено изменение настроек: REMNAWAVE_URL и REMNAWAVE_TOKEN (токен не показывается).</p>
      <button className="primary" onClick={apply}>Применить</button> <button onClick={() => setStaged(null)}>Позже (в «Настройки → Параметры»)</button></div>}
    {planned && <div className="plan" data-rw-action-plan><h4>{planned.plan.title}</h4>
      <ol>{planned.plan.steps.map((s: any) => <li key={s.position}>{s.title}</li>)}</ol>
      <button className="primary" onClick={runPlanned}>Запустить</button> <button onClick={() => act(async () => { await request(`${API}/installations/${planned.id}/cancel`, post()); setPlanned(null); })}>Не запускать</button></div>}
  </div>;
}
