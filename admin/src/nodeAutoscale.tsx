import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

/** «Серверы → Автомасштабирование»: добавить ноду, когда тесно, убрать добавленную, когда пусто. */
export function NodeAutoscale({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/nodes/autoscale").then((d: any) => { setData(d); setCfg({...d.config, inbound_text: (d.config.inbound_uuids || []).join(", ")}); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  const num = (key: string) => (e: any) => setCfg({...cfg, [key]: e.target.value});
  async function save() {
    setError("");
    try {
      const body: any = {...cfg, inbound_uuids: String(cfg.inbound_text || "").split(/[\s,]+/).filter(Boolean)};
      delete body.inbound_text;
      for (const k of ["up_at", "down_at", "min_nodes", "max_nodes", "sustain_minutes", "cooldown_minutes", "node_port"]) body[k] = Number(body[k]);
      await request("/api/admin/nodes/autoscale", {method: "PUT", body: JSON.stringify(body)});
      toast("Автомасштабирование сохранено"); load();
    } catch (e: any) { setError(e.message); }
  }
  if (!data || !cfg) return <div className="card"><h3>Автомасштабирование нод</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  const last = data.last;
  const ready = data.provider || {};
  return (
    <div className="card">
      <h3>Автомасштабирование нод</h3>
      <p className="muted">Нагрузка — пользователей онлайн на одну работающую ноду. Дольше заданного времени выше порога — нужна ещё нода, ниже — лишняя.
        В режиме «Рекомендации» приходит сообщение в Telegram. В режиме «Авто» магазин сам создаёт сервер в Hetzner Cloud с Remnawave Node и добавляет его в панель,
        а убирает только ноды, которые создал сам.</p>
      {error ? <p className="error">{error}</p> : null}
      {last ? <p>Сейчас: {last.online} нод онлайн, {last.users} пользователей, {last.load} на ноду{last.action ? ` — ${last.action === "up" ? "нужна ещё нода" : "одна нода лишняя"}` : ""}{last.reason ? ` (${last.reason})` : ""}.</p> : <p className="muted">Ещё не считалось.</p>}
      {cfg.mode === "auto" && !ready.hetzner_token ? <p className="error">Для режима «Авто» добавьте в .env HETZNER_API_TOKEN — пока будут только рекомендации. Ключ ноды магазин берёт из панели сам.</p> : null}
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={e => setCfg({...cfg, enabled: e.target.checked})}/> Включено</label>
      <label>Режим<select value={cfg.mode} onChange={e => setCfg({...cfg, mode: e.target.value})}><option value="recommend">Рекомендации</option><option value="auto">Авто (Hetzner)</option></select></label>
      <label>Добавлять ноду выше, польз./ноду<input type="number" value={cfg.up_at} onChange={num("up_at")}/></label>
      <label>Убирать ноду ниже, польз./ноду<input type="number" value={cfg.down_at} onChange={num("down_at")}/></label>
      <label>Нод минимум<input type="number" value={cfg.min_nodes} onChange={num("min_nodes")}/></label>
      <label>Нод максимум<input type="number" value={cfg.max_nodes} onChange={num("max_nodes")}/></label>
      <label>Держится, мин<input type="number" value={cfg.sustain_minutes} onChange={num("sustain_minutes")}/></label>
      <label>Пауза между изменениями, мин<input type="number" value={cfg.cooldown_minutes} onChange={num("cooldown_minutes")}/></label>
      <h4>Новая нода (режим «Авто»)</h4>
      <label>Тип сервера Hetzner<input value={cfg.server_type} onChange={num("server_type")}/></label>
      <label>Локация<input value={cfg.location} onChange={num("location")}/></label>
      <label>Образ<input value={cfg.image} onChange={num("image")}/></label>
      <label>SSH-ключ в Hetzner (имя)<input value={cfg.ssh_key} onChange={num("ssh_key")}/></label>
      <label>Код страны<input value={cfg.country_code} onChange={num("country_code")}/></label>
      <label>Порт ноды<input type="number" value={cfg.node_port} onChange={num("node_port")}/></label>
      <label>UUID профиля конфигурации<input value={cfg.config_profile_uuid} onChange={num("config_profile_uuid")}/></label>
      <label>UUID инбаундов (через запятую)<input value={cfg.inbound_text} onChange={num("inbound_text")}/></label>
      <label>Префикс имени<input value={cfg.name_prefix} onChange={num("name_prefix")}/></label>
      <div className="toolbar"><button className="primary" onClick={save}>Сохранить</button></div>
      {data.created?.length ? <><h4>Созданы автоматически</h4><ul>{data.created.map((c: any) => <li key={c.server_id}>{c.name} — {c.ip}, {String(c.created_at).slice(0, 16).replace("T", " ")} UTC</li>)}</ul></> : null}
      {data.history?.length ? <><h4>История</h4><ul>{data.history.map((h: any, i: number) => <li key={i}>{String(h.at).slice(0, 16).replace("T", " ")} — {h.action === "up" ? "добавление" : "удаление"}{h.ok ? "" : " (ошибка)"}: {h.reason}</li>)}</ul></> : null}
    </div>
  );
}
