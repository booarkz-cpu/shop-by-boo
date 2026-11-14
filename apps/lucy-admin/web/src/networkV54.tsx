import React, {useEffect, useState} from "react";

/** v28.54: «Фильтр рекламы и детский режим», «Регионы (GeoLite2)», «RIPE Atlas — проверка доступности». */
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (t: string) => void};
const put = (body: any): RequestInit => ({method: "PUT", body: JSON.stringify(body)});

export function DnsFilterAdmin({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/dns-filter").then(x => {
    setD(x); setEnabled(!!x.config.enabled);
    const r = Object.entries(x.config.squads || {}).map(([base, v]: any) => ({base, ads: v.ads || "", kids: v.kids || ""}));
    setRows(r.length ? r : [{base: "*", ads: "", kids: ""}]);
  }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!d) return <div className="card"><h3>Фильтр рекламы и детский режим</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const squads = d.panel_squads || [];
  const pick = (value: string, onChange: (v: string) => void, label: string) => squads.length
    ? <select aria-label={label} value={value} onChange={e => onChange(e.target.value)}><option value="">—</option>{squads.map((s: any) => <option key={s.uuid} value={s.uuid}>{s.name}</option>)}</select>
    : <input aria-label={label} value={value} onChange={e => onChange(e.target.value)} placeholder="UUID сквада"/>;
  const set = (i: number, patch: any) => setRows(rows.map((r, j) => j === i ? {...r, ...patch} : r));
  async function save() {
    setError("");
    const squadsMap: any = {};
    rows.filter(r => r.base).forEach(r => { squadsMap[r.base] = {...(r.ads ? {ads: r.ads} : {}), ...(r.kids ? {kids: r.kids} : {})}; });
    try { await request("/api/admin/dns-filter", put({enabled, squads: squadsMap})); toast("Фильтры сохранены"); load(); } catch (e: any) { setError(e.message); }
  }
  return (
    <div className="card">
      <h3>Фильтр рекламы и детский режим</h3>
      <p className="muted">Клиент включает фильтр в кабинете, боте или приложении, владелец семьи — для участника. Фильтрация идёт на нодах: создайте в Remnawave профиль конфигурации с правилами блокировки (готовые правила — в документации модуля) и сквад с этим профилем. Затем укажите здесь, какой сквад использовать вместо сквада тарифа. «*» — для всех тарифов.</p>
      {error ? <p className="error">{error}</p> : null}
      <label><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}/> Фильтры доступны клиентам</label>
      <table className="table"><thead><tr><th>Сквад тарифа</th><th>«Без рекламы»</th><th>«Детский режим»</th><th/></tr></thead><tbody>
        {rows.map((r, i) => <tr key={i}>
          <td>{squads.length ? <select aria-label="Сквад тарифа" value={r.base} onChange={e => set(i, {base: e.target.value})}><option value="*">* — все тарифы</option>{squads.map((s: any) => <option key={s.uuid} value={s.uuid}>{s.name}</option>)}</select>
                             : <input aria-label="Сквад тарифа" value={r.base} onChange={e => set(i, {base: e.target.value})}/>}</td>
          <td>{pick(r.ads, v => set(i, {ads: v}), "Сквад без рекламы")}</td>
          <td>{pick(r.kids, v => set(i, {kids: v}), "Сквад детского режима")}</td>
          <td>{rows.length > 1 && <button onClick={() => setRows(rows.filter((_, j) => j !== i))}>Убрать</button>}</td>
        </tr>)}
      </tbody></table>
      <div className="inline"><button onClick={() => setRows([...rows, {base: "", ads: "", kids: ""}])}>Добавить строку</button><button className="primary" onClick={save}>Сохранить</button></div>
      <p className="muted">Включено у клиентов: без рекламы — {d.counts?.ads ?? 0}, детский режим — {d.counts?.kids ?? 0}.</p>
    </div>
  );
}

