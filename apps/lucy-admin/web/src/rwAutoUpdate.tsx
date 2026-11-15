import React, {useEffect, useState} from "react";
import {StatusBadge, type Tone} from "./components/ui/status";
import {stepUp} from "./stepUp";

const API = process.env.NEXT_PUBLIC_API_URL || "";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Component = {repo: string; verified: string; latest: string | null; error: string | null; newer: boolean};
type Installation = {id: number; title: string; servers: {id: number; name: string; host: string | null}[]; components: string[];
  outdated: string[]; busy: boolean; last_update: Row | null};
type Row = {id: number; source_id: number | null; status: string; error: string | null; created_by: string; created_at: string | null;
  finished_at: string | null; automatic: boolean; rolled_back?: boolean};
type State = {settings: {enabled: boolean; time: string; installation_ids: number[]; notify: boolean; geo?: boolean}; next_run: string | null;
  verified: Record<string, string>; upstream: {checked_at: string | null; components: Record<string, Component>};
  panel: {status: string; version: string | null; verified: string} | null; installations: Installation[]; history: Row[];
  panel_copies?: {name: string; server_id: number; size: number; created_at: string}[]};

const TITLES: Record<string, string> = {panel: "Панель", node: "Нода", subscription_page: "Страница подписки", postgres: "PostgreSQL",
  valkey: "Valkey", caddy: "Caddy"};
const STATUS: Record<string, [string, Tone]> = {succeeded: ["Обновлено", "ok"], failed: ["Ошибка, откат", "danger"],
  cancelled: ["Отменено", "idle"], queued: ["В очереди", "info"], running: ["Идёт", "info"], planned: ["План", "idle"]};
const PANEL: Record<string, [string, Tone]> = {verified: ["проверена в CI", "ok"], newer: ["новее проверенной", "warn"],
  older: ["старше проверенной", "warn"], unknown: ["версия неизвестна", "warn"], unreachable: ["не отвечает", "danger"],
  not_connected: ["не подключена", "idle"]};
const when = (x: string | null) => (x ? new Date(x).toLocaleString("ru-RU") : "—");

