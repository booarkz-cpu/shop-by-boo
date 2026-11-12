import React, {useEffect, useState} from "react";
import {ShieldCheck} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Broken = {from: number; to: number; sealed: number; found: number; sealed_at: string};
type View = {sealed_records: number; seals: number; sealed_upto: number | null; last_seal_at: string | null; unsealed_records: number; verified_at: string | null; broken: Broken[]; intact: boolean; every_minutes: number};

const when = (value: string | null) => (value ? new Date(value).toLocaleString("ru-RU") : "ещё не было");

/** «Журнал действий → Целостность журнала»: a changed or deleted record breaks the seal of its range. */
export function AuditSeal({request}: {request: RequestFn}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load(verify: boolean) {
    setBusy(verify);
    try {
      setView(await request(verify ? "/api/admin/audit-seal/verify" : "/api/admin/audit-seal", verify ? {method: "POST"} : undefined));
      setError("");
    } catch (e: any) {
      setError(e.message || "Состояние недоступно");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load(false);
  }, []);

  const title = <h2><ShieldCheck aria-hidden="true" /> Целостность журнала</h2>;
  if (error) return <section className="card" data-audit-seal aria-label="Целостность журнала">{title}<p role="status"><StatusBadge tone="warn">Нет данных</StatusBadge> {error}</p></section>;
  if (!view) return <p className="muted card">Загрузка…</p>;
  return (
    <section className="card" data-audit-seal aria-label="Целостность журнала">
      {title}
      <p className="muted">Каждые {view.every_minutes} минут новые записи журнала запечатываются: по ним считается контрольная подпись с секретом сервера. Если запись потом изменить или удалить в базе, проверка это покажет.</p>
      <p data-seal-summary role="status">
        {!view.seals ? <StatusBadge tone="idle">Печатей ещё нет</StatusBadge>
          : !view.verified_at ? <StatusBadge tone="idle">Ещё не проверялось</StatusBadge>
          : view.intact ? <StatusBadge tone="ok">Журнал цел</StatusBadge>
          : <StatusBadge tone="danger">Нарушено диапазонов: {view.broken.length}</StatusBadge>}
      </p>
      <div className="table-scroll">
        <table>
          <tbody>
            <tr><th scope="row">Запечатано записей</th><td data-seal-count>{view.sealed_records}{view.sealed_upto ? ` (по № ${view.sealed_upto})` : ""}</td></tr>
            <tr><th scope="row">Ещё не запечатано</th><td data-seal-pending>{view.unsealed_records}</td></tr>
            <tr><th scope="row">Последняя печать</th><td>{when(view.last_seal_at)}</td></tr>
            <tr><th scope="row">Последняя проверка</th><td>{when(view.verified_at)}</td></tr>
          </tbody>
        </table>
      </div>
      {view.broken.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Записи №</th><th>Было запечатано</th><th>Найдено сейчас</th><th>Запечатано</th></tr></thead>
            <tbody>
              {view.broken.map((b) => (
                <tr key={`${b.from}-${b.to}`} data-seal-broken={`${b.from}-${b.to}`}>
                  <td>{b.from}–{b.to}</td><td>{b.sealed}</td><td>{b.found}</td><td>{when(b.sealed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {view.broken.length > 0 && <p className="muted">В этих диапазонах записи изменены или удалены после запечатывания. Сравните их с резервной копией базы.</p>}
      <p className="muted">Записи, сделанные после последней печати, ещё не защищены. Тот, у кого есть секрет сервера, может поставить печати заново.</p>
      <button type="button" className="secondary" disabled={busy || !view.seals} onClick={() => load(true)}>{busy ? "Проверяю…" : "Проверить журнал"}</button>
    </section>
  );
}
