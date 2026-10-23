import React, {useEffect, useState} from "react";
import {Copy, Magnet} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type View = {
  enabled: boolean;
  notify: boolean;
  days: number;
  retention_days: number;
  total: number;
  clients: {client: string; user_id: number | null; user: string | null; events: number; last_hour: string; nodes: number}[];
  nodes: {agent_id: number; node: string; events: number}[];
  days_series: {day: string; events: number}[];
};

const XRAY = `"routing": {"rules": [
  {"type": "field", "protocol": ["bittorrent"], "outboundTag": "TORRENT"}
]},
"outbounds": [ ..., {"protocol": "freedom", "tag": "TORRENT"} ],
"log": {"access": "/var/log/remnanode/access.log"}`;
const RULES = "Сервис не предназначен для торрентов (BitTorrent). Узлы автоматически замечают такой трафик по протоколу, не по содержимому: учитывается только число срабатываний, без адресов и файлов. При повторных нарушениях доступ может быть ограничен.";
const when = (v: string) => new Date(v + (v.endsWith("Z") ? "" : "Z")).toLocaleString("ru-RU", {dateStyle: "short", timeStyle: "short"});

/** BitTorrent detected by Xray on the nodes: counts only, abuse mark, customer notice. */
export function Torrents({data, request, toast}: {data: View; request: RequestFn; toast: (m: string) => void}) {
  const [view, setView] = useState<View>(data);
  useEffect(() => setView(data), [data]);
  if (!view?.clients) return <p className="muted card">Загрузка…</p>;
  const max = Math.max(1, ...view.days_series.map((d) => d.events));

  async function toggle() {
    try {
      const result = await request("/api/admin/platform/torrents/notify", {method: "POST", body: JSON.stringify({notify: !view.notify})});
      setView({...view, notify: result.notify});
      toast(result.notify ? "Уведомления клиентам включены" : "Уведомления клиентам выключены");
    } catch (e: any) {
      toast(e.message || "Не удалось изменить");
    }
  }
  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => toast("Скопировано")).catch(() => toast("Не удалось скопировать"));

  return (
    <div className="network-intel torrents">
      <section className="card" aria-label="Торренты на узлах">
        <h2>
          <Magnet aria-hidden="true" /> Торренты на узлах
        </h2>
        <p className="muted">
          Xray на узле распознаёт протокол BitTorrent и направляет такие соединения в отдельный выход. Агент узла читает журнал Xray и передаёт в магазин только число срабатываний по каждому клиенту — без адресов, портов и строк журнала. Срабатывание на 24 часа отмечает клиента в антиабузе; решения принимает оператор или настроенная политика.
        </p>
        <ul className="intel-warnings">
          <li>
            <StatusBadge tone={view.enabled ? "ok" : "idle"}>{view.enabled ? "Модуль включён" : "Модуль выключен"}</StatusBadge> Модуль «torrents» в разделе «Антиабуз и агенты».
          </li>
          <li>
            <StatusBadge tone={view.notify ? "ok" : "idle"}>{view.notify ? "Клиенты уведомляются" : "Без уведомлений"}</StatusBadge> Клиент получает одно уведомление в сутки, если у него замечен торрент.{" "}
            <button type="button" className="secondary" onClick={toggle}>
              {view.notify ? "Выключить уведомления" : "Включить уведомления"}
            </button>
          </li>
          <li className="muted">Счётчики хранятся {view.retention_days} дней и удаляются вместе с аккаунтом клиента.</li>
        </ul>
        <p className="muted">
          За {view.days} дней: <strong>{view.total.toLocaleString("ru-RU")}</strong> срабатываний, клиентов — {view.clients.length}.
        </p>
        {view.days_series.length > 0 && (
          <div className="torrent-bars" role="img" aria-label="Срабатывания по дням">
            {view.days_series.map((d) => (
              <div key={d.day} className="torrent-bar" title={`${d.day}: ${d.events}`}>
                <span style={{height: `${Math.max(4, (d.events / max) * 100)}%`}} />
                <small>{d.day.slice(5)}</small>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card" aria-label="Клиенты">
        <h3>Клиенты</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Клиент Xray</th>
                <th>Пользователь магазина</th>
                <th>Срабатываний</th>
                <th>Узлов</th>
                <th>Последний час</th>
              </tr>
            </thead>
            <tbody>
              {view.clients.map((c) => (
                <tr key={c.client}>
                  <td className="mono">{c.client}</td>
                  <td>{c.user ? `${c.user} (#${c.user_id})` : <span className="muted">не найден</span>}</td>
                  <td>{c.events.toLocaleString("ru-RU")}</td>
                  <td>{c.nodes}</td>
                  <td>{when(c.last_hour)}</td>
                </tr>
              ))}
              {view.clients.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    Срабатываний нет.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {view.nodes.length > 0 && <p className="muted">По узлам: {view.nodes.map((n) => `${n.node} — ${n.events.toLocaleString("ru-RU")}`).join(", ")}.</p>}
      </section>

      <section className="card" aria-label="Настройка">
        <h3>Настройка</h3>
        <p className="muted">
          1. В профиле конфигурации Xray (Remnawave) включите sniffing у входящих, добавьте правило для протокола bittorrent и выход с тегом TORRENT — freedom, чтобы только считать, или blackhole, чтобы ещё и блокировать. Access-журнал должен быть доступен агенту.
        </p>
        <pre className="term-transcript">{XRAY}</pre>
        <p className="muted">
          2. Запустите агент узла с <code>AGENT_XRAY_ACCESS_LOG=/var/log/remnanode/access.log</code> (и <code>AGENT_TORRENT_TAG</code>, если тег другой).
        </p>
        <p className="muted">3. Добавьте пункт в правила сервиса (раздел «Новости и страницы»). Пример:</p>
        <blockquote className="torrent-rules">{RULES}</blockquote>
        <button type="button" className="secondary" onClick={() => copy(RULES)}>
          <Copy aria-hidden="true" /> Скопировать текст
        </button>
      </section>
    </div>
  );
}
