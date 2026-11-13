import React, {useEffect, useState} from "react";
import {Network} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Row = {proto: "tcp" | "udp"; port: number; why: string; scope: "all" | "panel"; firewall: "open" | "closed" | "panel_only";
  listening: boolean; process: string; opened_by_shop: boolean; ssh: boolean; required: boolean; reachable: boolean | null};
type View = {server_id: number; name: string; host: string; firewalls: string[]; ports: Row[]; missing: string[]; checked_outside: boolean; notes: string[]};
type Server = {id: number; name: string; host: string};

const API = "/api/admin/rw/ports";
const JSON_HEADERS = {"Content-Type": "application/json"};
const WALLS: Record<string, string> = {ufw: "ufw", firewalld: "firewalld", iptables: "iptables", nftables: "nftables", none: "не включён"};

/** «Установка» → «Порты сервера» (owner's task of 2026-11-13): what is open, what the shop's installations need, open or close a port. */
export function ServerPorts({request, toast}: {request: RequestFn; toast: (m: string) => void}) {
  const [servers, setServers] = useState<Server[]>([]);
  const [server, setServer] = useState("");
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [port, setPort] = useState("");
  const [proto, setProto] = useState<"tcp" | "udp">("tcp");
  const [closing, setClosing] = useState<Row | null>(null);

  useEffect(() => {
    request("/api/admin/rw/servers").then((x: any) => { setServers(x.servers || []); if (x.servers?.[0]) setServer(String(x.servers[0].id)); }).catch(() => setServers([]));
  }, []);

  async function act(key: string, work: () => Promise<View>, done?: string) {
    if (busy) return;
    setBusy(key);
    try {
      setView(await work());
      setError("");
      if (done) toast(done);
    } catch (e: any) {
      setError(e.message || "Сервер не ответил");
    } finally {
      setBusy("");
    }
  }
  const load = (outside = false) => act(outside ? "outside" : "load", () => request(`${API}/${server}${outside ? "?outside=true" : ""}`));
  const send = (action: "open" | "close", rows: {port: number; proto: string}[], done: string) =>
    act(`${action}-${rows.map((r) => r.port).join(",")}`, () => request(`${API}/${server}/${action}`, {method: "POST", headers: JSON_HEADERS, body: JSON.stringify(rows)}), done);
  const portOk = /^\d{1,5}$/.test(port) && Number(port) >= 1 && Number(port) <= 65535;

  return (
    <section className="card" data-server-ports aria-label="Порты сервера">
      <h2><Network aria-hidden="true" /> Порты сервера</h2>
      <p className="muted">Магазин открывает нужные порты сам при установке. Здесь видно, что открыто в брандмауэре сервера, и можно открыть или закрыть порт вручную.</p>
      {servers.length === 0 ? <p className="muted">Серверов нет: добавьте сервер в мастере установки.</p> : (
        <p>
          <label>Сервер{" "}
            <select value={server} onChange={(e) => { setServer(e.target.value); setView(null); }}>
              {servers.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}
            </select>
          </label>{" "}
          <button type="button" className="secondary" disabled={!server || !!busy} onClick={() => load(false)}>{busy === "load" ? "Смотрю…" : "Проверить порты"}</button>{" "}
          <button type="button" className="secondary" disabled={!server || !!busy} onClick={() => load(true)}>{busy === "outside" ? "Проверяю снаружи…" : "Проверить снаружи"}</button>
        </p>
      )}
      {error && <p role="alert"><StatusBadge tone="warn">Ошибка</StatusBadge> {error}</p>}
      {view && <>
        <p data-server-ports-summary role="status">
          <StatusBadge tone="idle">Брандмауэр: {view.firewalls.map((f) => WALLS[f] || f).join(", ")}</StatusBadge>{" "}
          {view.missing.length ? <StatusBadge tone="warn">Закрыты нужные: {view.missing.join(", ")}</StatusBadge> : <StatusBadge tone="ok">Нужные порты открыты</StatusBadge>}
        </p>
        {view.missing.length > 0 && (
          <p><button type="button" disabled={!!busy} onClick={() => act("required", () => request(`${API}/${server}/open-required`, {method: "POST"}), "Нужные порты открыты")}>
            {busy === "required" ? "Открываю…" : "Открыть все нужные"}</button></p>
        )}
        <div className="table-scroll">
          <table>
            <thead><tr><th>Порт</th><th>Зачем</th><th>Брандмауэр</th><th>Слушает</th>{view.checked_outside && <th>Снаружи</th>}<th>Действие</th></tr></thead>
            <tbody>
              {view.ports.map((r) => (
                <tr key={`${r.proto}/${r.port}`} data-server-port={`${r.proto}/${r.port}`}>
                  <td>{r.port}/{r.proto}</td>
                  <td>{r.why || "—"}{r.ssh ? " (SSH)" : ""}</td>
                  <td>{r.firewall === "panel_only" ? <StatusBadge tone="ok">только для панели</StatusBadge>
                    : r.firewall === "open" ? <StatusBadge tone="ok">открыт</StatusBadge> : <StatusBadge tone={r.required ? "warn" : "idle"}>закрыт</StatusBadge>}</td>
                  <td>{r.listening ? r.process || "да" : "нет"}</td>
                  {view.checked_outside && <td>{r.reachable === true ? "доходит" : r.reachable === false ? "не доходит" : r.proto === "udp" ? "UDP не проверить" : "—"}</td>}
                  <td>
                    {r.firewall === "closed" && <button type="button" className="secondary" disabled={!!busy} onClick={() => send("open", [r], `Порт ${r.port}/${r.proto} открыт`)}>Открыть</button>}
                    {r.firewall === "open" && !r.ssh && r.opened_by_shop && <button type="button" className="secondary" disabled={!!busy} onClick={() => setClosing(r)}>Закрыть</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {closing && (
          <div role="alertdialog" aria-label="Закрыть порт" className="card" data-server-ports-confirm>
            <p>Закрыть порт {closing.port}/{closing.proto} на «{view.name}»?{closing.required ? " Он нужен установке магазина: клиенты потеряют этот способ подключения." : ""}</p>
            <button type="button" onClick={() => { const r = closing; setClosing(null); send("close", [r], `Порт ${r.port}/${r.proto} закрыт`); }}>Закрыть</button>{" "}
            <button type="button" className="secondary" onClick={() => setClosing(null)}>Отмена</button>
          </div>
        )}
        <form onSubmit={(e) => { e.preventDefault(); if (portOk) send("open", [{port: Number(port), proto}], `Порт ${port}/${proto} открыт`); }}>
          <label>Открыть другой порт
            <input inputMode="numeric" value={port} onChange={(e) => setPort(e.target.value)} aria-invalid={port !== "" && !portOk} />
          </label>{" "}
          <label>Протокол{" "}
            <select value={proto} onChange={(e) => setProto(e.target.value as "tcp" | "udp")}><option value="tcp">TCP</option><option value="udp">UDP</option></select>
          </label>{" "}
          <button type="submit" className="secondary" disabled={!portOk || !!busy}>Открыть</button>
          {port !== "" && !portOk && <p role="alert">Порт — число от 1 до 65535.</p>}
        </form>
        <ul className="muted">{view.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </>}
    </section>
  );
}
