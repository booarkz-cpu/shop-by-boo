import React, {useEffect, useState} from "react";
import {Layers} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Row = {key: string; title: string; installed: string | null; latest: string | null; state: string; auto: string; schedule: string | null; last_result: string | null; how: string; note: string | null};
type View = {checked_at: string; components: Row[]; summary: {total: number; automatic: number; switched_off: number; no_mechanism: number; updates_waiting: number}};

const AUTO: Record<string, [string, "ok" | "warn" | "idle" | "danger"]> = {
  on: ["включено", "ok"],
  in_app: ["в приложении", "ok"],
  off: ["выключено", "warn"],
  not_installed: ["агент не установлен", "danger"],
  none: ["нет", "idle"],
};
const STATE: Record<string, string> = {current: "актуально", update: "есть обновление", unknown: "—", not_installed: "не установлено"};

/** «Обновления → Вся экосистема»: what updates itself from GitHub, what is switched off and what has no mechanism at all. */
export function EcosystemUpdates({request}: {request: RequestFn}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  async function load() {
    try {
      setView(await request("/api/admin/ecosystem-updates"));
      setError("");
    } catch (e: any) {
      setError(e.message || "Состояние недоступно");
    }
  }
  useEffect(() => {
    load();
  }, []);

  const title = <h2><Layers aria-hidden="true" /> Вся экосистема: автообновление с GitHub</h2>;
  if (error) return <section className="card" data-ecosystem aria-label="Вся экосистема">{title}<p role="status"><StatusBadge tone="warn">Нет данных</StatusBadge> {error}</p><button type="button" className="secondary" onClick={load}>Повторить</button></section>;
  if (!view) return <p className="muted card">Загрузка…</p>;
  const s = view.summary;
  return (
    <section className="card" data-ecosystem aria-label="Вся экосистема">
      {title}
      <p className="muted">Одна таблица на всё, из чего состоит магазин. Настройки — в блоках ниже: «Автообновление с GitHub» и «Автообновление Remnawave».</p>
      <p data-eco-summary>
        <StatusBadge tone="ok">Обновляются сами: {s.automatic} из {s.total}</StatusBadge>{" "}
        {s.switched_off > 0 && <StatusBadge tone="warn">Выключено: {s.switched_off}</StatusBadge>}{" "}
        {s.no_mechanism > 0 && <StatusBadge tone="idle">Без автообновления: {s.no_mechanism}</StatusBadge>}{" "}
        {s.updates_waiting > 0 && <StatusBadge tone="warn">Ждут обновления: {s.updates_waiting}</StatusBadge>}
      </p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Часть</th><th>Установлено</th><th>На GitHub</th><th>Состояние</th><th>Автообновление</th><th>Как обновляется</th></tr></thead>
          <tbody>
            {view.components.map((r) => (
              <tr key={r.key} data-eco={r.key}>
                <td>{r.title}</td>
                <td>{r.installed || "—"}</td>
                <td>{r.latest || "—"}</td>
                <td>{STATE[r.state] || r.state}{r.last_result && <><br /><small className="muted">последний запуск: {r.last_result}</small></>}</td>
                <td><StatusBadge tone={(AUTO[r.auto] || AUTO.none)[1]}>{(AUTO[r.auto] || AUTO.none)[0]}</StatusBadge>{r.schedule && <><br /><small className="muted">{r.schedule}</small></>}</td>
                <td>{r.how}{r.note && <><br /><small className="muted">{r.note}</small></>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">Проверено: {new Date(view.checked_at).toLocaleString("ru-RU")}. <button type="button" className="secondary" onClick={load}>Проверить снова</button></p>
    </section>
  );
}
