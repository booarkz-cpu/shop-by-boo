import React, {useEffect, useState} from "react";
import {Ban} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type NodeRow = {uuid: string; name: string; country: string | null; online: boolean; plugin: {uuid: string; name: string; ours: boolean} | null; ban: boolean; minutes: number | null; node_version: string | null; supported: boolean | null};
type Report = {at: string | null; node: string | null; user: string | null; ip: string | null; seconds: number | null};
type View = {nodes: NodeRow[]; enabled_nodes: number; ignore_ips: string[]; minutes: number; reports_supported: boolean; reports: Report[]; panel_supported: boolean; panel_error: string | null};

const API = "/api/admin/rw/torrent-ban";
const flag = (code: string | null) => (code && /^[A-Z]{2}$/.test(code) ? String.fromCodePoint(...[...code].map((c) => 127397 + c.charCodeAt(0))) : "🌐");

/** «Временный бан за торренты»: the node's own Torrent Blocker plugin switched on for the chosen nodes with one button. */
export function TorrentBan({request, toast}: {request: RequestFn; toast: (m: string) => void}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [minutes, setMinutes] = useState("60");
  const [ignore, setIgnore] = useState("");

  function show(next: View) {
    setView(next);
    setPicked(next.nodes.filter((n) => n.ban).map((n) => n.uuid));
    setMinutes(String(next.minutes || 60));
    setIgnore(next.ignore_ips.join("\n"));
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

  async function apply(enabled: boolean) {
    if (busy || picked.length === 0) return;
    if (enabled && !window.confirm(`Включить временный бан на ${minutes} мин. для выбранных нод (${picked.length})? Блокируется адрес целиком: все, кто выходит в интернет с этого адреса, на это время потеряют ноду.`)) return;
    setBusy(true);
    try {
      const body = {enabled, minutes: Number(minutes), node_uuids: picked, ignore_ips: ignore.split(/[\s,]+/).filter(Boolean)};
      const next = await request(API, {method: "PUT", body: JSON.stringify(body)});
      show(next);
      toast(enabled ? "Временный бан включён" : "Временный бан выключен");
    } catch (e: any) {
      toast(e.message || "Не удалось изменить");
    } finally {
      setBusy(false);
    }
  }

  const title = <h2><Ban aria-hidden="true" /> Временный бан за торренты</h2>;
  if (error) return <section className="card" data-torrent-ban aria-label="Временный бан за торренты">{title}<p role="status"><StatusBadge tone="warn">Нет связи с панелью</StatusBadge> {error}</p><button type="button" className="secondary" onClick={load}>Повторить</button></section>;
  if (!view) return <p className="muted card">Загрузка…</p>;
  const toggle = (uuid: string) => setPicked((p) => (p.includes(uuid) ? p.filter((u) => u !== uuid) : [...p, uuid]));
  const valid = Number(minutes) >= 1 && Number(minutes) <= 10080;

  return (
    <section className="card" data-torrent-ban aria-label="Временный бан за торренты">
      {title}
      <p className="muted">
        Нода сама блокирует адрес, с которого пришло соединение BitTorrent, на заданное время и сама снимает блокировку. Это делает плагин Torrent Blocker панели Remnawave (нода 2.7.0 и новее); ничего не перезапускается.
      </p>
      {!view.panel_supported && <p role="status"><StatusBadge tone="warn">Панель не поддерживает плагины нод</StatusBadge> Нужна панель Remnawave 2.7.0 или новее. {view.panel_error}</p>}
      <p data-ban-summary><StatusBadge tone={view.enabled_nodes ? "ok" : "idle"}>{view.enabled_nodes ? `Включён на ${view.enabled_nodes} из ${view.nodes.length} нод` : "Выключен"}</StatusBadge></p>
      <ul className="intel-warnings">
        <li><StatusBadge tone="warn">Общий адрес</StatusBadge> Блокируется адрес, а не клиент. За одним адресом мобильного оператора или одной сетью Wi-Fi могут быть другие ваши клиенты: на время блокировки они тоже потеряют эту ноду.</li>
        <li>Чтобы узнавать BitTorrent, в профиле ноды должно быть включено распознавание трафика (sniffing). Адреса из списка ниже не блокируются никогда.</li>
      </ul>
      <label>Срок блокировки, минут
        <input type="number" min={1} max={10080} value={minutes} onChange={(e) => setMinutes(e.target.value)} />
      </label>
      <label>Адреса, которые не блокировать (по одному в строке, без маски)
        <textarea rows={3} value={ignore} placeholder="203.0.113.9" onChange={(e) => setIgnore(e.target.value)} />
      </label>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Выбрать</th><th>Нода</th><th>Состояние</th><th>Бан</th><th>Плагин ноды</th></tr></thead>
          <tbody>
            {view.nodes.map((n) => (
              <tr key={n.uuid} data-node={n.name}>
                <td><input type="checkbox" aria-label={`Выбрать: ${n.name}`} checked={picked.includes(n.uuid)} onChange={() => toggle(n.uuid)} /></td>
                <td>{flag(n.country)} {n.name}{n.supported === false && <><br /><small className="muted">версия {n.node_version}: плагины не поддерживаются</small></>}{n.supported === null && <><br /><small className="muted">версия ноды неизвестна</small></>}</td>
                <td><StatusBadge tone={n.online ? "ok" : "danger"}>{n.online ? "на связи" : "не на связи"}</StatusBadge></td>
                <td>{n.ban ? `включён, ${n.minutes} мин.` : "выключен"}</td>
                <td>{n.plugin ? `${n.plugin.name}${n.plugin.ours ? "" : " (ваш: меняется только блок торрентов)"}` : "—"}</td>
              </tr>
            ))}
            {view.nodes.length === 0 && <tr><td colSpan={5} className="muted">В панели нет нод.</td></tr>}
          </tbody>
        </table>
      </div>
      <p>
        <button type="button" disabled={busy || picked.length === 0 || !valid || !view.panel_supported} onClick={() => apply(true)}>{busy ? "Выполняется…" : "Включить на выбранных"}</button>{" "}
        <button type="button" className="secondary" disabled={busy || picked.length === 0 || !view.panel_supported} onClick={() => apply(false)}>Выключить на выбранных</button>
      </p>
      <h3>Последние блокировки</h3>
      {!view.reports_supported ? <p className="muted">Панель не отдаёт журнал блокировок.</p> : view.reports.length === 0 ? <p className="muted">Блокировок пока не было.</p> : (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Когда</th><th>Нода</th><th>Клиент</th><th>Адрес</th><th>Срок</th></tr></thead>
            <tbody>
              {view.reports.map((r, i) => (
                <tr key={i}><td>{r.at ? new Date(r.at).toLocaleString("ru-RU") : "—"}</td><td>{r.node || "—"}</td><td>{r.user || "—"}</td><td>{r.ip || "—"}</td><td>{r.seconds ? `${Math.round(r.seconds / 60)} мин.` : "—"}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
