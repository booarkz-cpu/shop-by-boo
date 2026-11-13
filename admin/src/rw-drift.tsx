import React, {useEffect, useState} from "react";
import {GitCompare} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Item = {area: string; object: string; expected: string; actual: string; tab: string};
type View = {checked_at: string | null; ok_at: string | null; error: string | null; failed_at: string | null; items: Item[]; in_sync: boolean; watched: {autoselect: boolean; torrent_ban_nodes: number; masque_nodes?: number}};

const when = (value: string | null) => (value ? new Date(value).toLocaleString("ru-RU") : "ещё не было");
const PLACE: Record<string, string> = {autoselect: "Автовыбор", torrents: "Торренты на узлах", protocolSwitch: "MASQUE: ноды и подписка"};

/** «Сверка с панелью»: what the shop set on the Remnawave panel against what the panel has now. Changes nothing. */
export function RwDrift({request}: {request: RequestFn}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load(check: boolean) {
    setBusy(check);
    try {
      setView(await request(check ? "/api/admin/rw/drift/check" : "/api/admin/rw/drift/meta", check ? {method: "POST"} : undefined));
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

  const title = <h2><GitCompare aria-hidden="true" /> Сверка с панелью</h2>;
  if (error) return <section className="card" data-rw-drift aria-label="Сверка с панелью">{title}<p role="status"><StatusBadge tone="warn">Нет данных</StatusBadge> {error}</p></section>;
  if (!view) return <p className="muted card">Загрузка…</p>;
  const nothing = !view.watched.autoselect && !view.watched.torrent_ban_nodes && !view.watched.masque_nodes;
  return (
    <section className="card" data-rw-drift aria-label="Сверка с панелью">
      {title}
      <p className="muted">Магазин помнит, что он настроил на панели Remnawave (пул автовыбора и бан за торренты) и на нодах (MASQUE: работает ли стек, порт, число пользователей). Здесь видно, совпадает ли это с тем, что есть сейчас. Проверка ничего не меняет; раз в 6 часов она идёт сама, о новых расхождениях приходит сообщение.</p>
      <p data-drift-summary role="status">
        {nothing ? <StatusBadge tone="idle">Сверять нечего</StatusBadge>
          : view.error ? <StatusBadge tone="danger">Панель не ответила</StatusBadge>
          : !view.checked_at ? <StatusBadge tone="idle">Ещё не проверялось</StatusBadge>
          : view.in_sync ? <StatusBadge tone="ok">Совпадает</StatusBadge>
          : <StatusBadge tone="warn">Расхождений: {view.items.length}</StatusBadge>}
      </p>
      {nothing && <p className="muted">Автовыбор не включён, бан за торренты через магазин не настраивался, MASQUE не установлен ни на одну ноду.</p>}
      {view.error && <p className="muted">Ошибка {when(view.failed_at)}: {view.error}. Ниже — результат последней удавшейся проверки.</p>}
      {view.items.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Где</th><th>Что</th><th>Настроено магазином</th><th>Сейчас</th><th>Где исправить</th></tr></thead>
            <tbody>
              {view.items.map((item, index) => (
                <tr key={index} data-drift-item={item.object}>
                  <td>{item.area}</td><td>{item.object}</td><td>{item.expected}</td><td>{item.actual}</td>
                  <td><a href={`#${item.tab}`}>{PLACE[item.tab] || item.tab}</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted">
        Проверено: {when(view.checked_at)}. Без расхождений в последний раз: {when(view.ok_at)}.{" "}
        <button type="button" className="secondary" disabled={busy || nothing} onClick={() => load(true)}>{busy ? "Проверяю…" : "Проверить сейчас"}</button>
      </p>
    </section>
  );
}
