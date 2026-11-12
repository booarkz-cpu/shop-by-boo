import React, {useEffect, useState} from "react";
import {Waypoints} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Plan = {id: number; name: string; enabled: boolean; traffic_limit_gb: number | null};
type Node = {server_id: number; name: string; address: string; domain: string | null; ready: boolean; installed: boolean; port: number | null; users: number | null; synced_at: string | null; error: string | null};
type View = {enabled: boolean; plan_ids: number[]; port: number; plans: Plan[]; nodes: Node[]; users: number; images: {xray: string; haproxy: string}; notes: string[]};
type UserRow = {subscription_id: number; user_id: number; plan_id: number; login: string; expires_at: string; url: string};
type Traffic = {subscription_id: number | null; user_id: number | null; login: string; uplink: number; downlink: number};
type Status = {users: number; port: number; certificate_until: string; traffic: Traffic[]};

const API = "/api/admin/masque/panel";
const JSON_HEADERS = {"Content-Type": "application/json"};
const mb = (bytes: number) => (bytes / 1048576).toFixed(bytes < 10485760 ? 2 : 0) + " МБ";
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ru-RU") : "—");

/** «Смена протокола» → «MASQUE: ноды и подписка»: the shop's own panel for a protocol Remnawave does not know. */
export function MasquePanel({request, toast}: {request: RequestFn; toast: (m: string) => void}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [plans, setPlans] = useState<number[]>([]);
  const [port, setPort] = useState("2087");
  const [users, setUsers] = useState<{total: number; items: UserRow[]} | null>(null);
  const [status, setStatus] = useState<{node: string; data: Status} | null>(null);
  const [confirm, setConfirm] = useState<Node | null>(null);

  function show(next: View) {
    setView(next);
    setEnabled(next.enabled);
    setPlans(next.plan_ids);
    setPort(String(next.port));
    setError("");
  }
  async function act(key: string, work: () => Promise<void>) {
    if (busy) return;
    setBusy(key);
    try {
      await work();
    } catch (e: any) {
      toast(e.message || "Не получилось");
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    request(API).then(show).catch((e: any) => setError(e.message || "Состояние недоступно"));
  }, []);

  const portOk = /^\d{4,5}$/.test(port) && Number(port) >= 1024 && Number(port) <= 65535;
  const dirty = !!view && (enabled !== view.enabled || port !== String(view.port) || plans.join() !== view.plan_ids.join());
  const installed = view ? view.nodes.filter((n) => n.installed).length : 0;
  const save = () => act("save", async () => {
    show(await request(`${API}/settings`, {method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({enabled, plan_ids: plans, port: Number(port)})}));
    toast("Настройки MASQUE сохранены");
  });
  const install = (n: Node) => act(`install-${n.server_id}`, async () => {
    show(await request(`${API}/nodes/${n.server_id}/install`, {method: "POST"}));
    toast(`MASQUE установлен на ${n.name}`);
  });
  const remove = (n: Node) => act(`remove-${n.server_id}`, async () => {
    setConfirm(null);
    show(await request(`${API}/nodes/${n.server_id}/remove`, {method: "POST"}));
    setStatus(null);
    toast(`MASQUE удалён с ${n.name}`);
  });
  const check = (n: Node) => act(`status-${n.server_id}`, async () => {
    setStatus({node: n.name, data: await request(`${API}/nodes/${n.server_id}/status`, {method: "POST"})});
  });
  const sync = () => act("sync", async () => {
    show(await request(`${API}/sync`, {method: "POST"}));
    toast("Список пользователей отправлен на ноды");
  });
  const loadUsers = () => act("users", async () => setUsers(await request(`${API}/users?limit=50`)));
  const copy = (url: string) => navigator.clipboard?.writeText(url).then(() => toast("Ссылка скопирована"), () => toast("Не удалось скопировать"));

  return (
    <section className="card" data-masque-panel aria-label="MASQUE: ноды и подписка">
      <h2><Waypoints aria-hidden="true" /> MASQUE: ноды и подписка</h2>
      <p className="muted">Панель Remnawave не знает MASQUE, поэтому его ведёт магазин: ставит на ноду за сайтом SelfSteal, выдаёт доступ по подпискам и отдаёт свою ссылку подписки.</p>
      {error && <p role="status"><StatusBadge tone="warn">Нет данных</StatusBadge> {error}</p>}
      {!view && !error && <p className="muted">Загрузка…</p>}
      {view && <>
        <p data-masque-panel-summary role="status">
          <StatusBadge tone={view.enabled ? "ok" : "idle"}>{view.enabled ? "Доступ выдаётся" : "Доступ не выдаётся"}</StatusBadge>{" "}
          <StatusBadge tone={installed ? "ok" : "idle"}>Нод с MASQUE: {installed}</StatusBadge>{" "}
          <StatusBadge tone="idle">Подписок с доступом: {view.users}</StatusBadge>
        </p>
        <ul>{view.notes.map((n) => <li key={n}>{n}</li>)}</ul>

        <h3>Кому выдавать</h3>
        <form onSubmit={(e) => { e.preventDefault(); if (portOk && dirty) save(); }}>
          <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Выдавать MASQUE по действующим подпискам</label>
          <fieldset>
            <legend>Тарифы (ни один не выбран — все)</legend>
            {view.plans.length === 0 && <p className="muted">Тарифов нет.</p>}
            {view.plans.map((p) => (
              <label className="check" key={p.id}>
                <input type="checkbox" checked={plans.includes(p.id)} onChange={(e) => setPlans(e.target.checked ? [...plans, p.id].sort((a, b) => a - b) : plans.filter((x) => x !== p.id))} />
                {" "}{p.name}{p.traffic_limit_gb ? ` — лимит ${p.traffic_limit_gb} ГБ (MASQUE в него не входит)` : ""}{p.enabled ? "" : " (выключен)"}
              </label>
            ))}
          </fieldset>
          <label>Порт для новых установок (TCP, от 1024)
            <input inputMode="numeric" value={port} onChange={(e) => setPort(e.target.value)} aria-invalid={!portOk} />
          </label>
          {!portOk && <p role="alert">Порт — число от 1024 до 65535.</p>}
          <button type="submit" disabled={!portOk || !dirty || !!busy}>{busy === "save" ? "Сохраняю…" : "Сохранить"}</button>
        </form>

        <h3>Ноды</h3>
        {view.nodes.length === 0 ? <p className="muted">Нод, установленных магазином, нет. MASQUE ставится на ноду с сайтом SelfSteal.</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Нода</th><th>Домен сайта</th><th>Состояние</th><th>Пользователей</th><th>Сверено</th><th>Действия</th></tr></thead>
              <tbody>
                {view.nodes.map((n) => (
                  <tr key={n.server_id} data-masque-panel-node={n.name}>
                    <td>{n.name}</td>
                    <td>{n.domain || "—"}</td>
                    <td>
                      {n.installed ? <StatusBadge tone={n.error ? "warn" : "ok"}>{n.error ? "ошибка сверки" : `работает, порт ${n.port}`}</StatusBadge>
                        : n.ready ? <StatusBadge tone="idle">не установлен</StatusBadge> : <StatusBadge tone="warn">нет сайта SelfSteal</StatusBadge>}
                      {n.error && <div className="muted">{n.error}</div>}
                    </td>
                    <td>{n.installed ? n.users ?? "—" : "—"}</td>
                    <td>{n.installed ? when(n.synced_at) : "—"}</td>
                    <td>
                      {!n.installed && <button type="button" className="secondary" disabled={!n.ready || !!busy} onClick={() => install(n)}>{busy === `install-${n.server_id}` ? "Устанавливаю…" : "Установить"}</button>}
                      {n.installed && <>
                        <button type="button" className="secondary" disabled={!!busy} onClick={() => check(n)}>{busy === `status-${n.server_id}` ? "Проверяю…" : "Проверить"}</button>{" "}
                        <button type="button" className="secondary" disabled={!!busy} onClick={() => setConfirm(n)}>{busy === `remove-${n.server_id}` ? "Удаляю…" : "Удалить"}</button>
                      </>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {confirm && (
          <div role="alertdialog" aria-label="Удалить MASQUE с ноды" className="card" data-masque-panel-confirm>
            <p>Удалить MASQUE с ноды «{confirm.name}»? Туннели её пользователей оборвутся, порт закроется. Сайт SelfSteal и остальные протоколы не меняются.</p>
            <button type="button" onClick={() => remove(confirm)}>Удалить</button>{" "}
            <button type="button" className="secondary" onClick={() => setConfirm(null)}>Отмена</button>
          </div>
        )}
        {installed > 0 && <p><button type="button" className="secondary" disabled={!!busy} onClick={sync}>{busy === "sync" ? "Отправляю…" : "Сверить пользователей сейчас"}</button> <span className="muted">Само сверяется раз в минуту, когда список изменился.</span></p>}
        {status && (
          <div data-masque-panel-status>
            <h3>Нода «{status.node}» сейчас</h3>
            <p>Пользователей в Xray: {status.data.users}. Порт: {status.data.port}. Сертификат до: {status.data.certificate_until || "—"}.</p>
            {status.data.traffic.length === 0 ? <p className="muted">Трафика с запуска Xray не было.</p> : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Подписка</th><th>Покупатель</th><th>Отдано</th><th>Получено</th></tr></thead>
                  <tbody>{status.data.traffic.map((t) => <tr key={t.login}><td>{t.subscription_id ?? `нет в списке (${t.login})`}</td><td>{t.user_id ?? "—"}</td><td>{mb(t.uplink)}</td><td>{mb(t.downlink)}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </div>
        )}

        <h3>Подписки с доступом</h3>
        <p><button type="button" className="secondary" disabled={!!busy} onClick={loadUsers}>{busy === "users" ? "Загружаю…" : users ? "Обновить список" : "Показать список и ссылки"}</button> <span className="muted">Ссылка подписки — секрет покупателя.</span></p>
        {users && (users.items.length === 0 ? <p className="muted">Подписок с доступом нет.</p> : (
          <div className="table-scroll" data-masque-panel-users>
            <table>
              <thead><tr><th>Подписка</th><th>Покупатель</th><th>Логин</th><th>Действует до</th><th>Ссылка</th></tr></thead>
              <tbody>
                {users.items.map((u) => <tr key={u.subscription_id}><td>{u.subscription_id}</td><td>{u.user_id}</td><td><code>{u.login}</code></td><td>{when(u.expires_at)}</td>
                  <td><button type="button" className="secondary" onClick={() => copy(u.url)} aria-label={`Скопировать ссылку подписки ${u.subscription_id}`}>Скопировать</button></td></tr>)}
              </tbody>
            </table>
            {users.total > users.items.length && <p className="muted">Показаны первые {users.items.length} из {users.total}.</p>}
          </div>
        ))}
        <p className="muted">Образы: {view.images.xray}, {view.images.haproxy}.</p>
      </>}
    </section>
  );
}
