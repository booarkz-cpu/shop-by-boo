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
  async function rotate(id: number, name: string) {
    if (!confirm(`Сменить SSH-ключ сервера ${name}? Магазин создаст новый ключ, проверит вход им и уберёт свой прежний ключ. Ключи владельца на сервере не трогаются.`)) return;
    setBusy(`rotate-${id}`); setError("");
    try {
      const s = await request(`${API}/servers/${id}/rotate-key`, post());
      toast(`${s.name}: новый ключ ${s.ssh_key?.fingerprint || ""}${s.rotation?.note ? " — " + s.rotation.note : ""}`); reload();
    } catch (e: any) { setError(e.message); } finally { setBusy(""); }
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
          <td>{s.ssh_user}@{s.host}:{s.ssh_port}<div className="muted mono" title="Отпечаток ключа сервера">{s.host_key_fingerprint}</div>
            <div className={s.ssh_key?.rotation_due ? "warn-text" : "muted"} data-ssh-key>{s.ssh_key?.managed
              ? `Ключ магазина ${s.ssh_key.fingerprint} · ${s.ssh_key.age_days ?? 0} дн.${s.ssh_key.rotation_due ? " — пора сменить" : ""}`
              : `Вход по ${s.auth_method === "password" ? "паролю" : "ключу"} владельца — смените на ключ магазина`}</div></td>
          <td data-status={s.status}>{STATUS[s.status] || s.status}<div className="muted">{s.last_checked_at ? new Date(s.last_checked_at).toLocaleString() : "не проверялся"}</div></td>
          <td>{s.os || "—"}{s.arch ? ` · ${s.arch}` : ""}</td>
          <td>{s.cpu_cores ? `${s.cpu_cores} CPU · ${s.ram_mb} МБ · ${s.disk_gb} ГБ свободно` : "—"}</td>
          <td>{(s.roles || []).map((r: string) => ROLE[r]).join(", ") || "—"}</td>
          <td className="actions">
            <button onClick={() => check(s.id)} disabled={busy === `check-${s.id}`}>{busy === `check-${s.id}` ? "Проверка…" : "Проверить"}</button>
            <button onClick={() => rotate(s.id, s.name)} disabled={busy === `rotate-${s.id}`}>{busy === `rotate-${s.id}` ? "Смена…" : "Сменить ключ"}</button>
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
    sub_domain: "", node_domain: "", tls: "acme", acme_email: "", node_port: "2222", node_name: "node", country_code: "XX", firewall: true, panel_access: "open",
    selfsteal_domain: "", selfsteal_template: "cloud", subpage_template: "default"});
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => { setF({...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value}); setPlan(null); };
  const usable = servers.filter(s => s.status !== "new" && s.status !== "unreachable");
  const m = f.mode;
  const needPanel = NEED_PANEL.includes(m);
  const needNodes = ["node", "add_node", "distributed"].includes(m);
  const needSub = ["panel_subpage", "subpage", "distributed"].includes(m);
  // SelfSteal: a node on its own server (port 443 is Xray's, the site is behind it on a socket).
  const selfsteal = ["node", "add_node", "distributed"].includes(m) && f.node_server_ids.length === 1;
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
      panel_access: needPanel ? f.panel_access : "open",
      selfsteal_domain: selfsteal ? f.selfsteal_domain || null : null, selfsteal_template: f.selfsteal_template,
      subpage_template: needSub ? f.subpage_template : "default"};
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
      {needSub && <label>Вид страницы подписки<select value={f.subpage_template} onChange={set("subpage_template")}>
        <option value="default">Стандартная страница Remnawave</option><option value="orion">Orion (legiz-ru, MIT)</option></select>
        <span className="muted">Orion — шаблон legiz-ru/Orion, закреплённый по SHA-256; скрипты страницы загружаются с jsDelivr и Skypack.</span></label>}
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
      {selfsteal && <fieldset className="wide" data-rw-selfsteal><legend>SelfSteal — маскировка ноды под сайт (TLS + REALITY)</legend>
        <p className="muted">Caddy на ноде получает сертификат домена ноды и отдаёт сайт-шаблон через сокет; Xray REALITY на порту 443 направляет туда всех, у кого нет ключей. Мастер создаст профиль REALITY и хост в панели. Домен должен указывать на сервер ноды.</p>
        <label>Домен ноды<input value={f.selfsteal_domain} onChange={set("selfsteal_domain")} placeholder="node1.example.com"/></label>
        <label>Сайт-шаблон<select value={f.selfsteal_template} onChange={set("selfsteal_template")}>
          <option value="cloud">Облачное хранилище</option><option value="docs">Документация</option><option value="corgi">Блог о корги</option></select></label>
        {f.selfsteal_domain && f.tls === "acme" && <label>Email для Let's Encrypt<input type="email" value={f.acme_email} onChange={set("acme_email")} required/></label>}
        {f.selfsteal_domain && !(needPanel || needSub) && <label>Сертификат<select value={f.tls} onChange={set("tls")}>
          <option value="acme">Let's Encrypt</option><option value="internal">Внутренний Caddy (проверка)</option></select></label>}
      </fieldset>}
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

// v28.77.0: «Журналы контейнеров», запуск, перезапуск и остановка контейнеров установки (файлы и тома не меняются).
const ACTIONS: [string, string, boolean][] = [["diagnose", "Диагностика", false], ["logs", "Журналы контейнеров", false],
  ["restart", "Перезапустить", true], ["start", "Запустить", true], ["stop", "Остановить", true],
  ["update", "Обновить", true], ["restore", "Восстановить базу панели", true], ["reinstall", "Переустановить", true], ["remove", "Удалить", true]];

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
      {job.params?.subpage_server_id && <button onClick={() => action("update", {subpage_template: job.params?.subpage_template === "orion" ? "default" : "orion"})}>
        {job.params?.subpage_template === "orion" ? "Вернуть стандартную страницу подписки" : "Страница подписки Orion"}</button>}
      {ACTIONS.filter(([a]) => a !== "restore" || job.params?.panel_server_id).map(([a, label, risky]) =>
        risky && confirm !== a ? <button key={a} onClick={() => setConfirm(a)}>{label}</button>
          : <button key={a} className={risky ? "danger" : ""} onClick={() => action(a)}>{risky ? `Составить план: ${label.toLowerCase()}` : label}</button>)}
    </div>}
    {creds && <SuccessNote>Панель {creds.panel_url}: администратор <code>{creds.username}</code>, пароль <code>{creds.password}</code>.
      {creds.access_url ? <> Вход только по секретной ссылке: <code>{creds.access_url}</code> (откройте один раз — браузер запомнит доступ на 30 дней).</> : null} Просмотр записан в журнал действий.</SuccessNote>}
    {staged && <div data-rw-staged><p>Подготовлено изменение настроек: REMNAWAVE_URL и REMNAWAVE_TOKEN (токен не показывается).</p>
      <button className="primary" onClick={apply}>Применить</button> <button onClick={() => setStaged(null)}>Позже (в «Настройки → Параметры»)</button></div>}
    {isInstall && job.status === "succeeded" && <NodeModules job={job} request={request} onPlanned={setPlanned} setError={setError}/>}
    {planned && <div className="plan" data-rw-action-plan><h4>{planned.plan.title}</h4>
      <ol>{planned.plan.steps.map((s: any) => <li key={s.position}>{s.title}</li>)}</ol>
      <button className="primary" onClick={runPlanned}>Запустить</button> <button onClick={() => act(async () => { await request(`${API}/installations/${planned.id}/cancel`, post()); setPlanned(null); })}>Не запускать</button></div>}
  </div>;
}

