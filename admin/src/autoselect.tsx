import React, {useEffect, useState} from "react";
import {RefreshCw, Trash2, Zap} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Host = {uuid: string; name: string; address: string; country: string | null; in_pool: boolean; hidden: boolean; disabled: boolean; online: boolean | null; users_online: number | null; nodes: string[]};
type View = {
  enabled: boolean;
  name: string;
  algorithm: string;
  hide_nodes: boolean;
  applied_at: string | null;
  checked_at: string;
  algorithms: Record<string, string>;
  tile: {exists: boolean; name: string | null; visible: boolean; formats_excluded: string[]};
  stats: {hosts_total: number; in_subscription: number; pool_total: number; pool_served: number; pool_online: number; pool_offline: number; pool_unknown: number; excluded: number; missing: string[]};
  json_at_base: boolean | null;
  hosts: Host[];
};

const API = "/api/admin/rw/autoselect";
const when = (v: string) => new Date(v).toLocaleString("ru-RU", {dateStyle: "short", timeStyle: "medium"});
const flag = (code: string | null) => (code && /^[A-Z]{2}$/.test(code) ? String.fromCodePoint(...[...code].map((c) => 127397 + c.charCodeAt(0))) : "🌐");

/** «Пул автовыбора»: one tile in the customer's list that picks a node; every figure is the panel's own data. */
export function AutoSelect({request, toast}: {request: RequestFn; toast: (m: string) => void}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("⚡ Автовыбор");
  const [algorithm, setAlgorithm] = useState("leastPing");
  const [hide, setHide] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);

  function show(next: View) {
    setView(next);
    setName(next.name);
    setAlgorithm(next.algorithm || "leastPing");
    setHide(next.hide_nodes);
    setPicked(next.hosts.filter((h) => h.in_pool).map((h) => h.uuid));
  }
  async function load() {
    try {
      show(await request(API));
      setError("");
    } catch (e: any) {
      setError(e.message || "Панель Remnawave не отвечает");
    }
  }
  useEffect(() => {
    load();
  }, []);

  // One request at a time: a second click while the panel is being changed does nothing.
  async function run(action: () => Promise<View>, done: string) {
    if (busy) return;
    setBusy(true);
    try {
      show(await action());
      toast(done);
    } catch (e: any) {
      toast(e.message || "Не удалось выполнить");
      await load();
    } finally {
      setBusy(false);
    }
  }
  const save = () => run(() => request(API, {method: "PUT", body: JSON.stringify({name, algorithm, hide_nodes: hide, hosts: picked})}), view?.enabled ? "Пул обновлён" : "Плитка «Автовыбор» включена");
  const refresh = () => run(() => request(`${API}/refresh`, {method: "POST"}), "Пул обновлён по сохранённому выбору");
  const remove = () => {
    if (!window.confirm("Убрать плитку «Автовыбор»? Скрытые узлы вернутся в список клиентов, плитка и её шаблон будут удалены из панели.")) return;
    run(() => request(API, {method: "DELETE"}), "Плитка убрана, узлы возвращены в список");
  };

  if (error) return <section className="card" role="alert"><h2><Zap aria-hidden="true" /> Пул автовыбора</h2><p>{error}</p><button type="button" className="secondary" onClick={load}>Повторить</button></section>;
  if (!view) return <p className="muted card">Загрузка…</p>;
  const s = view.stats;
  const selectable = view.hosts.filter((h) => !h.disabled);
  const toggle = (uuid: string) => setPicked((p) => (p.includes(uuid) ? p.filter((u) => u !== uuid) : [...p, uuid]));

  return (
    <div className="network-intel autoselect" data-autoselect>
      <section className="card" aria-label="Пул автовыбора">
        <h2><Zap aria-hidden="true" /> Пул автовыбора — «быстрейшая нода клиенту»</h2>
        <p className="muted">
          В списке серверов клиента появляется одна плитка. Узел за ней выбирает приложение клиента по алгоритму, который вы задаёте здесь.
          Это отдельная плитка рядом с обычными узлами; чтобы клиент видел только её, включите «Скрыть узлы пула».
        </p>
        <ul className="intel-warnings">
          <li><StatusBadge tone={view.enabled && view.tile.visible ? "ok" : "idle"}>{view.enabled && view.tile.visible ? "Плитка включена" : "Плитки нет"}</StatusBadge> {view.applied_at ? `Применено ${when(view.applied_at)}.` : "Пул ещё не включали."} Данные панели на {when(view.checked_at)}.</li>
          <li data-stat="subscription"><strong>Видны в подписке: {s.in_subscription}/{s.hosts_total}</strong> — включённые хосты, которые клиент видит в списке.</li>
          <li data-stat="pool"><strong>В пуле: {s.pool_served}/{s.pool_total}</strong> — на связи {s.pool_online}, не на связи {s.pool_offline}{s.pool_unknown ? `, нет данных ${s.pool_unknown}` : ""}; вне пула {s.excluded}.</li>
          {s.missing.length > 0 && <li><StatusBadge tone="warn">Удалены в панели: {s.missing.length}</StatusBadge> Нажмите «Обновить пул», чтобы убрать их из пула.</li>}
          {view.json_at_base === false && <li><StatusBadge tone="warn">Формат Xray JSON не основной</StatusBadge> В настройках подписки панели выключено «JSON по основной ссылке»: плитку увидят только приложения, которые сами запрашивают Xray JSON.</li>}
        </ul>
      </section>

      <section className="card" aria-label="Настройки плитки">
        <h3>Плитка</h3>
        <label>Имя плитки
          <input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>Алгоритм
          <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
            {Object.entries(view.algorithms).map(([key, title]) => <option key={key} value={key}>{title} ({key})</option>)}
          </select>
        </label>
        <label className="checkbox"><input type="checkbox" checked={hide} onChange={(e) => setHide(e.target.checked)} /> Скрыть узлы пула из списка приложения</label>
        <p className="muted">
          {hide
            ? "Клиент увидит только плитку. Настоящий выбор узла есть лишь в формате Xray JSON. В Clash, Mihomo, sing-box и Base64 балансировщика нет: там плитка ведёт на первый узел пула."
            : "Клиент увидит плитку и обычные узлы. В Clash, Mihomo, sing-box и Base64 плитка не показывается: в этих форматах нет балансировщика, клиент выбирает узел сам."}
          {" "}После выключения скрытия узлы возвращаются, когда клиент обновит подписку.
        </p>
      </section>

      <section className="card" aria-label="Узлы пула">
        <h3>Узлы пула</h3>
        <p>
          <button type="button" className="secondary" onClick={() => setPicked(selectable.map((h) => h.uuid))}>Выбрать все</button>{" "}
          <button type="button" className="secondary" onClick={() => setPicked([])}>Снять все</button>
        </p>
        <div className="table-scroll">
          <table>
            <thead><tr><th>В пуле</th><th>Узел</th><th>Состояние</th><th>Клиентов</th><th>В списке клиента</th></tr></thead>
            <tbody>
              {view.hosts.map((h, i) => (
                <tr key={h.uuid} data-host={h.uuid}>
                  <td><input type="checkbox" aria-label={`В пуле: ${h.name}`} checked={picked.includes(h.uuid)} disabled={h.disabled} onChange={() => toggle(h.uuid)} /></td>
                  <td>{i + 1}. {flag(h.country)} {h.name}<br /><small className="muted">{h.address}{h.nodes.length ? ` · ${h.nodes.join(", ")}` : ""}</small></td>
                  <td>{h.disabled ? <StatusBadge tone="idle">выключен</StatusBadge> : h.online === null ? <StatusBadge tone="idle">нет данных</StatusBadge> : <StatusBadge tone={h.online ? "ok" : "danger"}>{h.online ? "на связи" : "не на связи"}</StatusBadge>}</td>
                  <td>{h.users_online ?? "—"}</td>
                  <td>{h.hidden ? "скрыт" : "виден"}{h.in_pool ? " · раздаётся" : ""}</td>
                </tr>
              ))}
              {view.hosts.length === 0 && <tr><td colSpan={5} className="muted">В панели нет хостов. Сначала добавьте узел и хост.</td></tr>}
            </tbody>
          </table>
        </div>
        <p>
          <button type="button" disabled={busy || picked.length === 0} onClick={save}>{busy ? "Выполняется…" : view.enabled ? "Сохранить и обновить пул" : `Включить ${algorithm}`}</button>{" "}
          {view.enabled && <button type="button" className="secondary" disabled={busy} onClick={refresh}><RefreshCw aria-hidden="true" /> Обновить пул</button>}{" "}
          {(view.enabled || view.tile.exists) && <button type="button" className="danger" disabled={busy} onClick={remove}><Trash2 aria-hidden="true" /> Убрать плитку</button>}
        </p>
        {picked.length === 1 && <p className="muted">В пуле один узел: выбирать будет не из чего. Добавьте хотя бы второй.</p>}
      </section>
    </div>
  );
}
