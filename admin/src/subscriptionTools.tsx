import React, {useEffect, useState} from "react";

/** v28.38: subscription proxy and the other functions taken over from remnawave-subscription-middleware. */
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (text: string) => void};
const put = (body: any): RequestInit => ({method: "PUT", body: JSON.stringify(body)});
const post = (body?: any): RequestInit => ({method: "POST", body: JSON.stringify(body ?? {})});
const day = (v?: string | null) => (v ? String(v).slice(0, 16).replace("T", " ") : "—");
const gb = (b: number) => `${(Number(b || 0) / 1024 ** 3).toFixed(2)} ГБ`;
const DECISION: Record<string, string> = {proxied: "отдано", extended: "отдано + доп. ключи", blocked: "заглушка", not_found: "нет такой", error: "ошибка панели"};

function useData(request: Request, path: string): [any, () => void, string, (e: string) => void] {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => { setError(""); request(path).then(setData).catch((e: any) => setError(e.message)); };
  useEffect(load, [request, path]);
  return [data, load, error, setError];
}

function Card({title, hint, error, children}: {title: string; hint?: string; error?: string; children: React.ReactNode}) {
  return <div className="card"><h3>{title}</h3>{hint ? <p className="muted">{hint}</p> : null}{error ? <p className="error">{error}</p> : null}{children}</div>;
}

async function act(fn: () => Promise<any>, toast: (t: string) => void, ok: string, setError: (e: string) => void, after?: () => void) {
  setError("");
  try { await fn(); toast(ok); after?.(); } catch (e: any) { setError(e.message); }
}

