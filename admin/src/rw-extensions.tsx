import React, {useEffect, useState} from "react";
import {EmptyState, LoadState} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (text: string) => void};
const API = "/api/admin/rw/extensions";
const body = (method: string, data?: unknown): RequestInit => ({method, body: data === undefined ? undefined : JSON.stringify(data)});
const pretty = (v: unknown) => JSON.stringify(v ?? {}, null, 2);
const PLUGIN_NAMES: Record<string, string> = {torrentBlocker: "TorrentBlocker — блокировка торрентов", ingressFilter: "Ingress Filter — входящие адреса",
  egressFilter: "Egress Filter — исходящие адреса и порты", connectionDrop: "Connection Drop — сброс соединений"};

function JsonBox({label, value, onSave, rows = 14, saveLabel = "Сохранить"}: {label: string; value: unknown; onSave: (v: any) => Promise<void>; rows?: number; saveLabel?: string}) {
  const [text, setText] = useState(pretty(value));
  const [error, setError] = useState("");
  useEffect(() => setText(pretty(value)), [JSON.stringify(value)]);
  async function save() {
    setError("");
    let parsed;
    try { parsed = JSON.parse(text); } catch (e: any) { setError(`JSON: ${e.message}`); return; }
    try { await onSave(parsed); } catch (e: any) { setError(e.message); }
  }
  return <div className="stack" data-json-box={label}>
    <label className="wide">{label}<textarea rows={rows} spellCheck={false} value={text} onChange={e => setText(e.target.value)} style={{fontFamily: "ui-monospace, monospace"}}/></label>
    {error && <div role="alert" className="error">{error}</div>}
    <div className="toolbar"><button onClick={save}>{saveLabel}</button><button onClick={() => setText(pretty(value))}>Вернуть</button></div>
  </div>;
}

/** «Серверы → Расширения Remnawave» (v28.69.0, stage 12): config profiles with a VLESS + REALITY builder, node plugins,
 *  subscription response rules and HWID limit, subscription page configs and templates — all through the panel's API. */