export function GeoIpAdmin({request, toast}: Props) {
  const [s, setS] = useState<any>(null);
  const [geo, setGeo] = useState<any>(null);
  const [account, setAccount] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const load = () => Promise.all([request("/api/admin/geoip"), request("/api/admin/sessions/geo?days=7")]).then(([a, g]) => { setS(a); setAccount(a.account_id); setGeo(g); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!s) return <div className="card"><h3>Регионы клиентов</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  async function save() { setError(""); try { setS(await request("/api/admin/geoip", put({account_id: account, license_key: key}))); setKey(""); toast("Ключ MaxMind сохранён"); } catch (e: any) { setError(e.message); } }
  async function update() { setError(""); try { setS(await request("/api/admin/geoip/update", {method: "POST"})); toast("База регионов обновлена"); load(); } catch (e: any) { setError(e.message); } }
  return (
    <div className="card">
      <h3>Регионы клиентов</h3>
      <p className="muted">Страну адреса магазин знает и так. Для регионов внутри страны нужна база GeoLite2: зарегистрируйтесь на maxmind.com (бесплатно), создайте лицензионный ключ и укажите его здесь. База обновляется раз в неделю. {s.attribution}</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="form-grid">
        <label className="field">ID аккаунта MaxMind<input value={account} onChange={e => setAccount(e.target.value)}/></label>
        <label className="field">Лицензионный ключ<input type="password" value={key} placeholder={s.key_set ? "сохранён — введите, чтобы заменить" : ""} onChange={e => setKey(e.target.value)}/></label>
      </div>
      <div className="inline"><button className="primary" onClick={save}>Сохранить</button><button onClick={update} disabled={!s.key_set}>Обновить базу</button></div>
      <p className="muted">{s.database ? `База загружена: ${s.updated_at?.slice(0, 10) || "—"}, ${s.size_mb} МБ.` : "База не загружена."}{s.error ? ` Ошибка: ${s.error}` : ""}</p>
      {geo?.regions?.length ? <table className="table"><thead><tr><th>Страна</th><th>Регион</th><th>Клиентов за 7 дней</th></tr></thead><tbody>
        {geo.regions.map((r: any) => <tr key={r.country + r.region}><td>{r.country}</td><td>{r.region}</td><td>{r.users}</td></tr>)}</tbody></table> : null}
    </div>
  );
}

export function RipeAtlasAdmin({request, toast}: Props) {
  const [c, setC] = useState<any>(null);
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const load = () => request("/api/admin/ripe-atlas").then(setC).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>RIPE Atlas — доступность из России</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  async function save() {
    setError("");
    const {enabled, country, probes, interval_hours, wait_minutes, ok_share} = c;
    try { const r = await request("/api/admin/ripe-atlas", put({enabled, country, probes, interval_hours, wait_minutes, ok_share, api_key: key})); setC({...c, ...r}); setKey(""); toast("Настройки RIPE Atlas сохранены"); } catch (e: any) { setError(e.message); }
  }
  async function run() { setError(""); try { const r = await request("/api/admin/ripe-atlas/run", {method: "POST"}); toast(`Проверка запущена: ${r.targets} адресов, результаты через ${c.wait_minutes} мин.`); load(); } catch (e: any) { setError(e.message); } }
  const n = (k: string, label: string, step = 1) => <label className="field">{label}<input type="number" step={step} value={c[k]} onChange={e => setC({...c, [k]: Number(e.target.value)})}/></label>;
  const results = Object.entries(c.last_results || {});
  return (
    <div className="card">
      <h3>RIPE Atlas — доступность из России</h3>
      <p className="muted">Адреса API и ноды проверяются с зондов RIPE Atlas у российских провайдеров (TCP и TLS, как подключается VPN), своих серверов в России не нужно. Результаты попадают в монитор блокировок как ещё одна проба: при блокировке — те же оповещения, перестановка резервных адресов и резервный сквад. Нужен ключ API с кредитами на измерения (atlas.ripe.net → API keys).</p>
      {error ? <p className="error">{error}</p> : null}
      <label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Проверять автоматически</label>
      <div className="form-grid">
        <label className="field">Ключ API<input type="password" value={key} placeholder={c.key_set ? "сохранён — введите, чтобы заменить" : ""} onChange={e => setKey(e.target.value)}/></label>
        <label className="field">Страна зондов<input value={c.country} maxLength={2} onChange={e => setC({...c, country: e.target.value.toUpperCase()})}/></label>
        {n("probes", "Зондов на адрес")}{n("interval_hours", "Проверять раз в, часов")}{n("wait_minutes", "Ждать результатов, минут")}{n("ok_share", "Доступен, если успешно у доли зондов", 0.05)}
      </div>
      <div className="inline"><button className="primary" onClick={save}>Сохранить</button><button onClick={run} disabled={!c.key_set}>Проверить сейчас</button></div>
      <p className="muted">Последний запуск: {c.last_run?.slice(0, 16).replace("T", " ") || "—"}{c.pending ? " · ждём результаты" : ""}{c.last_error ? ` · ошибка: ${c.last_error}` : ""}</p>
      {results.length ? <table className="table"><thead><tr><th>Адрес</th><th>Успешно</th><th>Итог</th></tr></thead><tbody>
        {results.map(([t, r]: any) => <tr key={t} className={r.reachable ? "" : "warn"}><td>{r.label || t}</td><td>{r.ok} из {r.total}</td><td>{r.total ? (r.reachable ? "доступен" : "⚠️ недоступен") : "нет ответов"}</td></tr>)}</tbody></table> : null}
    </div>
  );
}