/** «Серверы → Прослойка подписки»: mirror, rules, extra keys, blocked devices. */
export function SubProxy({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/sub-proxy");
  const [form, setForm] = useState<any>(null);
  const [block, setBlock] = useState({hwid: "", note: ""});
  if (!d) return <Card title="Прослойка подписки" error={error}><p>Загрузка…</p></Card>;
  const cfg = form ?? d.config;
  const set = (patch: any) => setForm({...cfg, ...patch});
  const save = () => act(() => request("/api/admin/sub-proxy", put({
    ...cfg, rules: (cfg.rules || []).map((r: any) => ({...r, headers: typeof r.headers === "string" ? Object.fromEntries(r.headers.split("\n").filter((l: string) => l.includes(":")).map((l: string) => [l.split(":")[0].trim(), l.slice(l.indexOf(":") + 1).trim()])) : r.headers})),
    extras: (cfg.extras || []).map((x: any) => ({...x, links: typeof x.links === "string" ? x.links.split("\n").map((l: string) => l.trim()).filter(Boolean) : x.links})),
  })), toast, "Сохранено", setError, () => { setForm(null); load(); });
  const stats = d.last_24h || {};
  return (
    <Card title="Прослойка подписки" error={error} hint="Клиенты обновляют подписку через ваш домен, магазин забирает её у панели. Помогает, когда домен панели не открывается у клиентов. Ссылка панели продолжает работать.">
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => set({enabled: e.target.checked})}/> Включить прослойку</label>
      <div className="grid3">
        <label>Адрес зеркала<input value={cfg.public_base} placeholder="https://sub.example.ru" onChange={(e) => set({public_base: e.target.value.trim()})}/></label>
        <label>Префикс пути<input value={cfg.prefix} placeholder="без префикса" onChange={(e) => set({prefix: e.target.value.trim()})}/></label>
        <label>Откуда брать подписку<input value={cfg.origin} placeholder={d.origin_effective} onChange={(e) => set({origin: e.target.value.trim()})}/></label>
      </div>
      <p className="muted">Ссылка клиента: <code>{d.example || "укажите адрес зеркала"}</code>. Домен зеркала направьте на сервер магазина (Caddy: блок <code>SUB_PROXY_DOMAIN</code>).</p>
      <label className="check"><input type="checkbox" checked={cfg.rewrite_links} onChange={(e) => set({rewrite_links: e.target.checked})}/> Выдавать клиентам ссылку зеркала в кабинете, Mini App, боте и приложениях</label>
      <label className="check"><input type="checkbox" checked={cfg.mask} onChange={(e) => set({mask: e.target.checked})}/> Нейтральная страница входа для всего, что не похоже на подписку</label>
      <label className="check"><input type="checkbox" checked={cfg.ua_hwid} onChange={(e) => set({ua_hwid: e.target.checked})}/> Брать HWID из User-Agent (<code>x-hwid=…</code>) для клиентов без своих заголовков</label>
      <label>Вторая подписка (её серверы добавляются в ту же ссылку)<input value={cfg.merge_url} placeholder="https://other.example/sub/{short_uuid}" onChange={(e) => set({merge_url: e.target.value.trim()})}/></label>
      <h4>Правила по приложению</h4>
      <p className="muted">Первое подходящее правило меняет заголовки ответа. Заголовок с пустым значением удаляется. Кириллица отправляется как base64.</p>
      {(cfg.rules || []).map((r: any, i: number) => (
        <div className="grid3" key={i}>
          <label>Название<input value={r.name} onChange={(e) => set({rules: cfg.rules.map((x: any, j: number) => j === i ? {...x, name: e.target.value} : x)})}/></label>
          <label>User-Agent (выражение)<input value={r.ua} placeholder="^happ" onChange={(e) => set({rules: cfg.rules.map((x: any, j: number) => j === i ? {...x, ua: e.target.value} : x)})}/></label>
          <label>Заголовки (имя: значение)<textarea rows={3} value={typeof r.headers === "string" ? r.headers : Object.entries(r.headers || {}).map(([k, v]) => `${k}: ${v}`).join("\n")} placeholder={"profile-title: Корги Люси\nprofile-update-interval: 6\nannounce: Новый сервер в Финляндии"} onChange={(e) => set({rules: cfg.rules.map((x: any, j: number) => j === i ? {...x, headers: e.target.value} : x)})}/></label>
          <button className="danger" onClick={() => set({rules: cfg.rules.filter((_: any, j: number) => j !== i)})}>Удалить правило</button>
        </div>))}
      <button onClick={() => set({rules: [...(cfg.rules || []), {name: "", ua: "", os: "", headers: ""}]})}>Добавить правило</button>
      <h4>Дополнительные ключи по скваду</h4>
      <p className="muted">Ссылки (VLESS, WireGuard, Hysteria…) добавляются в подписку клиентам сквада, только если подписка активна и формат — список ссылок. Пустой сквад — всем.</p>
      {(cfg.extras || []).map((x: any, i: number) => (
        <div className="grid3" key={i}>
          <label>Название<input value={x.name} onChange={(e) => set({extras: cfg.extras.map((y: any, j: number) => j === i ? {...y, name: e.target.value} : y)})}/></label>
          <label>UUID сквада<input value={x.squad} onChange={(e) => set({extras: cfg.extras.map((y: any, j: number) => j === i ? {...y, squad: e.target.value.trim()} : y)})}/></label>
          <label>Ссылки, по одной в строке<textarea rows={3} value={typeof x.links === "string" ? x.links : (x.links || []).join("\n")} onChange={(e) => set({extras: cfg.extras.map((y: any, j: number) => j === i ? {...y, links: e.target.value} : y)})}/></label>
          <button className="danger" onClick={() => set({extras: cfg.extras.filter((_: any, j: number) => j !== i)})}>Удалить</button>
        </div>))}
      <button onClick={() => set({extras: [...(cfg.extras || []), {name: "", squad: "", links: ""}]})}>Добавить ключи</button>
      <h4>Заблокированные устройства</h4>
      <label>Текст заглушки (виден в приложении как имя сервера)<input value={cfg.block_text} maxLength={120} onChange={(e) => set({block_text: e.target.value})}/></label>
      <div className="toolbar"><button onClick={save}>Сохранить настройки</button>{form ? <button onClick={() => setForm(null)}>Отменить</button> : null}</div>
      <div className="toolbar">
        <input placeholder="HWID устройства" value={block.hwid} onChange={(e) => setBlock({...block, hwid: e.target.value.trim()})}/>
        <input placeholder="Причина" value={block.note} onChange={(e) => setBlock({...block, note: e.target.value})}/>
        <button className="danger" disabled={!block.hwid} onClick={() => act(() => request("/api/admin/sub-proxy/blocked", post(block)), toast, "Устройство заблокировано", setError, () => { setBlock({hwid: "", note: ""}); load(); })}>Заблокировать</button>
      </div>
      {(d.config.blocked_hwids || []).length ? <table className="table"><tbody>{d.config.blocked_hwids.map((b: any) => <tr key={b.hwid}><td><code>{b.hwid}</code></td><td>{b.note}</td><td>{day(b.at)}</td>
        <td><button onClick={() => act(() => request(`/api/admin/sub-proxy/blocked/${encodeURIComponent(b.hwid)}`, {method: "DELETE"}), toast, "Разблокировано", setError, load)}>Разблокировать</button></td></tr>)}</tbody></table> : <p className="muted">Нет заблокированных устройств.</p>}
      <p className="muted">За сутки: {Object.entries(stats).map(([k, v]) => `${DECISION[k] || k} — ${v}`).join(", ") || "запросов не было"}.</p>
    </Card>
  );
}