export function RwExtensions({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => { setError(""); request(API).then(setD).catch((e: any) => setError(e.message)); };
  useEffect(load, []);
  if (!d) return <LoadState error={error} onRetry={load} label="Загрузка расширений из панели Remnawave…"/>;
  return <div data-rw-extensions>
    <Profiles d={d} request={request} toast={toast} reload={load}/>
    <Plugins d={d} request={request} toast={toast} reload={load}/>
    <WarpProfile d={d} request={request} toast={toast}/>
    <AdBlockProfile d={d} request={request} toast={toast}/>
    <ServerRouting d={d} request={request} toast={toast}/>
    <SubscriptionRules request={request} toast={toast}/>
    <PagesAndTemplates request={request} toast={toast}/>
  </div>;
}

function Profiles({d, request, toast, reload}: any) {
  const [f, setF] = useState({name: "", server_names: "", dest: "selfsteal", target: "", port: "443", short_ids: "1", min_client_ver: "", block_private: true, block_torrent: true, doh: true});
  const [made, setMade] = useState<any>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [raw, setRaw] = useState<any>(null);
  const [bind, setBind] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});
  const act = async (fn: () => Promise<any>, ok: string) => { setError(""); try { const r = await fn(); toast(ok); reload(); return r; } catch (e: any) { setError(e.message); } };
  async function build(e: React.FormEvent) {
    e.preventDefault();
    const out = await act(() => request(`${API}/profiles/reality`, body("POST", {name: f.name, server_names: f.server_names.split(/[\s,]+/).filter(Boolean),
      dest: f.dest, target: f.dest === "site" ? f.target : null, port: Number(f.port), short_ids: Number(f.short_ids),
      min_client_ver: f.min_client_ver || null, block_private: f.block_private, block_torrent: f.block_torrent, doh: f.doh})), `Профиль ${f.name} создан`);
    if (out) setMade(out);
  }
  const show = async (uuid: string) => { if (open === uuid) { setOpen(null); return; } setOpen(uuid); setRaw(null); try { setRaw(await request(`${API}/profiles/${uuid}`)); } catch (e: any) { setError(e.message); } };
  return <div className="card" data-rw-profiles>
    <h3>Профили конфигурации</h3>
    <p className="muted">Конфигурации Xray для нод из панели Remnawave. Конструктор VLESS + REALITY берёт ключи x25519 у панели. SelfSteal — нода отдаёт свой сайт-шаблон через сокет <code>{d.selfsteal_socket}</code> (ставится мастером на сервер ноды).</p>
    {error && <div role="alert" className="error">{error}</div>}
    {d.profiles.length === 0 ? <EmptyState title="Профилей нет"/> : <div className="table-wrap"><table>
      <thead><tr><th>Профиль</th><th>Inbound</th><th>Ноды</th><th></th></tr></thead>
      <tbody>{d.profiles.map((p: any) => <React.Fragment key={p.uuid}><tr data-profile={p.name}>
        <td><b>{p.name}</b></td><td>{p.inbounds.map((i: any) => `${i.tag} (${i.type}${i.port ? `:${i.port}` : ""})`).join(", ") || "—"}</td>
        <td>{p.nodes.join(", ") || "—"}</td>
        <td className="actions"><button onClick={() => show(p.uuid)}>{open === p.uuid ? "Скрыть" : "Конфигурация"}</button>
          <button className="danger" disabled={p.nodes.length > 0} title={p.nodes.length ? "Профиль используется нодами" : ""}
            onClick={() => act(() => request(`${API}/profiles/${p.uuid}`, body("DELETE")), "Профиль удалён")}>Удалить</button></td></tr>
        {open === p.uuid && <tr><td colSpan={4}>{raw ? <JsonBox label="Конфигурация Xray (JSON)" value={raw.config}
          onSave={async v => { await request(`${API}/profiles/${p.uuid}`, body("PATCH", {config: v})); toast("Конфигурация сохранена: панель перезапустит ноды профиля"); reload(); }}/> : <p className="muted">Загрузка…</p>}
          <div className="grid3">{d.nodes.map((n: any) => <label key={n.uuid}>Нода {n.name}
            <select value={bind[n.uuid] ?? ""} onChange={e => setBind({...bind, [n.uuid]: e.target.value})}><option value="">— не менять —</option>
              {p.inbounds.map((i: any) => <option key={i.uuid} value={i.uuid}>{i.tag}</option>)}</select></label>)}</div>
          <button onClick={() => Promise.all(Object.entries(bind).filter(([, v]) => v).map(([node, inbound]) =>
            request(`${API}/nodes/${node}/profile`, body("POST", {profile_uuid: p.uuid, inbounds: [inbound]})))).then(() => { toast("Профиль назначен нодам"); setBind({}); reload(); }).catch((e: any) => setError(e.message))}>Назначить нодам</button>
        </td></tr>}
      </React.Fragment>)}</tbody></table></div>}
    <form onSubmit={build} className="grid-form" data-reality-builder>
      <h4>Новый профиль VLESS + REALITY</h4>
      <label>Название<input value={f.name} onChange={set("name")} required pattern="[A-Za-z0-9_ \-]{2,30}" placeholder="Lucy-REALITY"/></label>
      <label>Домены SNI (serverNames)<input value={f.server_names} onChange={set("server_names")} required placeholder="node1.example.com"/></label>
      <label>Маскировка<select value={f.dest} onChange={set("dest")}><option value="selfsteal">SelfSteal: свой сайт на ноде</option><option value="site">Чужой сайт (dest)</option></select></label>
      {f.dest === "site" && <label>Сайт (домен:порт)<input value={f.target} onChange={set("target")} required placeholder="www.example.com:443"/></label>}
      <label>Порт<input type="number" min={1} max={65535} value={f.port} onChange={set("port")}/></label>
      <label>Короткие ID (shortIds)<input type="number" min={1} max={8} value={f.short_ids} onChange={set("short_ids")}/></label>
      <label>Минимальная версия клиента<input value={f.min_client_ver} onChange={set("min_client_ver")} placeholder="25.1.1" pattern="\d+\.\d+\.\d+"/></label>
      <label className="inline"><input type="checkbox" checked={f.block_private} onChange={set("block_private")}/> Блокировать частные адреса</label>
      <label className="inline"><input type="checkbox" checked={f.block_torrent} onChange={set("block_torrent")}/> Блокировать BitTorrent</label>
      <label className="inline"><input type="checkbox" checked={f.doh} onChange={set("doh")}/> DNS через DoH</label>
      <div className="wide"><button className="primary">Создать профиль</button></div>
    </form>
    {made && <p className="success" data-reality-made>Профиль создан. Публичный ключ: <code>{made.public_key}</code>, shortIds: <code>{made.short_ids.join(", ")}</code>. Добавьте хост для inbound в «Remnawave: панель → Хосты» и назначьте профиль нодам.</p>}
  </div>;
}

