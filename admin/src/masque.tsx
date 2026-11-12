import React, {useEffect, useState} from "react";
import {Waypoints} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Node = {uuid: string; name: string; xray: string | null; state: "ready" | "old" | "unknown"};
type Profile = {uuid: string; name: string; conflicts: string[]};
type Blocker = {key: string; title: string; text: string};
type View = {required: string; first_tag: string; port: number; http: string[]; nodes: Node[]; nodes_ready: number; profiles: Profile[]; blockers: Blocker[]; can_enable: boolean; example: object};

const STATE: Record<Node["state"], [string, "ok" | "warn" | "idle"]> = {ready: ["подходит", "ok"], old: ["старое ядро", "warn"], unknown: ["версия неизвестна", "idle"]};

/** «Смена протокола» → «MASQUE»: readiness of the nodes and the reasons the protocol is not switched on. Changes nothing. */
export function Masque({request}: {request: RequestFn}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [port, setPort] = useState("2087");
  const [busy, setBusy] = useState(false);
  async function load(value: string) {
    setBusy(true);
    try {
      setView(await request(`/api/admin/masque?port=${encodeURIComponent(value)}`));
      setError("");
    } catch (e: any) {
      setError(e.message || "Состояние недоступно");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load(port);
  }, []);

  const title = <h2><Waypoints aria-hidden="true" /> MASQUE (CONNECT-IP)</h2>;
  const valid = /^\d{1,5}$/.test(port) && Number(port) >= 1 && Number(port) <= 65535;
  return (
    <section className="card" data-masque aria-label="MASQUE">
      {title}
      <p className="muted">Туннель поверх HTTP/3 (UDP) и HTTP/2 (TCP) по RFC 9484. Здесь видно, готовы ли ноды и что мешает включить протокол. Проверка ничего не меняет.</p>
      {error && <p role="status"><StatusBadge tone="warn">Нет данных</StatusBadge> {error}</p>}
      {!view && !error && <p className="muted">Загрузка…</p>}
      {view && <>
        <p data-masque-summary role="status">
          <StatusBadge tone="warn">Не включается</StatusBadge>{" "}
          <StatusBadge tone={view.nodes.length > 0 && view.nodes_ready === view.nodes.length ? "ok" : "idle"}>Ноды с подходящим ядром: {view.nodes_ready} из {view.nodes.length}</StatusBadge>
        </p>
        <p>Нужно ядро Xray {view.required} или новее. MASQUE появился в {view.first_tag}; версии v26.10.10 не существует.</p>
        <h3>Что мешает включить</h3>
        <ul data-masque-blockers>
          {view.blockers.map((b) => <li key={b.key} data-masque-blocker={b.key}><strong>{b.title}.</strong> {b.text}</li>)}
        </ul>
        <h3>Ноды</h3>
        {view.nodes.length === 0 ? <p className="muted">На панели нет нод.</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Нода</th><th>Ядро Xray</th><th>Готовность</th></tr></thead>
              <tbody>
                {view.nodes.map((n) => <tr key={n.uuid} data-masque-node={n.name}><td>{n.name}</td><td>{n.xray || "—"}</td><td><StatusBadge tone={STATE[n.state][1]}>{STATE[n.state][0]}</StatusBadge></td></tr>)}
              </tbody>
            </table>
          </div>
        )}
        <h3>Порт</h3>
        <form onSubmit={(e) => { e.preventDefault(); if (valid) load(port); }}>
          <label>Порт MASQUE (UDP для HTTP/3 и TCP для HTTP/2)
            <input inputMode="numeric" value={port} onChange={(e) => setPort(e.target.value)} aria-invalid={!valid} />
          </label>
          {!valid && <p role="alert">Порт — число от 1 до 65535.</p>}
          <button type="submit" className="secondary" disabled={!valid || busy}>{busy ? "Проверяю…" : "Проверить порт"}</button>
        </form>
        {view.profiles.length === 0 ? <p className="muted">На панели нет профилей.</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Профиль</th><th>Порт {view.port}</th></tr></thead>
              <tbody>
                {view.profiles.map((p) => <tr key={p.uuid} data-masque-profile={p.name}><td>{p.name}</td><td>{p.conflicts.length === 0 ? <StatusBadge tone="ok">свободен</StatusBadge> : <><StatusBadge tone="warn">занят</StatusBadge> {p.conflicts.join("; ")}</>}</td></tr>)}
              </tbody>
            </table>
          </div>
        )}
        <details>
          <summary>Проверенный inbound для Xray</summary>
          <pre data-masque-example>{JSON.stringify(view.example, null, 2)}</pre>
        </details>
      </>}
    </section>
  );
}