const MODULE_HINTS: Record<string, string> = {
  ipv6: "Включает или выключает IPv6 на выбранных серверах (sysctl). Прежняя настройка сохраняется и возвращается при ошибке.",
  xray_core: "Ядро Xray выбранного релиза XTLS/Xray-core вместо ядра из образа ноды. SHA-256 берётся из GitHub при составлении плана и проверяется на сервере; при ошибке ничего не заменяется.",
  warp: "Интерфейс warp (Cloudflare WARP через wgcf, без маршрутов). Трафик в него направляет исходящий warp-out профиля — «Расширения Remnawave → WARP в профиле».",
  netbird: "Подключает серверы к сети NetBird по ключу установки (Setup key). Ключ передаётся на сервер только при запуске и не хранится.",
  xray_checker: "Xray Checker проверяет все серверы подписки по расписанию; результаты видны здесь. Работает только на 127.0.0.1 сервера.",
};

function NodeModules({job, request, onPlanned, setError}: {job: any; request: Request; onPlanned: (p: any) => void; setError: (e: string) => void}) {
  const servers = Object.entries(job.plan?.servers || {}).map(([id, s]: any) => ({id: Number(id), ...s}));
  const nodes = servers.filter(s => s.roles.includes("node"));
  const [f, setF] = useState<any>({name: "ipv6", enabled: false, server_ids: nodes.map(s => String(s.id)), version: "latest", accept_warp_tos: false,
    setup_key: "", management_url: "", subscription_url: "", interval: "300", checker_server: String((nodes[0] || servers[0] || {}).id || "")});
  const [checker, setChecker] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});
  const mods = job.result?.state?.modules || {};
  async function plan(e: React.FormEvent) {
    e.preventDefault(); setError(""); setBusy(true);
    const m: any = {name: f.name, enabled: f.enabled};
    if (["ipv6", "warp", "netbird"].includes(f.name)) m.server_ids = f.server_ids.map(Number);
    if (f.name === "xray_core" && f.enabled) m.version = f.version || "latest";
    if (f.name === "warp") m.accept_warp_tos = f.accept_warp_tos;
    if (f.name === "netbird" && f.enabled) { m.setup_key = f.setup_key; m.management_url = f.management_url || null; }
    if (f.name === "xray_checker" && f.enabled) { m.server_ids = [Number(f.checker_server)]; m.interval = Number(f.interval); if (f.subscription_url) m.subscription_url = f.subscription_url; }
    try { onPlanned(await request(`${API}/installations/${job.id}/actions`, post({action: "module", module: m}))); setF({...f, setup_key: ""}); }
    catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function loadChecker() {
    setError("");
    try { setChecker(await request(`${API}/installations/${job.id}/xray-checker`)); } catch (err: any) { setError(err.message); }
  }
  const pickServers = (list: any[]) => <label className="wide">Серверы<select multiple value={f.server_ids} size={Math.min(5, Math.max(2, list.length))}
    onChange={e => setF({...f, server_ids: Array.from(e.target.selectedOptions).map(o => o.value)})}>
    {list.map(s => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}</select></label>;
  return <div className="card" data-rw-modules>
    <h4>Модули серверов</h4>
    <p className="muted">Каждое изменение — план из закрытого списка шагов: просмотрите его и запустите. Откат при ошибке — автоматически.</p>
    {Object.keys(mods).length > 0 && <ul data-rw-module-state>{Object.entries(mods).map(([sid, m]: any) => <li key={sid}>
      <b>{(servers.find(s => String(s.id) === sid) || {name: `#${sid}`}).name}</b>: {[m.ipv6 && `IPv6 ${m.ipv6 === "off" ? "выключен" : "включён"}`,
        m.xray_core && `ядро ${m.xray_core}`, m.warp && "WARP", m.netbird && "NetBird"].filter(Boolean).join(", ") || "по умолчанию"}</li>)}</ul>}
    <form onSubmit={plan} className="grid-form">
      <label>Модуль<select value={f.name} onChange={set("name")} data-rw-module>
        <option value="ipv6">IPv6</option><option value="xray_core">Ядро Xray</option><option value="warp">WARP Native</option>
        <option value="netbird">NetBird</option><option value="xray_checker">Xray Checker</option></select></label>
      <label>Действие<select value={f.enabled ? "on" : "off"} onChange={e => setF({...f, enabled: e.target.value === "on"})}>
        <option value="on">{f.name === "xray_core" ? "Установить версию" : "Включить"}</option>
        <option value="off">{f.name === "xray_core" ? "Вернуть ядро из образа" : "Выключить"}</option></select></label>
      <p className="muted wide">{MODULE_HINTS[f.name]}</p>
      {["ipv6", "warp", "netbird"].includes(f.name) && pickServers(f.name === "ipv6" || f.name === "netbird" ? servers : nodes)}
      {f.name === "xray_core" && f.enabled && <label>Версия<input value={f.version} onChange={set("version")} placeholder="latest или v25.10.15" pattern="latest|v\d+\.\d+\.\d+"/></label>}
      {f.name === "warp" && f.enabled && <label className="inline wide"><input type="checkbox" checked={f.accept_warp_tos} onChange={set("accept_warp_tos")}/>
        Я принимаю условия Cloudflare WARP (wgcf зарегистрирует учётную запись WARP для каждого сервера)</label>}
      {f.name === "netbird" && f.enabled && <>
        <label>Ключ установки (Setup key)<input type="password" autoComplete="off" value={f.setup_key} onChange={set("setup_key")} required/></label>
        <label>Свой сервер управления<input value={f.management_url} onChange={set("management_url")} placeholder="https://netbird.example.com (пусто — NetBird Cloud)"/></label></>}
      {f.name === "xray_checker" && f.enabled && <>
        <label>Сервер<select value={f.checker_server} onChange={set("checker_server")}>{servers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>Адрес подписки для проверки<input type="password" autoComplete="off" value={f.subscription_url} onChange={set("subscription_url")}
          placeholder={job.params?.xray_checker_server_id ? "оставьте пустым — прежний" : "https://sub.example.com/…"}/></label>
        <label>Интервал проверки, с<input type="number" min={60} max={86400} value={f.interval} onChange={set("interval")}/></label></>}
      <div className="wide"><button className="primary" disabled={busy}>Составить план</button></div>
    </form>
    {job.params?.xray_checker_server_id && <div data-rw-checker>
      <button onClick={loadChecker}>Результаты Xray Checker</button>
      {checker && <><p>На связи {checker.online} из {checker.total}</p>
        <div className="table-wrap"><table><thead><tr><th>Сервер</th><th>Адрес</th><th>Протокол</th><th>Состояние</th><th>Задержка</th></tr></thead>
          <tbody>{checker.proxies.map((p: any, i: number) => <tr key={i} data-online={p.online}><td>{p.name}</td><td>{p.server}:{p.port}</td><td>{p.protocol}</td>
            <td>{p.online ? "на связи" : "недоступен"}</td><td>{p.online ? `${p.latency_ms} мс` : "—"}</td></tr>)}</tbody></table></div></>}
    </div>}
  </div>;
}