function Plugins({d, request, toast, reload}: any) {
  const [name, setName] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState("");
  const act = async (fn: () => Promise<any>, ok: string) => { setError(""); try { await fn(); toast(ok); reload(); } catch (e: any) { setError(e.message); } };
  return <div className="card" data-rw-plugins>
    <h3>Плагины нод</h3>
    <p className="muted">Плагины панели Remnawave работают на нодах: TorrentBlocker, фильтры входящих и исходящих адресов, сброс соединений. Конфигурацию проверяет панель.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {d.plugins.length === 0 ? <EmptyState title="Плагинов нет" hint="Создайте плагин — все его функции сначала выключены."/> :
      d.plugins.map((p: any) => <div key={p.uuid} className="plan" data-plugin={p.name}>
        <div className="row"><b>{p.name}</b><span className="muted">{Object.entries(p.config || {}).filter(([, v]: any) => v?.enabled).map(([k]) => k).join(", ") || "всё выключено"}</span>
          <span className="muted">ноды: {p.nodes.join(", ") || "—"}</span>
          <button onClick={() => setOpen(open === p.uuid ? null : p.uuid)}>{open === p.uuid ? "Скрыть" : "Настроить"}</button>
          <button className="danger" onClick={() => act(() => request(`${API}/plugins/${p.uuid}`, body("DELETE")), "Плагин удалён")}>Удалить</button></div>
        {open === p.uuid && <>
          <div className="grid3">{Object.keys(PLUGIN_NAMES).map(k => <label key={k} className="inline"><input type="checkbox" checked={!!p.config?.[k]?.enabled}
            onChange={e => act(() => request(`${API}/plugins/${p.uuid}`, body("PATCH", {config: {...p.config, [k]: {...(p.config?.[k] || {}), enabled: e.target.checked}}})), "Плагин обновлён")}/> {PLUGIN_NAMES[k]}</label>)}</div>
          <JsonBox label="Конфигурация плагина (JSON)" value={p.config} onSave={async v => { await request(`${API}/plugins/${p.uuid}`, body("PATCH", {config: v})); toast("Плагин сохранён"); reload(); }}/>
          <div className="grid3">{d.nodes.map((n: any) => <label key={n.uuid} className="inline"><input type="checkbox" checked={n.plugin === p.uuid}
            onChange={e => act(() => request(`${API}/nodes/${n.uuid}/plugin`, body("POST", {plugin_uuid: e.target.checked ? p.uuid : null})), "Плагин ноды изменён")}/> {n.name}</label>)}</div>
        </>}
      </div>)}
    <div className="toolbar"><input value={name} onChange={e => setName(e.target.value)} placeholder="Название плагина" pattern="[A-Za-z0-9_ \-]{2,30}"/>
      <button disabled={name.length < 2} onClick={() => act(() => request(`${API}/plugins`, body("POST", {name})), "Плагин создан").then(() => setName(""))}>Создать плагин</button></div>
  </div>;
}

