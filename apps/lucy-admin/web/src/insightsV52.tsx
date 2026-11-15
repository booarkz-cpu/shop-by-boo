import React, {useEffect, useState} from "react";

/** v28.52: «Оценки и NPS» (вкладка «Поддержка»), «Когорты» и «Еженедельная сводка» (вкладка «Аналитика»). */
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (t: string) => void};
const put = (body: any): RequestInit => ({method: "PUT", body: JSON.stringify(body)});

export function FeedbackAdmin({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [c, setC] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/feedback?days=90").then(x => { setD(x); setC(x.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Оценки поддержки и NPS</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  async function save() { setError(""); try { setC(await request("/api/admin/feedback", put(c))); toast("Настройки оценок сохранены"); load(); } catch (e: any) { setError(e.message); } }
  const n = (k: string, label: string) => <label className="field">{label}<input type="number" value={c[k]} onChange={e => setC({...c, [k]: Number(e.target.value)})}/></label>;
  return (
    <div className="card">
      <h3>Оценки поддержки и NPS</h3>
      <p className="muted">После ответа оператора клиент получает просьбу оценить ответ от 1 до 5 (оценки 1–2 сразу приходят вам). Раз в квартал платящие клиенты отвечают, порекомендуют ли вас (0–10). NPS — доля промоутеров (9–10) минус доля критиков (0–6).</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label><input type="checkbox" checked={!!c.csat_enabled} onChange={e => setC({...c, csat_enabled: e.target.checked})}/> Просить оценить ответ поддержки</label>
        <label><input type="checkbox" checked={!!c.nps_enabled} onChange={e => setC({...c, nps_enabled: e.target.checked})}/> Опрос NPS</label>
      </div>
      <div className="form-grid">{n("csat_delay_minutes", "Через сколько минут после ответа")}{n("nps_interval_days", "Опрос NPS раз в, дней")}{n("nps_min_days", "Клиент с нами не меньше, дней")}{n("nps_batch", "Опросов за один проход")}</div>
      <button className="primary" onClick={save}>Сохранить</button>
      <h4>За 90 дней</h4>
      <p className="muted">Оценка поддержки: {d.csat.average ?? "—"} из 5 · довольных {d.csat.satisfied_percent ?? "—"}% · оценок {d.csat.count}. NPS: {d.nps.score ?? "—"} (промоутеров {d.nps.promoters}, нейтральных {d.nps.passives}, критиков {d.nps.detractors}).</p>
      {d.csat.operators.length ? <table className="table"><thead><tr><th>Оператор</th><th>Оценок</th><th>Средняя</th></tr></thead><tbody>
        {d.csat.operators.map((o: any) => <tr key={o.operator}><td>{o.operator}</td><td>{o.count}</td><td>{o.average}</td></tr>)}</tbody></table> : null}
      {d.nps.months.length ? <table className="table"><thead><tr><th>Месяц</th><th>Ответов</th><th>NPS</th></tr></thead><tbody>
        {d.nps.months.map((m: any) => <tr key={m.month}><td>{m.month}</td><td>{m.count}</td><td>{m.score}</td></tr>)}</tbody></table> : null}
      {d.comments.length ? <><h4>Комментарии</h4><table className="table"><thead><tr><th>Когда</th><th>Оценка</th><th>Комментарий</th></tr></thead><tbody>
        {d.comments.map((x: any, i: number) => <tr key={i}><td>{x.at.slice(0, 10)}</td><td>{x.kind === "csat" ? `${x.score}/5 · #${x.ticket_id}` : `NPS ${x.score}`}</td><td>{x.comment}</td></tr>)}</tbody></table></> : null}
    </div>
  );
}

export function CohortsAdmin({request}: {request: Request}) {
  const [d, setD] = useState<any>(null);
  const [bySource, setBySource] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { request(`/api/admin/cohorts?months=12&by_source=${bySource}`).then(setD).catch(e => setError(e.message)); }, [request, bySource]);
  const cell = (v: any) => v == null ? "—" : `${v}%`;
  return (
    <div className="card">
      <h3>Когорты</h3>
      <p className="muted">Клиенты по месяцу первой оплаты: какая доля ещё с вами через 1, 3, 6 и 12 месяцев и сколько денег принесла когорта. «—» — этот срок ещё не наступил.</p>
      <label><input type="checkbox" checked={bySource} onChange={e => setBySource(e.target.checked)}/> По источникам привлечения</label>
      {error ? <p className="error">{error}</p> : null}
      {!d ? <p>Загрузка…</p> : !d.cohorts.length ? <p className="muted">Оплат за последние 12 месяцев нет.</p> :
        <table className="table"><thead><tr><th>Месяц</th>{bySource && <th>Источник</th>}<th>Клиентов</th><th>1 мес.</th><th>3 мес.</th><th>6 мес.</th><th>12 мес.</th><th>Выручка</th><th>На клиента</th></tr></thead><tbody>
          {d.cohorts.map((c: any) => <tr key={c.month + (c.source || "")}><td>{c.month}</td>{bySource && <td>{c.source}</td>}<td>{c.size}</td><td>{cell(c.m1)}</td><td>{cell(c.m3)}</td><td>{cell(c.m6)}</td><td>{cell(c.m12)}</td><td>{c.revenue} ₽</td><td>{c.arpu} ₽</td></tr>)}
        </tbody></table>}
    </div>
  );
}

export function DigestAdmin({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [c, setC] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/digest").then(x => { setD(x); setC(x.config); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  if (!c) return <div className="card"><h3>Еженедельная сводка</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  async function save() { setError(""); try { setC(await request("/api/admin/digest", put({enabled: c.enabled, weekday: c.weekday, time: c.time}))); toast("Сводка настроена"); } catch (e: any) { setError(e.message); } }
  async function sendNow() { try { const r = await request("/api/admin/digest/send", {method: "POST"}); toast(r.ok ? "Сводка отправлена" : "Не удалось отправить — проверьте чат для оповещений"); } catch (e: any) { setError(e.message); } }
  return (
    <div className="card">
      <h3>Еженедельная сводка</h3>
      <p className="muted">Одно сообщение в Telegram: выручка, новые и ушедшие клиенты, кассы и ноды, оценки поддержки и один совет на неделю.</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label><input type="checkbox" checked={!!c.enabled} onChange={e => setC({...c, enabled: e.target.checked})}/> Присылать каждую неделю</label>
        <label className="field">День<select value={c.weekday} onChange={e => setC({...c, weekday: Number(e.target.value)})}>{(d?.weekdays || []).map((w: string, i: number) => <option key={i} value={i}>{w}</option>)}</select></label>
        <label className="field">Время (МСК)<input value={c.time} onChange={e => setC({...c, time: e.target.value})} placeholder="09:00"/></label>
      </div>
      <div className="inline"><button className="primary" onClick={save}>Сохранить</button><button onClick={sendNow}>Отправить сейчас</button></div>
      <h4>Так выглядит сводка сейчас</h4>
      <pre className="digest-preview">{d?.preview}</pre>
    </div>
  );
}