/** «Обновления → Автообновление Remnawave»: панель, ноды и страница подписки, установленные мастером. */
export function RwAutoUpdate({request, toast}: {request: Request; toast?: (text: string) => void}) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({enabled: false, time: "04:30", installation_ids: [] as number[], notify: true, geo: false});
  const [picked, setPicked] = useState<number[]>([]);

  async function load(sync = false) {
    try {
      const next: State = await request("/api/admin/remnawave/auto-update");
      setState(next);
      setError("");
      if (sync) setForm({...next.settings, geo: !!next.settings.geo});
    } catch (e: any) {
      setError(e.message || "Состояние недоступно");
    }
  }

  useEffect(() => {
    load(true);
    const timer = setInterval(() => load(false), 20000);
    return () => clearInterval(timer);
  }, []);

  async function act(path: string, method: string, body: any, done: string) {
    setBusy(true);
    try {
      const next = await request(path, {method, body: body ? JSON.stringify(body) : undefined});
      setState(prev => ({...(prev as State), ...next}));
      toast?.(done);
    } catch (e: any) {
      setError(e.message || "Не выполнено");
    } finally {
      setBusy(false);
    }
  }

  async function download(name: string) {
    const url = `${API}/api/admin/remnawave/auto-update/panel-copies/${encodeURIComponent(name)}`;
    let r = await fetch(url, {credentials: "include"});
    if (r.status === 428 && await stepUp((p, o) => request(p, o))) r = await fetch(url, {credentials: "include"});
    if (!r.ok) { setError(r.status === 428 ? "Скачивание не подтверждено" : `Не скачано (HTTP ${r.status})`); return; }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await r.blob());
    link.download = name.replace(/\.enc$/, "");
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  }

  const scope = (id: number, list: number[]) => (list.includes(id) ? list.filter(x => x !== id) : [...list, id]);
  const comps = Object.entries(state?.upstream.components || {});
  const panel = state?.panel ? PANEL[state.panel.status] || [state.panel.status, "info" as Tone] : null;

  return (
    <div className="card">
      <h3>Автообновление Remnawave</h3>
      <p className="muted">Ставятся только версии, которые выпуск магазина закрепил по digest и проверил в CI на настоящей панели и ноде.
        Перед обновлением — копия базы панели, после — проверка HTTPS, связи нод и страницы подписки. При сбое возвращаются прежние файлы и база.</p>
      {error ? <p className="error" role="alert">{error}</p> : null}

      <h4>Версии</h4>
      <table className="table"><thead><tr><th>Компонент</th><th>Проверена магазином</th><th>Последняя на GitHub</th><th>Статус</th></tr></thead>
        <tbody>{comps.map(([key, c]) => <tr key={key}>
          <td>{TITLES[key] || key} <span className="muted">({c.repo})</span></td><td>{c.verified}</td><td>{c.latest || "—"}</td>
          <td>{c.error ? <StatusBadge tone="warn">{c.error}</StatusBadge>
            : c.newer ? <StatusBadge tone="warn">Новее: ждёт проверки в выпуске магазина</StatusBadge>
            : c.latest ? <StatusBadge tone="ok">Актуальна</StatusBadge> : "—"}</td></tr>)}</tbody></table>
      <p className="muted">Проверено: {when(state?.upstream.checked_at || null)}</p>
      {state?.panel ? <p><span>Подключённая панель</span>: <b>{state.panel.version || "—"}</b> {panel ? <StatusBadge tone={panel[1]}>{panel[0]}</StatusBadge> : null}</p> : null}
      <div className="toolbar"><button disabled={busy} onClick={() => act("/api/admin/remnawave/auto-update/check", "POST", null, "Релизы проверены")}>Проверить релизы сейчас</button></div>

      <h4>Установки</h4>
      {state && !state.installations.length ? <p className="muted">Мастер ещё ничего не установил: обновлять нечего.</p> : null}
      {state?.installations.length ? <table className="table"><thead><tr><th></th><th>Установка</th><th>Серверы</th><th>Требует обновления</th><th>Последнее обновление</th></tr></thead>
        <tbody>{state.installations.map(i => <tr key={i.id}>
          <td><input type="checkbox" aria-label={`Выбрать установку #${i.id}`} checked={picked.includes(i.id)} onChange={() => setPicked(scope(i.id, picked))}/></td>
          <td>#{i.id} {i.title}</td><td>{i.servers.map(s => s.name).join(", ")}</td>
          <td>{i.busy ? <StatusBadge tone="info">Идёт действие</StatusBadge>
            : i.outdated.length ? <StatusBadge tone="warn">{i.outdated.map(x => TITLES[x] || x).join(", ")}</StatusBadge>
            : <StatusBadge tone="ok">Актуальна</StatusBadge>}</td>
          <td>{i.last_update ? `${(STATUS[i.last_update.status] || [i.last_update.status])[0]} · ${when(i.last_update.finished_at || i.last_update.created_at)}` : "—"}</td></tr>)}</tbody></table> : null}
      <div className="toolbar">
        <button className="primary" disabled={busy || !picked.length}
          onClick={() => confirm("Обновить выбранные установки сейчас? Панель будет недоступна 1–3 минуты.")
            && act("/api/admin/remnawave/auto-update/run", "POST", {installation_ids: picked}, "Обновление поставлено в очередь")}>Обновить выбранные сейчас</button>
      </div>

      <h4>Расписание</h4>
      <label className="check"><input type="checkbox" checked={form.enabled} onChange={e => setForm({...form, enabled: e.target.checked})}/> Обновлять автоматически каждую ночь</label>
      <label>Время (МСК)<input type="time" value={form.time} disabled={!form.enabled} onChange={e => setForm({...form, time: e.target.value})}/></label>
      {state?.installations.length ? <fieldset><legend>Какие установки обновлять ночью (ничего не выбрано — все)</legend>
        {state.installations.map(i => <label className="check" key={i.id}><input type="checkbox" checked={form.installation_ids.includes(i.id)}
          onChange={() => setForm({...form, installation_ids: scope(i.id, form.installation_ids)})}/> #{i.id} {i.title}: {i.servers.map(s => s.name).join(", ")}</label>)}
      </fieldset> : null}
      <label className="check" data-autoupdate-geo><input type="checkbox" checked={!!form.geo} onChange={e => setForm({...form, geo: e.target.checked})}/> В то же время обновлять российские списки блокировок (только там, где они установлены; нода перезапускается)</label>
      <label className="check"><input type="checkbox" checked={form.notify} onChange={e => setForm({...form, notify: e.target.checked})}/> Сообщать в Telegram о новых релизах и итогах обновления</label>
      {state?.next_run ? <p className="muted"><span>Следующий запуск</span>: {when(state.next_run)}</p> : null}
      <div className="toolbar"><button className="primary" disabled={busy} onClick={() => act("/api/admin/remnawave/auto-update", "PUT", form, "Расписание сохранено")}>Сохранить</button></div>

      <h4>Копии базы панели в магазине</h4>
      {state?.panel_copies?.length ? <table className="table"><thead><tr><th>Файл</th><th>Сервер</th><th>Размер</th><th>Создана</th><th></th></tr></thead>
        <tbody>{state.panel_copies.map(c => <tr key={c.name}><td>{c.name}</td><td>#{c.server_id}</td><td>{(c.size / 1048576).toFixed(1)} МБ</td>
          <td>{when(c.created_at)}</td><td><button onClick={() => download(c.name)}>Скачать</button></td></tr>)}</tbody></table>
        : <p className="muted">Копий пока нет: они появляются при обновлении, переустановке или удалении панели.</p>}
      <p className="muted">Файлы хранятся зашифрованными ключом магазина; скачивается расшифрованный дамп (pg_dump -Fc) после подтверждения.</p>

      <h4>История обновлений</h4>
      {state?.history.length ? <table className="table"><thead><tr><th>№</th><th>Установка</th><th>Кто</th><th>Итог</th><th>Завершено</th></tr></thead>
        <tbody>{state.history.map(r => {
          const [label, tone] = STATUS[r.status] || [r.status, "info" as Tone];
          return <tr key={r.id}><td>{r.id}</td><td>#{r.source_id}</td><td>{r.automatic ? "ночное автообновление" : r.created_by}</td>
            <td><StatusBadge tone={tone}>{label}</StatusBadge>{r.rolled_back ? " изменения откатаны" : ""}{r.error ? <div className="muted">{r.error}</div> : null}</td>
            <td>{when(r.finished_at)}</td></tr>;
        })}</tbody></table> : <p className="muted">Обновлений ещё не было. Журнал шагов каждого обновления — в «Установке Remnawave».</p>}
    </div>
  );
}
