import React, {useEffect, useState} from "react";
import {StatusBadge, type Tone} from "./components/ui/status";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type State = {
  available: boolean;
  agent_alive: boolean;
  setup_hint: string | null;
  pending_run: boolean;
  status: {enabled?: boolean; time?: string; installed?: string; latest?: string; running?: boolean; last_run_at?: string;
    last_result?: string; last_message?: string; next_run?: string; recovery_mode?: boolean; failed_release?: string; log_tail?: string[]};
  request: {enabled?: boolean; time?: string; updated_by?: string; updated_at?: string};
};

const RESULT: Record<string, [string, Tone]> = {
  updated: ["Обновлено", "ok"],
  current: ["Версия актуальна", "ok"],
  skipped: ["Пропущено", "idle"],
  failed: ["Ошибка, выполнен откат", "danger"],
};

/** «Выпуски → Автообновление»: расписание, «Обновить сейчас» и итог последней установки с GitHub. */
export function AutoUpdate({request, toast}: {request: Request; toast?: (text: string) => void}) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [time, setTime] = useState("03:00");
  const [busy, setBusy] = useState(false);

  async function load(syncForm = false) {
    try {
      const next: State = await request("/api/admin/auto-update");
      setState(next);
      setError("");
      if (syncForm) {
        setEnabled(next.request.enabled ?? next.status.enabled ?? true);
        setTime(next.request.time ?? next.status.time ?? "03:00");
      }
    } catch (e: any) {
      setError(e.message || "Состояние недоступно");
    }
  }

  useEffect(() => {
    load(true);
    const timer = setInterval(() => load(false), 15000);
    return () => clearInterval(timer);
  }, []);

  async function save() {
    setBusy(true);
    try {
      setState(await request("/api/admin/auto-update", {method: "PUT", body: JSON.stringify({enabled, time})}));
      toast?.("Настройки переданы агенту, применятся в течение минуты");
    } catch (e: any) {
      setError(e.message || "Не сохранено");
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    if (!confirm("Проверить GitHub и установить новый выпуск сейчас? Во время установки магазин может быть недоступен 1–3 минуты.")) return;
    setBusy(true);
    try {
      setState(await request("/api/admin/auto-update/run", {method: "POST"}));
      toast?.("Запрос отправлен: агент начнёт проверку в течение минуты");
    } catch (e: any) {
      setError(e.message || "Запуск не принят");
    } finally {
      setBusy(false);
    }
  }

  const s = state?.status || {};
  const result = s.last_result ? RESULT[s.last_result] || [s.last_result, "info" as Tone] : null;
  const ready = !!state?.available;
  return (
    <div className="card">
      <h3>Автообновление с GitHub</h3>
      {error ? <p className="error">{error}</p> : null}
      {state && !state.agent_alive ? (
        <div className="alert">Агент на сервере не отвечает. {state.setup_hint}</div>
      ) : null}
      {s.recovery_mode ? <div className="error">Сервер в режиме восстановления после неудачного обновления: автообновление остановлено до ручной проверки.</div> : null}
      <p><span>Установлено</span>: <b>{s.installed || "—"}</b> · <span>На GitHub</span>: {s.latest || "—"}</p>
      <p>
        <span>Статус</span>:{" "}
        {s.running ? <StatusBadge tone="info">Идёт обновление…</StatusBadge>
          : state?.pending_run ? <StatusBadge tone="info">Ожидает агента</StatusBadge>
          : result ? <StatusBadge tone={result[1]}>{result[0]}</StatusBadge> : "—"}
      </p>
      {s.last_message ? <p className="muted">{s.last_message}</p> : null}
      {s.last_run_at ? <p className="muted"><span>Последний запуск</span>: {new Date(s.last_run_at).toLocaleString("ru-RU")}</p> : null}
      {s.next_run ? <p className="muted"><span>Следующая проверка</span>: {s.next_run}</p> : null}
      {s.failed_release ? <p className="muted">Выпуск {s.failed_release} не установился и ночью повторно не ставится; «Обновить сейчас» попробует снова.</p> : null}
      <label className="check"><input type="checkbox" checked={enabled} disabled={!ready} onChange={e => setEnabled(e.target.checked)}/> Обновлять автоматически каждую ночь</label>
      <label>Время проверки (МСК)<input type="time" value={time} disabled={!ready || !enabled} onChange={e => setTime(e.target.value)}/></label>
      <div className="toolbar">
        <button className="primary" disabled={!ready || busy} onClick={save}>Сохранить</button>
        <button disabled={!ready || busy || !!s.running || !!state?.pending_run} onClick={runNow}>Проверить и обновить сейчас</button>
      </div>
      {s.log_tail?.length ? <details><summary>Журнал последнего запуска</summary><pre>{s.log_tail.join("\n")}</pre></details> : null}
      <p className="muted">Перед установкой агент сверяет SHA-256, делает снимок и дамп базы; при ошибке выпуск откатывается автоматически. Итог приходит в Telegram администратору.</p>
    </div>
  );
}
