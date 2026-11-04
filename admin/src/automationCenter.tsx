import React from "react";
import {StatusBadge, StatusDot, type Tone} from "./components/ui/status";
import {EmptyState} from "./components/ui/state";
import {sectionInfo} from "./sections";

const TONE: Record<string, Tone> = {ok: "ok", warn: "warn", error: "danger", off: "idle"};
const LABEL: Record<string, string> = {ok: "работает", warn: "внимание", error: "не работает", off: "выключено"};
const OVERALL: Record<string, [Tone, string]> = {ok: ["ok", "Автоматика работает"], warn: ["warn", "Есть что проверить"],
  error: ["danger", "Часть автоматики не работает"]};
const HEALTH: Record<string, [Tone, string]> = {ok: ["ok", "Все системы работают"], attention: ["warn", "Есть что проверить"],
  degraded: ["danger", "Есть неработающие части"], error: ["danger", "Проверка не завершилась"]};
const when = (x: string | null) => (x ? new Date(/Z|[+-]\d\d:\d\d$/.test(x) ? x : x + "Z").toLocaleString("ru-RU") : "—");

/** «Система → Automation Center» (v28.74.0, этап 15). Data: GET /api/admin/automation-center
 *  (backend/app/automation_center.py): every automatic process with its state, schedule and last run, plus the
 *  summary of «Состояние системы». Buttons open the section where the process is configured. */
export function AutomationCenter({d, navigate, reload}: {d: any; navigate: (tab: string) => void; reload: () => void}) {
  const items: any[] = d?.processes || [];
  const [tone, title] = OVERALL[d?.status] || ["idle", "Нет данных"];
  const health = d?.health || {};
  const [htone, htitle] = HEALTH[health.status] || ["idle", "Нет данных"];
  const counts = Object.entries(health.counts || {}).map(([s, n]) => `${LABEL[s] || s}: ${n}`).join(" · ");
  return <>
    <div className="card" data-automation-status={d?.status || "unknown"}>
      <h3>Automation Center</h3>
      <p><StatusBadge tone={tone}>{title}</StatusBadge></p>
      {items.length === 0 ? <EmptyState title="Нет данных" hint="Сервер не вернул список процессов." action={<button onClick={reload}>Повторить</button>}/> :
        <div className="health-list">
          {items.map(x => <div className="health-row" key={x.key} data-process={x.key} data-status={x.status}>
            <StatusDot tone={TONE[x.status] || "danger"}/>
            <div><b>{x.name}</b><small>{x.detail}</small>
              <small className="muted">{x.schedule ? `Расписание: ${x.schedule}` : ""}{x.schedule && x.last_run ? " · " : ""}{x.last_run ? `Последний запуск: ${when(x.last_run)}` : ""}</small></div>
            <div className="health-actions">
              <em>{LABEL[x.status] || x.status}</em>
              {x.tab && <button onClick={() => navigate(x.tab)}>{sectionInfo(x.tab).item?.label || "Открыть"}</button>}
            </div>
          </div>)}
        </div>}
    </div>
    <div className="card">
      <h3>Состояние системы</h3>
      <p><StatusBadge tone={htone}>{htitle}</StatusBadge> <span className="muted">{counts}</span></p>
      {(health.attention || []).length ? <div className="health-list">
        {health.attention.map((x: any) => <div className="health-row" key={x.key} data-check={x.key} data-status={x.status}>
          <StatusDot tone={TONE[x.status] || "danger"}/>
          <div><b>{x.name}</b><small>{x.detail}</small></div>
          <div className="health-actions">{x.tab && <button onClick={() => navigate(x.tab)}>{sectionInfo(x.tab).item?.label || "Открыть"}</button>}</div>
        </div>)}
      </div> : <p className="muted">Всё, что проверяет «Состояние системы», в норме или не используется.</p>}
      <div className="toolbar"><button onClick={() => navigate("health")}>Все проверки</button><button className="primary" onClick={reload}>Проверить снова</button></div>
      {d?.checked_at ? <p className="muted">Проверено: {when(d.checked_at)}</p> : null}
    </div>
  </>;
}
