import React, {useEffect, useState} from "react";
import {StatusBadge} from "./components/ui/status";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Config = {enabled: boolean; auto_restart: boolean; restart_after_minutes: number; restart_cooldown_minutes: number;
  alert_after_minutes: number; agent_silence_minutes: number; scheduled_restart: boolean; restart_time: string; auto_update: boolean; update_time: string};

/** «Ноды → Мониторинг»: автоперезапуск упавших нод, алерты в Telegram, плановый перезапуск и обновление нод. */
export function NodeMonitor({request, toast}: {request: Request; toast?: (text: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [error, setError] = useState("");

  async function load() {
    try {
      const next = await request("/api/admin/nodes/health");
      setData(next);
      setCfg(c => c || next.config);
      setError("");
    } catch (e: any) {
      setError(e.message || "Мониторинг недоступен");
    }
  }
  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, []);

  async function save() {
    try {
      setCfg(await request("/api/admin/nodes/health/config", {method: "PUT", body: JSON.stringify(cfg)}));
      toast?.("Настройки мониторинга сохранены");
    } catch (e: any) {
      setError(e.message || "Не сохранено");
    }
  }
  async function restart(uuid: string, name: string) {
    if (!confirm(`Перезапустить ноду «${name}»? Клиенты на ней переподключатся.`)) return;
    try {
      await request(`/api/admin/nodes/${uuid}/restart`, {method: "POST"});
      toast?.("Команда перезапуска отправлена в Remnawave");
      load();
    } catch (e: any) {
      setError(e.message || "Перезапуск не выполнен");
    }
  }
  async function updateAll() {
    if (!confirm("Обновить все ноды до последней версии remnawave/node? Агент на каждой ноде скачает образ и пересоздаст контейнер.")) return;
    try {
      const r = await request("/api/admin/nodes/update", {method: "POST"});
      toast?.(`Обновление поставлено в очередь для ${r.queued} нод`);
    } catch (e: any) {
      setError(e.message || "Не поставлено в очередь");
    }
  }
  const set = (patch: Partial<Config>) => setCfg(c => (c ? {...c, ...patch} : c));
  const num = (key: keyof Config, label: string) => (
    <label>{label}<input type="number" min={1} value={Number(cfg?.[key] ?? 0)} onChange={e => set({[key]: +e.target.value} as any)}/></label>
  );
  return (
    <div className="card">
      <div className="toolbar"><h3>Мониторинг и автовосстановление нод</h3><button onClick={updateAll}>Обновить все ноды</button></div>
      {error ? <p className="error">{error}</p> : null}
      {data?.error ? <div className="alert">{data.error}</div> : null}
      <div className="table-wrap"><table><thead><tr><th>Нода</th><th>Статус</th><th>Не в сети</th><th>Перезапусков</th><th>Xray</th><th></th></tr></thead>
        <tbody>{(data?.nodes || []).map((n: any) => (
          <tr key={n.uuid}>
            <td>{n.name}{n.country ? ` · ${n.country}` : ""}</td>
            <td><StatusBadge tone={n.status === "online" ? "ok" : n.status === "disabled" ? "idle" : "danger"}>{n.status === "online" ? "в сети" : n.status === "disabled" ? "выключена" : "не в сети"}</StatusBadge></td>
            <td>{n.down_minutes ? `${n.down_minutes} мин` : "—"}</td>
            <td>{n.restart_count || 0}</td>
            <td>{n.xray_version || "—"}</td>
            <td><button onClick={() => restart(n.uuid, n.name)}>Перезапустить</button></td>
          </tr>))}</tbody></table></div>
      {data?.agents?.length ? <p className="muted">Агенты нод: {data.agents.map((a: any) => `${a.name}${a.silent ? " (молчит)" : ""}`).join(", ")}</p> : null}
      {cfg ? <div className="grid2">
        <div>
          <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={e => set({enabled: e.target.checked})}/> Мониторинг включён</label>
          <label className="check"><input type="checkbox" checked={cfg.auto_restart} onChange={e => set({auto_restart: e.target.checked})}/> Перезапускать упавшую ноду автоматически</label>
          {num("restart_after_minutes", "Перезапуск после, мин")}
          {num("restart_cooldown_minutes", "Пауза между перезапусками, мин")}
          {num("alert_after_minutes", "Алерт в Telegram после, мин")}
          {num("agent_silence_minutes", "Агент молчит дольше, мин")}
        </div>
        <div>
          <label className="check"><input type="checkbox" checked={cfg.scheduled_restart} onChange={e => set({scheduled_restart: e.target.checked})}/> Плановый перезапуск всех нод</label>
          <label>Время (МСК)<input type="time" value={cfg.restart_time} onChange={e => set({restart_time: e.target.value})}/></label>
          <label className="check"><input type="checkbox" checked={cfg.auto_update} onChange={e => set({auto_update: e.target.checked})}/> Обновлять ноды каждую ночь</label>
          <label>Время (МСК)<input type="time" value={cfg.update_time} onChange={e => set({update_time: e.target.value})}/></label>
          <p className="muted">Обновление выполняет агент ноды (scripts/node-agent.py) при AGENT_ALLOW_NODE_UPDATE=1.</p>
        </div>
        <button className="primary" onClick={save}>Сохранить</button>
      </div> : null}
    </div>
  );
}