function SubscriptionRules({request, toast}: Props) {
  const [s, setS] = useState<any>(null);
  const [error, setError] = useState("");
  const [ua, setUa] = useState("Happ/2.0");
  const [result, setResult] = useState<any>(null);
  const load = () => request(`${API}/subscription-settings`).then(setS).catch((e: any) => setError(e.message));
  useEffect(() => { load(); }, []);
  if (!s) return <div className="card"><h3>Правила подписки</h3>{error ? <div role="alert" className="error">{error}</div> : <p className="muted">Загрузка…</p>}</div>;
  const save = async (patch: any, ok: string) => { await request(`${API}/subscription-settings`, body("PATCH", patch)); toast(ok); load(); };
  return <div className="card" data-rw-srr>
    <h3>Правила подписки панели (SRR), лимит устройств, заголовки</h3>
    <p className="muted">Правила ответа подписки решают, что получит каждый клиент по User-Agent и заголовкам: формат (Xray JSON, Mihomo, sing-box…), страницу для браузера, блокировку. Проверка — тестером панели, без сохранения.</p>
    {error && <div role="alert" className="error">{error}</div>}
    <JsonBox label="Правила ответа (responseRules)" value={s.responseRules} rows={16} onSave={v => save({response_rules: v}, "Правила сохранены")}/>
    <div className="toolbar"><input value={ua} onChange={e => setUa(e.target.value)} aria-label="User-Agent для проверки" placeholder="User-Agent"/>
      <button onClick={() => request(`${API}/srr-test`, body("POST", {response_rules: s.responseRules || {}, user_agent: ua})).then(setResult).catch((e: any) => setError(e.message))}>Проверить правило</button></div>
    {result && <p data-srr-result>{result.matched ? `Сработало правило «${result.matchedRule?.name}»` : "Ни одно правило не сработало"} → ответ <b>{result.responseType}</b></p>}
    <JsonBox label="Лимит устройств (hwidSettings)" value={s.hwidSettings} rows={6} onSave={v => save({hwid_settings: v}, "Лимит устройств сохранён")}/>
    <JsonBox label="Свои заголовки ответа (customResponseHeaders)" value={s.customResponseHeaders} rows={5} onSave={v => save({custom_response_headers: v}, "Заголовки сохранены")}/>
    <label className="inline"><input type="checkbox" checked={!!s.randomizeHosts} onChange={e => save({randomize_hosts: e.target.checked}, "Сохранено")}/> Перемешивать хосты в подписке</label>
  </div>;
}

function PagesAndTemplates({request, toast}: Props) {
  const [pages, setPages] = useState<any[] | null>(null);
  const [templates, setTemplates] = useState<any[] | null>(null);
  const [presets, setPresets] = useState<any>(null);
  const [open, setOpen] = useState<any>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("XRAY_JSON");
  const [error, setError] = useState("");
  const load = () => Promise.all([request(`${API}/subpage-configs`), request(`${API}/templates`), request(`${API}/presets`)])
    .then(([p, t, x]) => { setPages(p.configs); setTemplates(t.templates); setPresets(x); }).catch((e: any) => setError(e.message));
  useEffect(() => { load(); }, []);
  const act = async (fn: () => Promise<any>, ok: string) => { setError(""); try { await fn(); toast(ok); load(); } catch (e: any) { setError(e.message); } };
  const openItem = async (kind: string, uuid: string) => {
    if (open?.uuid === uuid) { setOpen(null); return; }
    try { setOpen({kind, uuid, data: await request(`${API}/${kind}/${uuid}`)}); } catch (e: any) { setError(e.message); }
  };
  return <div className="card" data-rw-pages>
    <h3>Страница подписки Remnawave и шаблоны подписки</h3>
    <p className="muted">Конфиги официальной страницы подписки (тема, приложения, тексты) и шаблоны ответа подписки. Клиентский балансировщик — фрагмент для шаблона Xray JSON: одна запись у клиента выбирает самую быструю ноду.</p>
    {error && <div role="alert" className="error">{error}</div>}
    <h4>Конфиги страницы подписки</h4>
    {(pages || []).map((p: any) => <div key={p.uuid} className="row" data-subpage={p.name}><b>{p.name}</b>
      <button onClick={() => openItem("subpage-configs", p.uuid)}>{open?.uuid === p.uuid ? "Скрыть" : "Редактировать"}</button>
      <button className="danger" onClick={() => act(() => request(`${API}/subpage-configs/${p.uuid}`, body("DELETE")), "Конфиг удалён")}>Удалить</button></div>)}
    <h4>Шаблоны подписки</h4>
    {(templates || []).map((t: any) => <div key={t.uuid} className="row" data-template={t.name}><b>{t.name}</b><span className="muted">{t.templateType}</span>
      <button onClick={() => openItem("templates", t.uuid)}>{open?.uuid === t.uuid ? "Скрыть" : "Редактировать"}</button>
      <button className="danger" onClick={() => act(() => request(`${API}/templates/${t.uuid}`, body("DELETE")), "Шаблон удалён")}>Удалить</button></div>)}
    {open?.kind === "subpage-configs" && <JsonBox label={`Конфиг страницы «${open.data.name}»`} value={open.data.config} rows={18}
      onSave={async v => { await request(`${API}/subpage-configs/${open.uuid}`, body("PATCH", {config: v})); toast("Конфиг страницы сохранён"); }}/>}
    {open?.kind === "templates" && open.data.templateJson !== undefined && open.data.templateJson !== null && <>
      <JsonBox label={`Шаблон «${open.data.name}» (JSON)`} value={open.data.templateJson} rows={18}
        onSave={async v => { await request(`${API}/templates/${open.uuid}`, body("PATCH", {template_json: v})); toast("Шаблон сохранён"); }}/>
      {presets && <button data-add-balancer onClick={() => act(() => request(`${API}/templates/${open.uuid}`, body("PATCH", {template_json: {...open.data.templateJson, ...presets.client_balancer_xray_json}})), "Балансировщик добавлен в шаблон")}>Добавить клиентский балансировщик</button>}
    </>}
    {open?.kind === "templates" && (open.data.templateJson === undefined || open.data.templateJson === null) && <p className="muted">Шаблон YAML ({open.data.templateType}) правится в панели Remnawave: здесь — JSON-шаблоны.</p>}
    <div className="toolbar"><input value={name} onChange={e => setName(e.target.value)} placeholder="Название" aria-label="Название конфига или шаблона"/>
      <button disabled={name.length < 2} onClick={() => act(() => request(`${API}/subpage-configs`, body("POST", {name})), "Конфиг страницы создан")}>Новый конфиг страницы</button>
      <select value={type} onChange={e => setType(e.target.value)} aria-label="Тип шаблона">{["XRAY_JSON", "XRAY_BASE64", "MIHOMO", "STASH", "CLASH", "SINGBOX"].map(x => <option key={x}>{x}</option>)}</select>
      <button disabled={name.length < 2} onClick={() => act(() => request(`${API}/templates`, body("POST", {name, template_type: type})), "Шаблон создан")}>Новый шаблон</button></div>
  </div>;
}

