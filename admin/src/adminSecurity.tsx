import React, {useEffect, useState} from "react";
import {StatusBadge} from "./components/ui/status";
import {stepUp} from "./stepUp";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const when = (x: string | null | undefined) => (x ? new Date(/Z|[+-]\d\d:\d\d$/.test(x) ? x : x + "Z").toLocaleString("ru-RU") : "—");

/** «Защита и 2FA»: подтверждение опасных действий — состояние этой сессии и список действий (v28.75.0). */
export function StepUpPanel({request, toast}: {request: Request; toast?: (text: string) => void}) {
  const [state, setState] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/security/step-up").then(setState).catch((e: any) => setError(e.message || "Недоступно"));
  useEffect(() => { load(); }, []);
  async function confirmNow() {
    if (await stepUp((p, o) => request(p, o))) { toast?.("Подтверждено на 10 минут"); load(); }
  }
  if (error) return null;  // a role without «security.stepup» does no dangerous actions
  return <div className="card">
    <h3>Подтверждение опасных действий</h3>
    <p className="muted">Перед действиями ниже панель попросит {state?.method === "totp" ? "код двухфакторной защиты" : "пароль"}.
      Подтверждение действует 10 минут и только в этой сессии: украденного входа недостаточно, чтобы восстановить копию или добавить администратора.</p>
    <p>{state?.fresh ? <StatusBadge tone="ok">Подтверждено, осталось {Math.ceil((state.expires_in || 0) / 60)} мин</StatusBadge>
      : <StatusBadge tone="idle">Не подтверждено</StatusBadge>}</p>
    {state?.method === "password" ? <p className="muted">Включите двухфакторную защиту выше: тогда подтверждение будет кодом, а не паролем.</p> : null}
    <details><summary>Какие действия требуют подтверждения</summary><ul>{(state?.actions || []).map((a: any) => <li key={a.method + a.path}>{a.title}</li>)}</ul></details>
    <div className="toolbar"><button disabled={!state || state.fresh} onClick={confirmNow}>Подтвердить сейчас</button></div>
  </div>;
}

/** Свои сессии: где выполнен вход, завершить лишние (право sessions.self). */
export function MySessions({request, toast}: {request: Request; toast?: (text: string) => void}) {
  const [rows, setRows] = useState<any[] | null>(null);
  const load = () => request("/api/admin/sessions/mine").then(setRows).catch(() => setRows(null));
  useEffect(() => { load(); }, []);
  if (!rows) return null;
  async function revoke(id: number) {
    if (!confirm("Завершить эту сессию?")) return;
    await request(`/api/admin/sessions/mine/${id}`, {method: "DELETE"});
    toast?.("Сессия завершена");
    load();
  }
  return <div className="card">
    <h3>Мои сессии</h3>
    <table className="table"><thead><tr><th>Устройство</th><th>IP</th><th>Вход</th><th>Активность</th><th></th></tr></thead>
      <tbody>{rows.map(s => <tr key={s.id}>
        <td>{(s.user_agent || "—").slice(0, 80)}{s.current ? <> <StatusBadge tone="info">эта</StatusBadge></> : null}</td><td>{s.ip || "—"}</td>
        <td>{when(s.created_at)}</td><td>{when(s.last_seen_at)}</td>
        <td>{s.current ? null : <button className="danger" onClick={() => revoke(s.id)}>Завершить</button>}</td></tr>)}</tbody></table>
  </div>;
}

/** «Сессии»: история безопасности — входы, неудачные попытки, подтверждения, роли, 2FA, терминал (право sessions.manage). */
export function SecurityHistory({request}: {request: Request}) {
  const [data, setData] = useState<any>(null);
  const [days, setDays] = useState(30);
  const [onlyWarn, setOnlyWarn] = useState(false);
  useEffect(() => { request(`/api/admin/security/history?days=${days}`).then(setData).catch(() => setData(null)); }, [days]);
  if (!data) return null;
  const events = (data.events || []).filter((e: any) => !onlyWarn || e.level === "warn");
  const s = data.summary || {};
  return <div className="card">
    <h3>История безопасности</h3>
    <p>{s.failed_logins_24h ? <StatusBadge tone="warn">Неудачных входов за сутки: {s.failed_logins_24h} (адресов: {s.failed_login_ips_24h})</StatusBadge>
      : <StatusBadge tone="ok">Неудачных входов за сутки нет</StatusBadge>}{" "}
      <span className="muted">Входов: {s.logins} · подтверждений опасных действий: {s.step_ups}</span></p>
    <div className="toolbar">
      <label>Период<select value={days} onChange={e => setDays(Number(e.target.value))}>{[1, 7, 30, 90].map(d => <option key={d} value={d}>{d} дн.</option>)}</select></label>
      <label className="check"><input type="checkbox" checked={onlyWarn} onChange={e => setOnlyWarn(e.target.checked)}/> Только требующие внимания</label>
    </div>
    <table className="table"><thead><tr><th>Время</th><th>Событие</th><th>Кто</th><th>Где / что</th></tr></thead>
      <tbody>{events.map((e: any) => <tr key={e.id} data-level={e.level}>
        <td>{when(e.at)}</td><td>{e.level === "warn" ? <StatusBadge tone="warn">{e.title}</StatusBadge> : e.title}</td>
        <td>{e.actor}</td><td>{e.target || "—"}</td></tr>)}</tbody></table>
    {events.length === 0 ? <p className="muted">Событий за период нет.</p> : null}
  </div>;
}
