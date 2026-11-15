import React, {useEffect, useState} from "react";

/** v28.53 (вкладка «Ноды»): «Скорость у клиентов» — замеры из приложений; «Прогноз нагрузки» — когда нода упрётся в лимит. */
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (t: string) => void};
const put = (body: any): RequestInit => ({method: "PUT", body: JSON.stringify(body)});

export function SpeedAdmin({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [c, setC] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/speedtest").then(x => { setD(x); setC(x.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Скорость у клиентов</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  async function save() { setError(""); try { setC(await request("/api/admin/speedtest", put(c))); toast("Настройки сохранены"); load(); } catch (e: any) { setError(e.message); } }
  const n = (k: string, label: string) => <label className="field">{label}<input type="number" value={c[k]} onChange={e => setC({...c, [k]: Number(e.target.value)})}/></label>;
  return (
    <div className="card">
      <h3>Скорость у клиентов</h3>
      <p className="muted">Клиенты проверяют скорость в приложении: загрузка через текущее подключение и время ответа. Здесь — замеры с включённым VPN за 7 дней по серверам. Сервер медленнее порога (при достаточном числе замеров) отмечается, и раз в день вам приходит сообщение.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Проверка скорости в приложениях</label>
        <label><input type="checkbox" checked={!!c.alert} onChange={e => setC({...c, alert: e.target.checked})}/> Сообщать о медленных серверах</label>
      </div>
      <div className="form-grid">{n("slow_mbps", "Медленно, если медиана ниже, Мбит/с")}{n("min_runs", "Замеров для вывода, от")}{n("max_mb", "Размер загрузки, МБ")}{n("runs_per_hour", "Проверок в час на клиента")}</div>
      <button className="primary" onClick={save}>Сохранить</button>
      {!d?.servers?.length ? <p className="muted">Замеров пока нет.</p> :
        <table className="table"><thead><tr><th>Сервер</th><th>Замеров</th><th>Медиана, Мбит/с</th><th>Худшая четверть</th><th>Отклик, мс</th><th>Приложения</th></tr></thead><tbody>
          {d.servers.map((s: any) => <tr key={s.server} className={s.slow ? "warn" : ""}><td>{s.slow ? "⚠️ " : ""}{s.server}</td><td>{s.runs}</td><td>{s.median_mbps}</td><td>{s.slow_quarter_mbps}</td><td>{s.median_ping_ms ?? "—"}</td><td>{s.platforms.join(", ") || "—"}</td></tr>)}
        </tbody></table>}
    </div>
  );
}

export function ForecastAdmin({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [c, setC] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/nodes/forecast").then(x => { setD(x); setC(x.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Прогноз нагрузки</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  async function save(next = c) { setError(""); try { const r = await request("/api/admin/nodes/forecast", put(next)); setD(r); setC(r.config); toast("Прогноз обновлён"); } catch (e: any) { setError(e.message); } }
  const n = (k: string, label: string) => <label className="field">{label}<input type="number" value={c[k]} onChange={e => setC({...c, [k]: Number(e.target.value)})}/></label>;
  const setCap = (uuid: string, v: number) => setC({...c, capacities: {...(c.capacities || {}), [uuid]: v}});
  return (
    <div className="card">
      <h3>Прогноз нагрузки</h3>
      <p className="muted">Каждые 30 минут сохраняется дневной пик клиентов онлайн на каждой ноде. По тренду за последние недели видно, через сколько дней нода упрётся в свой лимит. Укажите лимит каждой ноды — сколько клиентов онлайн она выдерживает.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline"><label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Считать прогноз и предупреждать</label></div>
      <div className="form-grid">{n("default_capacity", "Лимит по умолчанию, клиентов онлайн")}{n("window_days", "Тренд по последним, дней")}{n("warn_days", "Предупреждать, если до лимита меньше, дней")}{n("busy_percent", "Или нагрузка уже от, %")}</div>
      {!d?.nodes?.length ? <p className="muted">Данных пока нет — первые замеры появятся через полчаса.</p> :
        <table className="table"><thead><tr><th>Нода</th><th>Пик сегодня</th><th>Лимит</th><th>Нагрузка</th><th>Рост в день</th><th>До лимита</th></tr></thead><tbody>
          {d.nodes.map((x: any) => <tr key={x.uuid} className={x.flagged ? "warn" : ""}><td>{x.flagged ? "⚠️ " : ""}{x.name}</td><td>{x.peak}</td>
            <td><input type="number" style={{width: 90}} aria-label={`Лимит ${x.name}`} value={(c.capacities || {})[x.uuid] ?? c.default_capacity} onChange={e => setCap(x.uuid, Number(e.target.value))}/></td>
            <td>{x.load_percent}%</td><td>{x.per_day > 0 ? `+${x.per_day}` : x.per_day}</td><td>{x.days_left == null ? "—" : `~${x.days_left} дн.`}</td></tr>)}
        </tbody></table>}
      <button className="primary" onClick={() => save()}>Сохранить</button>
    </div>
  );
}
