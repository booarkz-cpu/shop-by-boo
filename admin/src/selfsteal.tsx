import React, {useEffect, useState} from "react";
import {EmptyState, LoadState} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const API = "/api/admin/rw/selfsteal";
const post = (body?: any): RequestInit => ({method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});
const flag = (code: string) => /^[A-Z]{2}$/.test(code || "") && code !== "XX"
  ? String.fromCodePoint(...[...code].map(c => 0x1f1e6 + c.charCodeAt(0) - 65)) : "🏳️";

/** «Серверы → SelfSteal» (v28.92.0, N8): the sites the nodes show to strangers — overview, outside check, own sites, catalogue. */
export function SelfSteal({request, toast, apiBase = ""}: {request: Request; toast: (t: string) => void; apiBase?: string}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<string>("");
  const [change, setChange] = useState<any>(null);
  const [catalogue, setCatalogue] = useState<any>(null);
  const [sites, setSites] = useState<any[]>([]);
  const load = async () => {
    setError("");
    try {
      const [o, c, s] = await Promise.all([request(`${API}/overview`), request(`${API}/catalogue`), request(`${API}/sites`)]);
      setData(o); setCatalogue(c); setSites(s.sites);
    } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { load(); }, []);
  if (!data || !catalogue) return <section className="card"><LoadState error={error} onRetry={load} label="Загрузка нод и сайтов…"/></section>;

  async function check(key: string) {
    setBusy(key); setError("");
    try { const r = await request(`${API}/check`, post({key})); toast(`Проверка снаружи: ${r.summary}`); setOpen(key); await load(); }
    catch (e: any) { setError(e.message); } finally { setBusy(""); }
  }

  return <div data-selfsteal>
    <section className="card">
      <h3>SelfSteal — сайты нод</h3>
      <details data-selfsteal-why><summary>Зачем ноде свой сайт</summary>
        <p className="muted">Нода с REALITY на порту 443 для всех, у кого нет ключа, выглядит как обычный сайт: Xray передаёт такие соединения
          сайту SelfSteal на самой ноде. Свой сайт на домене ноды — с настоящим сертификатом, внутренними страницами, страницей 404 и картой
          сайта — не отличить от тысяч обычных сайтов. Пустая заглушка, страница веб-сервера по умолчанию или один сайт на всех нодах
          выдают VPN. Поэтому у каждой ноды своя сборка шаблона, а «Проверка снаружи» смотрит на ноду так, как её видит посторонний.</p>
      </details>
      {error && <div role="alert" className="error">{error}</div>}
      <div className="toolbar"><b data-selfsteal-known>Что стоит на нодах — известно про {data.known} из {data.total}</b>
        <button onClick={load}>Обновить</button></div>
      {!data.panel_connected && <p className="muted">Магазин не подключён к панели Remnawave: показаны только ноды, которые ставил мастер.</p>}
      {data.nodes.length === 0 ? <EmptyState title="Нод пока нет" hint="Поставьте ноду с SelfSteal в «Установка Remnawave» — она появится здесь."/> :
        <div className="table-wrap"><table data-selfsteal-nodes><thead><tr><th>Нода</th><th>Адрес</th><th>Домен</th><th>Сайт на ноде</th>
          <th>Проверка снаружи</th><th/></tr></thead>
          <tbody>{data.nodes.map((n: any, i: number) => <React.Fragment key={n.key || `u${i}`}>
            <tr data-node={n.key || "unknown"}>
              <td>{flag(n.country)} {n.name}</td><td className="mono">{n.address}</td>
              <td>{n.domain || <span className="muted">домена нет</span>}</td>
              <td>{n.unknown ? <span className="muted">не знаем — нода поставлена не мастером</span>
                : n.site ? <>{n.site.title}{n.site.template !== "custom" && <span className="muted"> · {n.site.lang}</span>}</>
                : <span className="muted">нечего показывать</span>}</td>
              <td>{n.check ? <button className="link" onClick={() => setOpen(open === n.key ? "" : n.key)} data-check-summary>
                {n.check.remarks ? "⚠️" : "✅"} {n.check.summary}</button> : <span className="muted">не проверяли</span>}</td>
              <td className="actions">{n.domain && <button onClick={() => check(n.key)} disabled={!!busy}>{busy === n.key ? "Проверяем…" : "Проверить"}</button>}
                {n.domain && <button onClick={() => setChange(n)}>Сменить сайт</button>}</td>
            </tr>
            {open === n.key && n.check && <tr><td colSpan={6}><ul className="checklist" data-check-points>
              {n.check.points.map((p: any) => <li key={p.key} data-ok={p.ok}>{p.ok ? "✅" : "⚠️"} {p.text}</li>)}</ul>
              <p className="muted">Проверено {new Date(n.check.checked_at).toLocaleString("ru-RU")} с сервера магазина по адресу ноды {n.check.address}.</p></td></tr>}
          </React.Fragment>)}</tbody></table></div>}
    </section>
    {change && <ChangeSite node={change} catalogue={catalogue} sites={sites} request={request} toast={toast}
      onDone={() => { setChange(null); load(); }}/>}
    <OwnSites sites={sites} request={request} toast={toast} reload={load}/>
    <Catalogue catalogue={catalogue} apiBase={apiBase}/>
  </div>;
}