/** v28.70.0: the outbound warp-out (interface «warp» raised by the wizard's WARP Native module) and its domains. */
function WarpProfile({d, request, toast}: any) {
  const [profile, setProfile] = useState(d.profiles[0]?.uuid || "");
  const [domains, setDomains] = useState("whoer.net, browserleaks.com, 2ip.io, 2ip.ru");
  const [error, setError] = useState("");
  async function apply(enabled: boolean) {
    setError("");
    try {
      const out = await request(`${API}/profiles/${profile}/warp`, body("POST", {enabled, domains: domains.split(/[\s,]+/).filter(Boolean)}));
      toast(enabled ? `WARP в профиле: ${out.domains.length} доменов` : "WARP убран из профиля");
    } catch (e: any) { setError(e.message); }
  }
  return <section className="card" data-rw-warp>
    <h3>WARP в профиле</h3>
    <p className="muted">Исходящий <code>warp-out</code> идёт через интерфейс <code>warp</code> ноды. Сначала включите модуль «WARP Native» на серверах нод (Серверы → Мастер установки → задача установки → Модули), затем выберите домены, которые пойдут через WARP.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {d.profiles.length === 0 ? <EmptyState title="Нет профилей" hint="Создайте профиль выше."/> : <div className="grid-form">
      <label>Профиль<select value={profile} onChange={e => setProfile(e.target.value)}>{d.profiles.map((p: any) => <option key={p.uuid} value={p.uuid}>{p.name}</option>)}</select></label>
      <label className="wide">Домены через WARP<input value={domains} onChange={e => setDomains(e.target.value)} placeholder="example.com, geosite:openai"/></label>
      <div className="wide toolbar"><button className="primary" onClick={() => apply(true)}>Включить WARP для доменов</button><button onClick={() => apply(false)}>Убрать WARP</button></div>
    </div>}
  </section>;
}