/** «Мониторинг → Журнал подписки»: requests through the proxy and client versions. */
export function SubLog({request, toast}: Props) {
  const [filter, setFilter] = useState({short_uuid: "", decision: "", outdated: false});
  const q = `/api/admin/sub-proxy/log?limit=200&short_uuid=${encodeURIComponent(filter.short_uuid)}&decision=${filter.decision}&outdated=${filter.outdated}`;
  const [log, , error] = useData(request, q);
  const [apps] = useData(request, "/api/admin/sub-proxy/apps?days=7");
  const [clients, loadClients, cerror, setCError] = useData(request, "/api/admin/sub-proxy/clients");
  const [edit, setEdit] = useState<any[] | null>(null);
  const rows = edit ?? clients?.clients ?? [];
  return (
    <Card title="Журнал подписки" error={error || cerror} hint="Кто, когда и каким приложением обновлял подписку через прослойку. Хранится 14 дней. Отметка «устарел» — подсказка: версия взята из User-Agent клиента.">
      <div className="toolbar">
        <input placeholder="shortUuid" value={filter.short_uuid} onChange={(e) => setFilter({...filter, short_uuid: e.target.value.trim()})}/>
        <select value={filter.decision} onChange={(e) => setFilter({...filter, decision: e.target.value})}><option value="">Все решения</option>{Object.entries(DECISION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <label className="check"><input type="checkbox" checked={filter.outdated} onChange={(e) => setFilter({...filter, outdated: e.target.checked})}/> Только устаревшие клиенты</label>
      </div>
      <table className="table"><thead><tr><th>Время</th><th>Клиент</th><th>Приложение</th><th>Устройство</th><th>Решение</th><th>Размер</th></tr></thead>
        <tbody>{(log?.rows || []).map((r: any) => <tr key={r.id}><td>{day(r.at)}</td><td>{r.user_id ? `#${r.user_id}` : r.short_uuid}</td>
          <td>{r.app || "—"} {r.version}{r.outdated ? <b className="warn"> · устарел</b> : null}</td><td>{[r.os, r.model].filter(Boolean).join(" · ") || "—"}{r.hwid ? <><br/><code>{r.hwid}</code></> : null}</td>
          <td>{DECISION[r.decision] || r.decision} ({r.status})</td><td>{r.bytes} Б · {r.ms} мс</td></tr>)}</tbody></table>
      <h4>Приложения за неделю</h4>
      <p>{(apps?.apps || []).slice(0, 20).map((a: any) => `${a.app} ${a.version || ""} — ${a.customers}`).join(" · ") || "Пока нет данных."}</p>
      <h4>Каталог версий клиентов</h4>
      <table className="table"><thead><tr><th>Приложение</th><th>GitHub (владелец/репозиторий)</th><th>Последняя версия</th><th>Вручную</th><th/></tr></thead>
        <tbody>{rows.map((c: any, i: number) => <tr key={i}>
          <td><input value={c.app} onChange={(e) => setEdit(rows.map((x: any, j: number) => j === i ? {...x, app: e.target.value} : x))}/></td>
          <td><input value={c.repo} onChange={(e) => setEdit(rows.map((x: any, j: number) => j === i ? {...x, repo: e.target.value.trim()} : x))}/></td>
          <td><input value={c.latest} onChange={(e) => setEdit(rows.map((x: any, j: number) => j === i ? {...x, latest: e.target.value.trim()} : x))}/>{c.checked_at ? <small className="muted"> проверено {day(c.checked_at)}</small> : null}</td>
          <td><input type="checkbox" checked={!!c.manual} onChange={(e) => setEdit(rows.map((x: any, j: number) => j === i ? {...x, manual: e.target.checked} : x))}/></td>
          <td><button className="danger" onClick={() => setEdit(rows.filter((_: any, j: number) => j !== i))}>×</button></td></tr>)}</tbody></table>
      <div className="toolbar">
        <button onClick={() => setEdit([...rows, {app: "", repo: "", latest: "", manual: false}])}>Добавить приложение</button>
        <button disabled={!edit} onClick={() => act(() => request("/api/admin/sub-proxy/clients", put(rows.filter((x: any) => x.app))), toast, "Каталог сохранён", setCError, () => { setEdit(null); loadClients(); })}>Сохранить каталог</button>
        <button onClick={() => act(() => request("/api/admin/sub-proxy/clients/refresh", post()), toast, "Версии обновлены", setCError, loadClients)}>Проверить версии сейчас</button>
      </div>
    </Card>
  );
}

/** «Интеграции → Пересылка вебхуков» and «Кто менял пользователя». */
export function WebhookTee({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/webhooks/tee");
  const [rows, setRows] = useState<any[] | null>(null);
  const [source, setSource] = useState("");
  const [changes] = useData(request, `/api/admin/panel-changes?limit=100&source=${source}`);
  if (!d) return <Card title="Вебхуки панели" error={error}><p>Загрузка…</p></Card>;
  const targets = rows ?? d.targets.map((t: any) => ({...t, secret: ""}));
  const SRC: Record<string, string> = {shop: "магазин", external: "извне", first: "первое событие"};
  return (
    <Card title="Вебхуки панели" error={error} hint="Панель шлёт вебхуки одному адресу — магазину. Здесь их можно разослать дальше: каждый получатель получает исходное тело, подписанное своим секретом (X-Remnawave-Signature).">
      {targets.map((t: any, i: number) => <div className="grid3" key={i}>
        <label>Название<input value={t.name} onChange={(e) => setRows(targets.map((x: any, j: number) => j === i ? {...x, name: e.target.value} : x))}/></label>
        <label>Адрес (https)<input value={t.url} onChange={(e) => setRows(targets.map((x: any, j: number) => j === i ? {...x, url: e.target.value.trim()} : x))}/></label>
        <label>Секрет{t.has_secret ? " (сохранён — оставьте пустым)" : ""}<input type="password" value={t.secret} onChange={(e) => setRows(targets.map((x: any, j: number) => j === i ? {...x, secret: e.target.value} : x))}/></label>
        <label className="check"><input type="checkbox" checked={t.enabled} onChange={(e) => setRows(targets.map((x: any, j: number) => j === i ? {...x, enabled: e.target.checked} : x))}/> Включён</label>
        <button className="danger" onClick={() => setRows(targets.filter((_: any, j: number) => j !== i))}>Удалить</button>
      </div>)}
      <div className="toolbar">
        <button onClick={() => setRows([...targets, {name: "", url: "", secret: "", enabled: true}])}>Добавить получателя</button>
        <button disabled={!rows} onClick={() => act(() => request("/api/admin/webhooks/tee", put({targets, journal: d.journal})), toast, "Сохранено", setError, () => { setRows(null); load(); })}>Сохранить</button>
        <button onClick={() => act(async () => { const r = await request("/api/admin/webhooks/tee/test", post()); toast(r.results.map((x: any) => `${x.name}: ${x.ok ? "принял" : "ошибка"}`).join(", ") || "Нет получателей"); }, toast, "Проверено", setError)}>Отправить тестовое событие</button>
      </div>
      <label className="check"><input type="checkbox" checked={d.journal} onChange={(e) => act(() => request("/api/admin/webhooks/tee", put({targets: targets.map((t: any) => ({...t, secret: ""})), journal: e.target.checked})), toast, "Сохранено", setError, load)}/> Вести журнал изменений пользователей</label>
      <h4>Кто менял пользователя</h4>
      <p className="muted">«Магазин» — поля менял сам магазин через API за последние 5 минут; «извне» — бот, скрипт или человек в панели.</p>
      <div className="toolbar"><select value={source} onChange={(e) => setSource(e.target.value)}><option value="">Все</option><option value="shop">магазин</option><option value="external">извне</option></select>
        <a className="button" href="/api/admin/panel-changes.csv?anonymize=true">CSV (обезличенный)</a><a className="button" href="/api/admin/panel-changes.csv">CSV</a></div>
      <table className="table"><tbody>{(changes?.rows || []).map((r: any) => <tr key={r.id}><td>{day(r.at)}</td><td>{r.user_id ? `#${r.user_id}` : r.panel_user}</td><td>{r.event}</td>
        <td><b className={r.source === "external" ? "warn" : ""}>{SRC[r.source] || r.source}</b></td>
        <td>{Object.entries(r.changed || {}).map(([k, v]: any) => `${k}: ${JSON.stringify(v[0])} → ${JSON.stringify(v[1])}`).join("; ") || "—"}</td></tr>)}</tbody></table>
    </Card>
  );
}

/** «Мониторинг → Запросы к панели». */
export function PanelApiStats({request}: {request: Request}) {
  const [hours, setHours] = useState(24);
  const [d, , error] = useData(request, `/api/admin/panel-api-stats?hours=${hours}`);
  const [open, setOpen] = useState("");
  const NAMES: Record<string, string> = {customer: "Клиенты", admin: "Админка", subscription: "Прослойка подписки", webhook: "Вебхуки", background: "Фоновые задачи", api: "Прочее API"};
  return (
    <Card title="Запросы к панели" error={error} hint="Кто в магазине и как часто обращается к API Remnawave. Считается в памяти, пишется почасовыми суммами.">
      <div className="toolbar">{[24, 72, 168].map((h) => <button key={h} className={h === hours ? "primary" : ""} onClick={() => setHours(h)}>{h === 24 ? "Сутки" : h === 72 ? "3 дня" : "Неделя"}</button>)}</div>
      {d ? <>
        <p>Всего {d.total}, ошибок {d.errors} ({d.total ? Math.round(d.errors * 100 / d.total) : 0}%). Пик: {day(d.peak_hour)} — {d.peak_calls} за час.</p>
        <table className="table"><thead><tr><th>Источник</th><th>Запросов</th><th>Ошибок</th><th>Среднее время</th></tr></thead>
          <tbody>{d.sources.map((s: any) => <React.Fragment key={s.source}><tr onClick={() => setOpen(open === s.source ? "" : s.source)} style={{cursor: "pointer"}}>
            <td>{open === s.source ? "▾" : "▸"} {NAMES[s.source] || s.source}</td><td>{s.calls}</td><td>{s.errors}</td><td>{s.avg_ms} мс</td></tr>
            {open === s.source ? s.paths.map((p: any) => <tr key={p.path}><td><code>{p.path}</code></td><td>{p.calls}</td><td>{p.errors}</td><td>{p.avg_ms} мс</td></tr>) : null}</React.Fragment>)}</tbody></table>
      </> : <p>Загрузка…</p>}
    </Card>
  );
}

/** «Тарифы → Срок с первого подключения». */
export function FirstConnect({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/first-connect");
  const [plans, setPlans] = useState("");
  if (!d) return <Card title="Срок с первого подключения" error={error}><p>Загрузка…</p></Card>;
  const cfg = d.config;
  const save = (patch: any) => act(() => request("/api/admin/first-connect", put({...cfg, ...patch})), toast, "Сохранено", setError, load);
  return (
    <Card title="Срок с первого подключения" error={error} hint="Новая подписка активна сразу, а срок начинает идти, когда клиент впервые подключится (вебхук панели user.first_connected). Если клиент так и не подключится, срок начнётся сам по окончании ожидания.">
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => save({enabled: e.target.checked})}/> Включить для выбранных тарифов</label>
      <label>ID тарифов через запятую<input defaultValue={(cfg.plans || []).join(", ")} onChange={(e) => setPlans(e.target.value)} onBlur={() => plans && save({plans: plans.split(/[\s,]+/).map(Number).filter(Boolean)})}/></label>
      <label>Ждать подключения не дольше (дней, до 30)<input type="number" min={1} max={30} defaultValue={cfg.max_wait_days} onBlur={(e) => save({max_wait_days: Number(e.target.value)})}/></label>
      <p className="muted">Ждут подключения: {d.waiting.length}; срок начался за 30 дней: {d.started_30d}. Нужен вебхук панели (WEBHOOK_ENABLED).</p>
    </Card>
  );
}

/** «Клиенты → Сессии и аномалии». */
export function SessionsAdmin({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/sessions/config");
  const [an, loadAn] = useData(request, "/api/admin/sessions/anomalies");
  const [rules, setRules] = useState<any[] | null>(null);
  if (!d) return <Card title="Сессии и аномалии" error={error}><p>Загрузка…</p></Card>;
  const cfg = d.config;
  const list = rules ?? cfg.rules;
  const save = (patch: any) => act(() => request("/api/admin/sessions/config", put({...cfg, rules: list, ...patch})), toast, "Сохранено", setError, () => { setRules(null); load(); loadAn(); });
  return (
    <Card title="Сессии и аномалии" error={error} hint="Раз в несколько минут магазин спрашивает у панели, кто онлайн на каждой ноде и с каких IP, и склеивает снимки в сессии: IP, провайдер, страна, нода. Аномалия — совпадение с вашими правилами по текущему снимку.">
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => save({enabled: e.target.checked})}/> Собирать сессии</label>
      <label>Опрос раз в (минут)<input type="number" min={2} max={60} defaultValue={cfg.interval_min} onBlur={(e) => save({interval_min: Number(e.target.value)})}/></label>
      <h4>Правила аномалий (любое совпавшее)</h4>
      {list.map((r: any, i: number) => <div className="toolbar" key={i}>
        <input value={r.name} placeholder="Название" onChange={(e) => setRules(list.map((x: any, j: number) => j === i ? {...x, name: e.target.value} : x))}/>
        <select value={r.metric} onChange={(e) => setRules(list.map((x: any, j: number) => j === i ? {...x, metric: e.target.value} : x))}>{Object.entries(d.metrics).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select>
        <span>больше</span><input type="number" min={0} value={r.value} onChange={(e) => setRules(list.map((x: any, j: number) => j === i ? {...x, value: Number(e.target.value)} : x))}/>
        <label className="check"><input type="checkbox" checked={r.per_device} onChange={(e) => setRules(list.map((x: any, j: number) => j === i ? {...x, per_device: e.target.checked} : x))}/> × лимит устройств</label>
        <select value={r.level} onChange={(e) => setRules(list.map((x: any, j: number) => j === i ? {...x, level: e.target.value} : x))}><option value="yellow">жёлтая</option><option value="red">красная</option></select>
        <button className="danger" onClick={() => setRules(list.filter((_: any, j: number) => j !== i))}>×</button></div>)}
      <div className="toolbar">
        <button onClick={() => setRules([...list, {name: "", metric: "ips", value: 2, per_device: true, level: "yellow"}])}>Добавить правило</button>
        <button onClick={() => setRules(d.typical_rules)}>Типовая схема</button>
        <button disabled={!rules} onClick={() => save({})}>Сохранить правила</button>
      </div>
      <h4>Сейчас аномалии</h4>
      {(an?.anomalies || []).length ? <table className="table"><tbody>{an.anomalies.map((a: any) => <tr key={a.panel_user}>
        <td><b className={a.level === "red" ? "error" : "warn"}>●</b> {a.user_id ? `#${a.user_id}` : a.panel_user}</td><td>{a.hits.map((h: any) => `${h.name}: ${h.value} > ${h.limit}`).join("; ")}</td>
        <td>{(a.now || []).map((x: any) => `${x.ip} ${x.isp || ""} ${x.country || ""}`).join(", ")}</td><td>с {day(a.since)}</td></tr>)}</tbody></table> : <p className="muted">Аномалий нет.</p>}
      <CustomerConnections request={request} toast={toast}/>
    </Card>
  );
}

/** Customer card: sessions history, «Сейчас онлайн», drop connections, traffic by day and server. */
export function CustomerConnections({request, toast}: Props) {
  const [id, setId] = useState("");
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const open = async () => {
    setError("");
    try {
      const [sessions, traffic] = await Promise.all([request(`/api/admin/users/${id}/sessions`), request(`/api/admin/users/${id}/traffic?days=${days}`).catch((e: any) => ({error: e.message}))]);
      setData({sessions, traffic, online: null});
    } catch (e: any) { setError(e.message); }
  };
  const max = Math.max(1, ...((data?.traffic?.days || []).map((x: any) => x.bytes)));
  return (
    <>
      <h4>Клиент: сессии, онлайн и трафик</h4>
      {error ? <p className="error">{error}</p> : null}
      <div className="toolbar">
        <input placeholder="ID клиента" value={id} onChange={(e) => setId(e.target.value.replace(/\D/g, ""))}/>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={7}>7 дней</option><option value={30}>30 дней</option><option value={90}>90 дней</option></select>
        <button disabled={!id} onClick={open}>Показать</button>
        <button disabled={!id} onClick={() => act(async () => setData({...data, online: await request(`/api/admin/users/${id}/online`)}), toast, "Обновлено", setError)}>Сейчас онлайн</button>
        <button className="danger" disabled={!id} onClick={() => window.confirm("Сбросить все соединения клиента?") && act(() => request(`/api/admin/users/${id}/drop-connections`, post()), toast, "Готово", setError)}>Сбросить соединения</button>
      </div>
      {data?.online ? <p>{data.online.answered ? (data.online.online.length ? data.online.online.map((n: any) => `${n.node}: ${n.ips.join(", ")}`).join(" · ") : "Сейчас не подключён") : "Панель не ответила"}</p> : null}
      {data ? <>
        <p className="muted">За неделю: IP {data.sessions.week.ips}, провайдеров {data.sessions.week.providers}, стран {data.sessions.week.countries}.</p>
        <table className="table"><tbody>{data.sessions.groups.map((g: any, i: number) => <tr key={i}><td>{g.isp} {g.country}</td><td>{g.ips.join(", ")}</td><td>{g.nodes.join(", ")}</td><td>{day(g.first)} — {day(g.last)}</td></tr>)}</tbody></table>
        {data.traffic.error ? <p className="muted">Трафик: {data.traffic.error}</p> : <>
          <p>Трафик за {data.traffic.range_days} дн.: {gb(data.traffic.total_bytes)}, в среднем {gb(data.traffic.per_day_bytes)} в день{data.traffic.peak ? `, пик ${data.traffic.peak.day} — ${gb(data.traffic.peak.bytes)}` : ""}.</p>
          <div style={{display: "flex", alignItems: "flex-end", gap: 2, height: 80}}>{data.traffic.days.map((x: any) => <div key={x.day} title={`${x.day}: ${gb(x.bytes)}`} style={{flex: 1, background: "var(--accent, #f97316)", height: `${Math.max(2, x.bytes * 100 / max)}%`, borderRadius: 2}}/>)}</div>
          <table className="table"><tbody>{data.traffic.nodes.map((n: any) => <tr key={n.name}><td>{n.name}</td><td>{gb(n.bytes)}</td><td>{n.share}%</td></tr>)}</tbody></table>
        </>}
      </> : null}
    </>
  );
}

/** «Серверы → Пул WireGuard / AmneziaWG». */
export function WgPool({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/wg-pool");
  const [text, setText] = useState("");
  if (!d) return <Card title="Пул WireGuard / AmneziaWG" error={error}><p>Загрузка…</p></Card>;
  const cfg = d.config;
  const save = (patch: any) => act(() => request("/api/admin/wg-pool", put({...cfg, ...patch})), toast, "Сохранено", setError, load);
  return (
    <Card title="Пул WireGuard / AmneziaWG" error={error} hint="Загрузите готовые .conf — клиент с активной подпиской получит свой конфиг в кабинете, Mini App и приложении. Один конфиг — одно устройство, не больше лимита устройств тарифа. Хранятся зашифрованными.">
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => save({enabled: e.target.checked})}/> Выдавать конфиги клиентам</label>
      <label>Только для сквадов (UUID через запятую, пусто — всем)<input defaultValue={(cfg.squads || []).join(", ")} onBlur={(e) => save({squads: e.target.value.split(/[\s,]+/).filter(Boolean)})}/></label>
      <p>{Object.entries(d.stats).map(([k, v]: any) => `${k === "awg" ? "AmneziaWG" : "WireGuard"}: свободно ${v.free}, выдано ${v.assigned}`).join(" · ") || "Пул пуст."}</p>
      <textarea rows={6} placeholder="[Interface]&#10;PrivateKey = …&#10;Address = …&#10;&#10;[Peer]&#10;…" value={text} onChange={(e) => setText(e.target.value)}/>
      <div className="toolbar">
        <button disabled={text.length < 20} onClick={() => act(async () => { const r = await request("/api/admin/wg-pool/upload", post({text})); toast(`Добавлено ${r.added}, из них AmneziaWG ${r.awg}`); setText(""); }, toast, "Загружено", setError, load)}>Загрузить конфиги</button>
        <label className="button">Из файлов<input type="file" multiple accept=".conf,.txt" hidden onChange={async (e) => { const files = Array.from(e.target.files || []); setText((await Promise.all(files.map((f) => f.text()))).join("\n\n")); }}/></label>
        <button className="danger" onClick={() => window.confirm("Удалить все свободные конфиги?") && act(() => request("/api/admin/wg-pool/free", {method: "DELETE"}), toast, "Свободные удалены", setError, load)}>Удалить свободные</button>
      </div>
    </Card>
  );
}

/** Dashboard «События подписок»: payments, panel events and changes made outside the shop. */
export function SubscriptionFeed({request}: {request: Request}) {
  const [d, load, error] = useData(request, "/api/admin/subscription-feed?limit=30");
  const ICON: Record<string, string> = {payment: "💳", panel: "🛰", external: "✏️"};
  return (
    <Card title="События подписок" error={error} hint="Оплаты, события панели и правки не из магазина — по свежести.">
      <div className="toolbar"><button onClick={load}>Обновить</button></div>
      {(d?.items || []).length ? <table className="table"><tbody>{d.items.map((x: any, i: number) => <tr key={i}>
        <td>{day(x.at)}</td><td>{ICON[x.kind] || "•"} {x.title}</td><td>{x.user_id ? `#${x.user_id}` : "—"}</td><td className="muted">{x.detail}</td></tr>)}</tbody></table>
        : <p className="muted">{d ? "Событий пока нет." : "Загрузка…"}</p>}
    </Card>
  );
}

const flag = (cc: string) => (cc && cc.length === 2 ? String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 127397 + c.charCodeAt(0))) : "🌐");

/** «Аналитика → География клиентов»: countries and providers from the sessions. */
export function Geography({request}: {request: Request}) {
  const [days, setDays] = useState(7);
  const [d, , error] = useData(request, `/api/admin/sessions/geo?days=${days}`);
  return (
    <Card title="География клиентов" error={error} hint="Страны и провайдеры, откуда клиенты подключаются (по сессиям; нужен включённый сбор сессий).">
      <div className="toolbar">{[1, 7, 30].map((x) => <button key={x} className={x === days ? "primary" : ""} onClick={() => setDays(x)}>{x === 1 ? "Сутки" : `${x} дней`}</button>)}</div>
      {d && d.countries.length ? <div className="grid3">
        <div>{d.countries.map((c: any) => <div key={c.country} style={{margin: "4px 0"}}>{flag(c.country)} {c.country} — {c.users}
          <div style={{height: 6, borderRadius: 3, background: "var(--accent, #f97316)", width: `${Math.max(2, c.share)}%`}}/></div>)}</div>
        <table className="table"><tbody>{d.providers.map((p: any, i: number) => <tr key={i}><td>{flag(p.country)} {p.isp}</td><td>{p.users}</td></tr>)}</tbody></table>
      </div> : <p className="muted">{d ? "Нет данных за период." : "Загрузка…"}</p>}
    </Card>
  );
}