/** The module «Сайт SelfSteal» of the node's installation: a plan to approve; the previous site comes back on an error. */
function ChangeSite({node, catalogue, sites, request, toast, onDone}: any) {
  const [template, setTemplate] = useState(node.site?.template || "cloud");
  const [lang, setLang] = useState(node.site?.lang || "ru");
  const [upload, setUpload] = useState(node.site?.upload || sites[0]?.id || "");
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  async function make() {
    setError("");
    const module: any = {name: "selfsteal_site", selfsteal_template: template, selfsteal_lang: lang};
    if (template === "custom") module.selfsteal_upload = upload;
    try { setPlan(await request(`/api/admin/rw/installations/${node.installation_id}/actions`, post({action: "module", module}))); }
    catch (e: any) { setError(e.message); }
  }
  async function run() {
    setError("");
    try { await request(`/api/admin/rw/installations/${plan.id}/approve`, post({plan_sha256: plan.plan_sha256}));
      toast(`Смена сайта на ${node.name} запущена: журнал — в «Установка Remnawave»`); onDone(); }
    catch (e: any) { setError(e.message); }
  }
  return <section className="card" data-selfsteal-change>
    <h4>Сайт на ноде {node.name} ({node.domain})</h4>
    {error && <div role="alert" className="error">{error}</div>}
    <div className="grid-form">
      <label>Сайт<select value={template} onChange={e => { setTemplate(e.target.value); setPlan(null); }}>
        {catalogue.templates.map((t: any) => <option key={t.id} value={t.id}>{t.title} — {t.theme_title}</option>)}
        <option value="custom" disabled={!sites.length}>Свой сайт (загруженный архив)</option></select></label>
      {template === "custom" ? <label>Архив<select value={upload} onChange={e => { setUpload(e.target.value); setPlan(null); }}>
        {sites.map((s: any) => <option key={s.id} value={s.id}>{s.name} ({s.files} файлов)</option>)}</select></label>
        : <label>Язык сайта<select value={lang} onChange={e => { setLang(e.target.value); setPlan(null); }}>
          <option value="ru">Русский</option><option value="en">English</option></select></label>}
    </div>
    <p className="muted">Каждая нода получает свою сборку шаблона: название, цвета, раскладка и картинки зависят от её домена.
      Нода и ключи REALITY не меняются; при ошибке вернётся прежний сайт.</p>
    {!plan ? <div className="toolbar"><button className="primary" onClick={make}>Составить план</button><button onClick={onDone}>Отмена</button></div>
      : <div data-selfsteal-plan><ol>{plan.plan.steps.map((s: any) => <li key={s.position}>{s.title}</li>)}</ol>
        <div className="toolbar"><button className="primary" onClick={run}>Запустить</button><button onClick={() => setPlan(null)}>Изменить</button></div></div>}
  </section>;
}

