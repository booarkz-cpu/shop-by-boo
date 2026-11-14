import React, {useEffect, useState} from "react";

/** v28.47: «Страница статуса» (настройки, подписчики, превью) и «Цены по странам». */
type Request = (path: string, options?: RequestInit) => Promise<any>;
const put = (body: any): RequestInit => ({method: "PUT", body: JSON.stringify(body)});

export function StatusPageAdmin({request, toast, api}: {request: Request; toast: (t: string) => void; api: string}) {
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/status-page").then(setD).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!d) return <div className="card"><h3>Страница статуса</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const c = d.config;
  const set = (k: string, v: any) => setD({...d, config: {...c, [k]: v}});
  async function save() { try { await request("/api/admin/status-page/config", put(c)); toast("Страница статуса сохранена"); load(); } catch (e: any) { setError(e.message); } }
  return (
    <div className="card">
      <div className="toolbar"><h3>Страница статуса</h3><a href={`${api}/status`} target="_blank" rel="noopener">Открыть страницу</a></div>
      <p className="muted">Публичная страница: регионы по серверам, приём оплаты, ваши компоненты и события категории «service» из «Инцидентов». Если все серверы страны недоступны дольше заданного времени, событие открывается само, а когда сервер вернётся — закрывается. Подписчики ({d.subscribers}) получают новости в Telegram и в уведомлениях приложений.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="toolbar">
        <label><input type="checkbox" checked={!!c.enabled} onChange={e => set("enabled", e.target.checked)}/> Страница включена</label>
        <label><input type="checkbox" checked={!!c.notify} onChange={e => set("notify", e.target.checked)}/> Сообщать подписчикам</label>
        <label>Заголовок<input value={c.title || ""} placeholder="Название — статус" onChange={e => set("title", e.target.value)}/></label>
        <label>Сбой региона через, мин<input type="number" min={1} max={120} value={c.outage_minutes} onChange={e => set("outage_minutes", Number(e.target.value))}/></label>
        <label>История, дней<input type="number" min={1} max={180} value={c.history_days} onChange={e => set("history_days", Number(e.target.value))}/></label>
        <button className="primary" onClick={save}>Сохранить</button>
      </div>
      <p>Сейчас: <b>{d.page.overall_label}</b>. {d.page.regions.map((r: any) => `${r.country} ${r.online}/${r.total}`).join(" · ") || "серверов нет"}</p>
    </div>
  );
}

export function RegionalPricing({request, toast}: {request: Request; toast: (t: string) => void}) {
  const [cfg, setCfg] = useState<any>(null);
  const [error, setError] = useState("");
  const [country, setCountry] = useState("KZ");
  const [preview, setPreview] = useState<any>(null);
  useEffect(() => { request("/api/admin/pricing/regions").then(setCfg).catch(e => setError(e.message)); }, [request]);
  if (!cfg) return <div className="card"><h3>Цены по странам</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const regions: any[] = cfg.regions || [];
  const setRegion = (i: number, patch: any) => setCfg({...cfg, regions: regions.map((r, j) => (j === i ? {...r, ...patch} : r))});
  const list = (v: string) => v.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean);
  async function save() {
    setError("");
    try { setCfg(await request("/api/admin/pricing/regions", put(cfg))); toast("Цены по странам сохранены"); } catch (e: any) { setError(e.message); }
  }
  async function check() {
    try { setPreview(await request(`/api/admin/pricing/regions/preview?country=${encodeURIComponent(country)}`)); } catch (e: any) { setError(e.message); }
  }
  return (
    <div className="card">
      <h3>Цены по странам</h3>
      <p className="muted">Для клиентов из выбранных стран цены меняются на процент, а для отдельных тарифов можно задать точную цену. Валюта остаётся валютой магазина. Кассы региона идут в очереди первыми. Страна определяется по адресу клиента; если клиент подключён через ваш сервер, действует обычная цена.</p>
      {error ? <p className="error">{error}</p> : null}
      <label><input type="checkbox" checked={!!cfg.enabled} onChange={e => setCfg({...cfg, enabled: e.target.checked})}/> Включено</label>
      {regions.map((r, i) => (
        <div className="toolbar" key={i}>
          <label>Регион<input value={r.name} onChange={e => setRegion(i, {name: e.target.value})}/></label>
          <label>Страны (KZ, BY…)<input value={(r.countries || []).join(", ")} onChange={e => setRegion(i, {countries: list(e.target.value).map(x => x.toUpperCase())})}/></label>
          <label>Изменение цены, %<input type="number" min={-90} max={300} value={r.percent} onChange={e => setRegion(i, {percent: Number(e.target.value)})}/></label>
          <label>Точные цены (тариф=цена)<input value={Object.entries(r.plan_prices || {}).map(([k, v]) => `${k}=${v}`).join(", ")}
            onChange={e => setRegion(i, {plan_prices: Object.fromEntries(list(e.target.value).map(x => x.split("=")).filter(p => p.length === 2 && p[0] && p[1]))})}/></label>
          <label>Кассы первыми<input value={(r.providers || []).join(", ")} onChange={e => setRegion(i, {providers: list(e.target.value)})}/></label>
          <button onClick={() => setCfg({...cfg, regions: regions.filter((_, j) => j !== i)})}>Удалить</button>
        </div>
      ))}
      <div className="toolbar">
        <button onClick={() => setCfg({...cfg, regions: [...regions, {name: "Новый регион", countries: [], percent: 0, plan_prices: {}, providers: []}]})}>Добавить регион</button>
        <button className="primary" onClick={save}>Сохранить</button>
        <label>Проверить страну<input value={country} maxLength={2} onChange={e => setCountry(e.target.value.toUpperCase())}/></label>
        <button onClick={check}>Показать цены</button>
      </div>
      {preview ? <table className="table"><thead><tr><th>Тариф</th><th>Обычная</th><th>Для {preview.country}{preview.region ? ` (${preview.region})` : ""}</th></tr></thead>
        <tbody>{preview.plans.map((p: any) => <tr key={p.id}><td>{p.id}. {p.name}</td><td>{p.base}</td><td>{p.price}</td></tr>)}</tbody></table> : null}
    </div>
  );
}