/** v28.92.0 (N7): ad domains of the node's geosite.dat to BLOCK for every client of the profile. */
function AdBlockProfile({d, request, toast}: any) {
  const [profile, setProfile] = useState(d.profiles[0]?.uuid || "");
  const [error, setError] = useState("");
  async function apply(enabled: boolean) {
    setError("");
    try { await request(`${API}/profiles/${profile}/adblock`, body("POST", {enabled})); toast(enabled ? "Реклама блокируется на нодах профиля" : "Блокировка рекламы снята"); }
    catch (e: any) { setError(e.message); }
  }
  return <section className="card" data-rw-adblock>
    <h3>Блокировка рекламы на нодах</h3>
    <p className="muted">Правило <code>geosite:category-ads-all → BLOCK</code> первым в профиле: реклама и трекеры не открываются у всех клиентов, без настроек в приложениях. Ноды получат профиль сразу.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {d.profiles.length === 0 ? <EmptyState title="Нет профилей" hint="Создайте профиль выше."/> : <div className="toolbar">
      <label>Профиль<select value={profile} onChange={e => setProfile(e.target.value)}>{d.profiles.map((p: any) => <option key={p.uuid} value={p.uuid}>{p.name}</option>)}</select></label>
      <button className="primary" onClick={() => apply(true)}>Включить</button><button onClick={() => apply(false)}>Выключить</button></div>}
  </section>;
}

/** v28.70.0: a bridge from an entry node to an exit node (Shadowsocks), with rules for Russian addresses. */
function ServerRouting({d, request, toast}: any) {
  const [list, setList] = useState<any[] | null>(null);
  const [f, setF] = useState({entry: d.profiles[0]?.uuid || "", exit: d.nodes[0]?.uuid || "", port: "8443", mode: "direct"});
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const load = () => request(`${API}/routing`).then((x: any) => setList(x.bridges)).catch((e: any) => setError(e.message));
  useEffect(() => { load(); }, []);
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.value});
  async function create(e: React.FormEvent) {
    e.preventDefault(); setError(""); setNote("");
    try {
      const out = await request(`${API}/routing`, body("POST", {entry_profile_uuid: f.entry, exit_node_uuid: f.exit, port: Number(f.port), mode: f.mode}));
      setNote(out.note); toast(`Мост: ${out.profile} → ${out.exit}`); load();
    } catch (err: any) { setError(err.message); }
  }
  async function remove(uuid: string) {
    setError("");
    try { await request(`${API}/routing/${uuid}`, body("DELETE")); toast("Мост удалён"); load(); } catch (err: any) { setError(err.message); }
  }
  return <section className="card" data-rw-routing>
    <h3>Серверный роутинг</h3>
    <p className="muted">Мост с ноды входа на ноду выхода (Shadowsocks). «Прямо»: российские адреса выходят с ноды входа, остальное — через ноду выхода. «Через мост»: только российские адреса идут через ноду выхода. Частные адреса и BitTorrent блокируются.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {note && <p className="muted" data-rw-routing-note>{note}</p>}
    {list && list.length > 0 && <div className="table-wrap"><table><thead><tr><th>Профиль входа</th><th>Нода выхода</th><th>Режим</th><th></th></tr></thead>
      <tbody>{list.map(b => <tr key={b.profile_uuid} data-bridge={b.profile}><td>{b.profile}</td><td>{b.exit}</td><td>{b.mode === "bridge" ? "через мост" : "прямо"}</td>
        <td><button className="danger" onClick={() => remove(b.profile_uuid)}>Удалить мост</button></td></tr>)}</tbody></table></div>}
    <form onSubmit={create} className="grid-form">
      <label>Профиль входа<select value={f.entry} onChange={set("entry")}>{d.profiles.map((p: any) => <option key={p.uuid} value={p.uuid}>{p.name}</option>)}</select></label>
      <label>Нода выхода<select value={f.exit} onChange={set("exit")}>{d.nodes.map((n: any) => <option key={n.uuid} value={n.uuid}>{n.name}</option>)}</select></label>
      <label>Порт моста<input type="number" min={1024} max={65535} value={f.port} onChange={set("port")}/></label>
      <label>Режим<select value={f.mode} onChange={set("mode")}><option value="direct">Прямо (РФ с ноды входа)</option><option value="bridge">Через мост (только РФ)</option></select></label>
      <div className="wide"><button className="primary" disabled={!f.entry || !f.exit}>Создать мост</button></div>
    </form>
  </section>;
}