function OwnSites({sites, request, toast, reload}: any) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function upload(e: React.FormEvent) {
    e.preventDefault(); if (!file) return; setError(""); setBusy(true);
    const fd = new FormData(); fd.append("file", file); fd.append("name", name);
    try { const s = await request(`${API}/sites`, {method: "POST", body: fd}); toast(`Сайт «${s.name}» загружен: ${s.files} файлов`); setFile(null); setName(""); reload(); }
    catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function remove(id: string) {
    setError("");
    try { await request(`${API}/sites/${id}`, {method: "DELETE"}); toast("Сайт удалён"); reload(); } catch (err: any) { setError(err.message); }
  }
  return <section className="card" data-selfsteal-own>
    <h3>Свой сайт</h3>
    <p className="muted">Архив zip или tar.gz до 20 МБ: html, css, js, картинки, шрифты, видео. В корне архива или в единственной папке — index.html
      с заголовком &lt;title&gt;. Скрытые и служебные файлы, серверные скрипты (php, py, sh…) и ссылки не принимаются. Добавьте 404.html, robots.txt
      и sitemap.xml — их ищет «Проверка снаружи».</p>
    {error && <div role="alert" className="error">{error}</div>}
    <form onSubmit={upload} className="toolbar">
      <label>Архив<input type="file" accept=".zip,.tar.gz,.tgz,application/zip,application/gzip" onChange={e => setFile(e.target.files?.[0] || null)} data-selfsteal-file/></label>
      <label>Название<input value={name} onChange={e => setName(e.target.value)} placeholder="из <title>, если пусто" maxLength={80}/></label>
      <button className="primary" disabled={!file || busy}>{busy ? "Загрузка…" : "Загрузить архив"}</button>
    </form>
    {sites.length ? <div className="table-wrap"><table data-selfsteal-sites><thead><tr><th>Сайт</th><th>Файлов</th><th>Размер</th><th>Загружен</th><th/></tr></thead>
      <tbody>{sites.map((s: any) => <tr key={s.id}><td>{s.name}<div className="muted">{s.archive}</div></td><td>{s.files}</td>
        <td>{(s.size / 1024 / 1024).toFixed(2)} МБ</td><td>{new Date(s.uploaded_at).toLocaleString("ru-RU")} · {s.by}</td>
        <td><button onClick={() => remove(s.id)}>Удалить</button></td></tr>)}</tbody></table></div>
      : <p className="muted">Своих сайтов пока нет.</p>}
  </section>;
}

function Catalogue({catalogue, apiBase}: any) {
  const [theme, setTheme] = useState("");
  const [lang, setLang] = useState("");
  const [shown, setShown] = useState("");
  const [domain, setDomain] = useState("node.example.com");
  const list = catalogue.templates.filter((t: any) => (!theme || t.theme === theme) && (!lang || t.langs.includes(lang)));
  const previewLang = lang || "ru";
  return <section className="card" data-selfsteal-catalogue>
    <h3>Каталог шаблонов ({catalogue.templates.length})</h3>
    <p className="muted">Свои шаблоны магазина: тексты и картинки написаны для него, без запросов к чужим сайтам. У каждой ноды — своя сборка.</p>
    <div className="toolbar">
      <label>Тема<select value={theme} onChange={e => setTheme(e.target.value)} data-selfsteal-theme><option value="">Все темы</option>
        {Object.entries(catalogue.themes).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label>Язык<select value={lang} onChange={e => setLang(e.target.value)}><option value="">Любой</option>
        <option value="ru">Русский</option><option value="en">Английский</option></select></label>
      <label>Домен для превью<input value={domain} onChange={e => setDomain(e.target.value.trim().toLowerCase())}/></label>
    </div>
    <div className="cards">{list.map((t: any) => <div key={t.id} className="card" data-template={t.id}>
      <b>{t.title}</b><div className="muted">{t.theme_title} · {t.langs.join(", ")}</div><p>{t.tagline}</p>
      <button onClick={() => setShown(shown === t.id ? "" : t.id)}>{shown === t.id ? "Скрыть превью" : "Превью"}</button>
      {shown === t.id && <iframe title={`Превью ${t.title}`} sandbox="" style={{width: "100%", height: 420, border: "1px solid #ddd", borderRadius: 8}}
        src={`${apiBase}${API}/preview/${t.id}?domain=${encodeURIComponent(domain)}&lang=${previewLang}&page=index.html`}/>}
    </div>)}</div>
  </section>;
}

/** The catalogue's templates as a <select> (the wizard and «Сайт SelfSteal» of the installer), with the site's language. */
export function SiteTemplateSelect({request, value, onChange, lang, onLang, label = "Сайт-шаблон"}: {request: Request; value: string;
  onChange: (v: string) => void; lang: string; onLang: (v: string) => void; label?: string}) {
  const [list, setList] = useState<any[]>([]);
  useEffect(() => { request(`${API}/catalogue`).then((c: any) => setList(c.templates)).catch(() => setList([])); }, []);
  return <>
    <label>{label}<select value={value} onChange={e => onChange(e.target.value)} data-rw-site-template>
      {list.length === 0 && <option value={value}>{value}</option>}
      {list.map((t: any) => <option key={t.id} value={t.id}>{t.title} — {t.theme_title}</option>)}</select></label>
    <label>Язык сайта<select value={lang} onChange={e => onLang(e.target.value)} data-rw-site-lang>
      <option value="ru">Русский</option><option value="en">English</option></select></label>
  </>;
}
