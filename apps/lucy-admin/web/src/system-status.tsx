import React from "react";
import {StatusBadge, StatusDot, type Tone} from "./components/ui/status";
import {EmptyState} from "./components/ui/state";
import {sectionInfo} from "./sections";

const TONE: Record<string, Tone> = {ok: "ok", warn: "warn", error: "danger", off: "idle"};
const LABEL: Record<string, string> = {ok: "в норме", warn: "внимание", error: "ошибка", off: "не настроено"};
const OVERALL: Record<string, [Tone, string]> = {
  ok: ["ok", "Все системы работают"],
  attention: ["warn", "Работает, но есть что проверить"],
  degraded: ["danger", "Есть неработающие части"],
};

/** «Аналитика → Состояние системы» (v28.62.0, stage 6 — System Control Center).
 *  Data: GET /api/admin/health/summary (backend/app/system_status.py). Every row is a read-only check;
 *  the button opens the section where that part is managed. */
export function SystemStatus({d, navigate, reload}: {d: any; navigate: (tab: string) => void; reload: () => void}) {
  const checks: any[] = d?.checks || [];
  const [tone, title] = OVERALL[d?.status] || ["idle", "Нет данных"];
  const counts = ["error", "warn", "ok", "off"].map(s => [s, checks.filter(c => c.status === s).length] as const).filter(([, n]) => n);
  return <div className="card" data-system-status={d?.status || "unknown"}>
    <h3>Состояние системы</h3>
    <p><StatusBadge tone={tone}>{title}</StatusBadge>{" "}
      <span className="muted">{counts.map(([s, n]) => `${LABEL[s]}: ${n}`).join(" · ")}</span></p>
    {checks.length === 0 ? <EmptyState title="Проверок нет" hint="Сервер не вернул ни одной проверки. Обновите страницу." action={<button onClick={reload}>Повторить</button>}/> :
      <div className="health-list">
        {checks.map(x => <div className="health-row" key={x.key || x.name} data-check={x.key} data-status={x.status}>
          <StatusDot tone={TONE[x.status] || "danger"}/>
          <div><b>{x.name}</b><small>{x.detail || x.error || ""}</small></div>
          <div className="health-actions">
            <em>{x.latency_ms ? `${x.latency_ms} мс` : LABEL[x.status] || x.status}</em>
            {x.tab && <button onClick={() => navigate(x.tab)}>{sectionInfo(x.tab).item?.label || "Открыть"}</button>}
          </div>
        </div>)}
      </div>}
    <p className="muted">Режим инцидента: {d?.incident_mode ? "включён" : "выключен"} · Платежи: {d?.payments_paused ? "приостановлены" : "принимаются"}
      {d?.checked_at && <> · Проверено: {new Date(String(d.checked_at).endsWith("Z") ? d.checked_at : d.checked_at + "Z").toLocaleTimeString()}</>}</p>
    <button className="primary" onClick={reload}>Проверить снова</button>
  </div>;
}
