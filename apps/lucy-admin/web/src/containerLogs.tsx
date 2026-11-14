import React, {useEffect, useRef, useState} from "react";
import {StatusBadge} from "./components/ui/status";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const TITLES: Record<string, string> = {backend: "API (backend)", worker: "Фоновый обработчик", bot: "Telegram-бот", caddy: "Caddy (прокси, TLS)",
  admin: "Админка", cabinet: "Кабинет", miniapp: "Mini App", db: "PostgreSQL", redis: "Redis", support_pro: "Поддержка",
  support_worker: "Поддержка: фон", mail_receiver: "Приём почты"};

/** «Мониторинг → Журналы контейнеров» (v28.75.0): хвост журнала службы. Читает агент на сервере раз в минуту,
 *  значения секретов из .env заменены на ***. */
export function ContainerLogs({request, toast}: {request: Request; toast?: (text: string) => void}) {
  const [service, setService] = useState("backend");
  const [lines, setLines] = useState(200);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const timer = useRef<any>(null);

  async function load(name = service) {
    try { setData(await request(`/api/admin/logs/${name}`)); setError(""); } catch (e: any) { setError(e.message || "Недоступно"); }
  }
  useEffect(() => { load(service); }, [service]);
  useEffect(() => {
    clearInterval(timer.current);
    if (data?.pending) timer.current = setInterval(() => load(), 5000);
    return () => clearInterval(timer.current);
  }, [data?.pending, service]);

  async function ask() {
    try {
      const out = await request("/api/admin/logs/request", {method: "POST", body: JSON.stringify({service, lines})});
      toast?.(out.agent_alive ? "Запрос передан: журнал появится в течение минуты" : "Запрос записан, но агент на сервере не отвечает");
      load();
    } catch (e: any) { setError(e.message || "Не запрошено"); }
  }
  const text: string = data?.text || "";
  const shown = filter ? text.split("\n").filter(l => l.toLowerCase().includes(filter.toLowerCase())).join("\n") : text;
  return <div className="card" data-container-logs>
    <h3>Журналы контейнеров</h3>
    <p className="muted">Хвост журнала службы с сервера. Его читает агент автообновления раз в минуту; пароли, токены и ключи из .env заменены на ***.</p>
    {error ? <p className="error" role="alert">{error}</p> : null}
    {data && !data.agent_alive ? <div className="alert">Агент на сервере не отвечает. {data.setup_hint}</div> : null}
    <div className="toolbar">
      <label>Служба<select value={service} onChange={e => setService(e.target.value)}>{(data?.services || Object.keys(TITLES)).map((s: string) =>
        <option key={s} value={s}>{TITLES[s] || s}</option>)}</select></label>
      <label>Строк<select value={lines} onChange={e => setLines(Number(e.target.value))}>{[100, 200, 500, 1000].map(n => <option key={n}>{n}</option>)}</select></label>
      <button className="primary" disabled={data?.pending} onClick={ask}>{data?.pending ? "Ждём агента…" : "Получить свежий журнал"}</button>
      <label>Фильтр<input value={filter} onChange={e => setFilter(e.target.value)} placeholder="error, 500, payment…"/></label>
    </div>
    <p className="muted">{data?.at ? <>Получено {new Date(data.at).toLocaleString("ru-RU")} · {data.lines} строк {data.code ? <StatusBadge tone="warn">docker compose завершился с кодом {data.code}</StatusBadge> : null}</> : "Журнал ещё не запрашивался"}</p>
    {text ? <pre className="log-view" tabIndex={0}>{shown || "Нет строк по фильтру"}</pre> : null}
  </div>;
}
