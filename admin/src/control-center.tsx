import React, {useEffect, useState} from "react";
import {sectionInfo} from "./sections";

type Request = (path: string, options?: RequestInit) => Promise<any>;

const OPS: [string, string][] = [
  ["read", "Чтение"], ["create", "Создание"], ["update", "Изменение"], ["delete", "Удаление"],
  ["search", "Поиск/фильтр"], ["settings", "Настройки"], ["diagnostics", "Проверка"], ["audit", "Журнал"],
];

/** «Система → Админ-центр» (v28.60.0, stage 6): the 30 modules of the platform and how the panel manages them.
 *  The operations come from the API routes (GET /api/admin/control-center), not from this file. */
export function ControlCenter({request, navigate}: {request: Request; navigate: (tab: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/control-center").then(setData).catch((e: any) => setError(e.message)); }, []);
  if (!data) return <div className="card">{error ? <div role="alert" className="error">{error}</div> : <p className="muted">Загрузка…</p>}</div>;
  const ready = data.modules.filter((m: any) => !m.missing).length;
  return <div className="card table-card" data-control-center>
    <h3>Админ-центр</h3>
    <p className="muted">{ready} из {data.modules.length} модулей управляются из панели. {data.note} Модули без раздела появятся на указанных этапах; до тех пор в панели нет их кнопок.</p>
    <div className="table-wrap">
      <table>
        <thead><tr><th>№</th><th>Модуль</th><th>Разделы панели</th>{OPS.map(([key, label]) => <th key={key}>{label}</th>)}<th>Права</th></tr></thead>
        <tbody>
          {data.modules.map((m: any) => <tr key={m.number} data-module={m.module} data-status={m.status}>
            <td>{m.number}</td>
            <td><b>{m.module}</b>{m.missing && <div className="muted">{m.missing}</div>}</td>
            <td>{m.tabs.length ? m.tabs.map((tab: string) => <button key={tab} onClick={() => navigate(tab)}>{sectionInfo(tab).item?.label || tab}</button>) : <span className="muted">нет раздела</span>}</td>
            {OPS.map(([key]) => <td key={key} aria-label={m.operations[key] ? "есть" : "нет"}>{m.missing ? "—" : m.operations[key] ? "✓" : "·"}</td>)}
            <td className="muted">{m.permissions.join(", ") || "—"}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
  </div>;
}

/** «Безопасность → Роли и администраторы»: which role holds which permission (read-only; roles are part of the code). */
export function RolesMatrix({request}: {request: Request}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/roles").then(setData).catch((e: any) => setError(e.message)); }, []);
  if (!data) return error ? <div className="card"><div role="alert" className="error">{error}</div></div> : null;
  return <div className="card table-card" data-roles-matrix>
    <h3>Права ролей</h3>
    <p className="muted">Роль администратора выбирается выше, в списке администраторов. Набор прав каждой роли задан в коде магазина и одинаков на всех установках. Ваша роль: <b>{data.your_role}</b>.</p>
    <div className="table-wrap">
      <table>
        <thead><tr><th>Право</th>{data.roles.map((r: any) => <th key={r.role}>{r.role}</th>)}</tr></thead>
        <tbody>
          {data.permissions.map((p: any) => <tr key={p.key}>
            <td>{p.label} <code className="muted">{p.key}</code></td>
            {data.roles.map((r: any) => <td key={r.role}>{r.permissions.includes(p.key) ? "✓" : ""}</td>)}
          </tr>)}
        </tbody>
      </table>
    </div>
  </div>;
}

/** «Безопасность → Журнал действий»: search by administrator, action, target and period, page by page. */
export function AuditLog({request}: {request: Request}) {
  const [filters, setFilters] = useState({actor: "", action: "", target: "", since: "", until: ""});
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<any[]>([]);
  const [error, setError] = useState("");
  const size = 50;
  async function load(nextPage = page) {
    setError("");
    const query = new URLSearchParams({page: String(nextPage), page_size: String(size)});
    for (const [key, value] of Object.entries(filters)) if (value.trim()) query.set(key, value.trim());
    try {
      const result = await request(`/api/admin/audit?${query}`);
      setRows(result); setPage(nextPage);
    } catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(1); }, []);
  const field = (key: keyof typeof filters, label: string, type = "text", placeholder = "") =>
    <label className="field">{label}<input type={type} value={filters[key]} placeholder={placeholder}
      onChange={(e) => setFilters({...filters, [key]: e.target.value})} onKeyDown={(e) => { if (e.key === "Enter") load(1); }}/></label>;
  return <div className="card table-card" data-audit-log>
    <h3>Журнал действий</h3>
    <p className="muted">Каждое изменение администратора: кто, когда, что и над чем. Записи не изменяются и не удаляются.</p>
    <div className="filters">
      {field("actor", "Администратор", "text", "email или часть")}
      {field("action", "Действие начинается с", "text", "например, payment.")}
      {field("target", "Цель", "text", "ID или ключ")}
      {field("since", "С", "date")}
      {field("until", "По (не включая)", "date")}
      <button className="primary" onClick={() => load(1)}>Найти</button>
    </div>
    {error && <div role="alert" className="error">{error}</div>}
    <div className="table-wrap">
      <table>
        <thead><tr><th>Время</th><th>Администратор</th><th>Действие</th><th>Цель</th></tr></thead>
        <tbody>{rows.map((x: any) => <tr key={x.id}><td>{x.created_at}</td><td>{x.actor}</td><td><code>{x.action}</code></td><td>{x.target || "—"}</td></tr>)}</tbody>
      </table>
    </div>
    {!rows.length && !error && <p className="muted">Ничего не найдено.</p>}
    <div className="btn-row">
      <button disabled={page <= 1} onClick={() => load(page - 1)}>Назад</button>
      <span className="muted">Страница {page}</span>
      <button disabled={rows.length < size} onClick={() => load(page + 1)}>Дальше</button>
    </div>
  </div>;
}
