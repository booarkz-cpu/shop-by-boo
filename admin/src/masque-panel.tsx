import React, {useEffect, useState} from "react";
import {Waypoints} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Plan = {id: number; name: string; enabled: boolean; traffic_limit_gb: number | null};
type Shield = {strict_sni: boolean; tls_like_site: boolean; probe_ban: boolean; ban_after: number; ban_minutes: number};
type Node = {server_id: number; name: string; address: string; domain: string | null; ready: boolean; installed: boolean; port: number | null; users: number | null; synced_at: string | null; error: string | null; shield: Shield | null};
type Probe = {domain: string; port: number; same: boolean; checks: {check: string; same: boolean; differences: string[]}[]; limits: string[]};
type View = {enabled: boolean; plan_ids: number[]; port: number; count_in_limit: boolean; over_limit: number; plans: Plan[]; nodes: Node[]; users: number; images: {xray: string; haproxy: string}; notes: string[]; shield_default: Shield};
type UserRow = {subscription_id: number; user_id: number; plan_id: number; login: string; expires_at: string; url: string; traffic_bytes: number; over_limit: boolean; tunnels: number};
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
  const [counted, setCounted] = useState(true);
  const [users, setUsers] = useState<{total: number; items: UserRow[]} | null>(null);
  const [status, setStatus] = useState<{node: string; data: Status} | null>(null);
  const [confirm, setConfirm] = useState<Node | null>(null);
  const [reissueOf, setReissueOf] = useState<UserRow | null>(null);
  const [setup, setSetup] = useState<{node: Node; shield: Shield} | null>(null);
  const [probe, setProbe] = useState<{node: string; data: Probe} | null>(null);

  function show(next: View) {
    setView(next);
    setEnabled(next.enabled);
    setPlans(next.plan_ids);
    setPort(String(next.port));
    setCounted(next.count_in_limit);
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
  const dirty = !!view && (enabled !== view.enabled || port !== String(view.port) || plans.join() !== view.plan_ids.join() || counted !== view.count_in_limit);
  const installed = view ? view.nodes.filter((n) => n.installed).length : 0;
  const save = () => act("save", async () => {
    show(await request(`${API}/settings`, {method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({enabled, plan_ids: plans, port: Number(port), count_in_limit: counted})}));
    toast("Настройки MASQUE сохранены");
  });
  const shieldOk = !!setup && Number.isInteger(setup.shield.ban_after) && setup.shield.ban_after >= 5 && setup.shield.ban_after <= 500
    && Number.isInteger(setup.shield.ban_minutes) && setup.shield.ban_minutes >= 1 && setup.shield.ban_minutes <= 1440;
  const install = (n: Node, shield: Shield) => act(`install-${n.server_id}`, async () => {
    setSetup(null);
    show(await request(`${API}/nodes/${n.server_id}/install`, {method: "POST", headers: JSON_HEADERS, body: JSON.stringify({shield})}));
    toast(n.installed ? `Защиты на ${n.name} изменены` : `MASQUE установлен на ${n.name}`);
  });
  const runProbe = (n: Node) => act(`probe-${n.server_id}`, async () => {
    setProbe({node: n.name, data: await request(`${API}/nodes/${n.server_id}/probe`, {method: "POST"})});
  });
  const shieldText = (s: Shield | null) => !s ? "—" : [s.strict_sni && "строгий SNI", s.tls_like_site && "TLS как у сайта", s.probe_ban && `блокировка после ${s.ban_after} отказов на ${s.ban_minutes} мин.`].filter(Boolean).join(", ") || "только базовые";
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
  const reissue = (u: UserRow) => act(`reissue-${u.subscription_id}`, async () => {
    setReissueOf(null);
    const next = await request(`${API}/users/${u.subscription_id}/reissue`, {method: "POST"});
    setUsers((list) => list && {...list, items: list.items.map((i) => (i.subscription_id === u.subscription_id ? {...i, url: next.url, login: next.login} : i))});
    toast(`Подписке ${u.subscription_id} выдана новая ссылка`);
  });
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
          {view.count_in_limit && view.over_limit > 0 && <>{" "}<StatusBadge tone="warn">Исчерпали лимит тарифа: {view.over_limit}</StatusBadge></>}
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
          <label className="check"><input type="checkbox" checked={counted} onChange={(e) => setCounted(e.target.checked)} /> Засчитывать трафик MASQUE в лимит тарифа</label>
          <p className="muted">Включено: трафик MASQUE складывается с трафиком панели, и когда лимит тарифа исчерпан, доступ MASQUE снимается до нового периода. Выключено: MASQUE безлимитный.</p>
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
              <thead><tr><th>Нода</th><th>Домен сайта</th><th>Состояние</th><th>Защиты</th><th>Пользователей</th><th>Сверено</th><th>Действия</th></tr></thead>
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
                    <td>{n.installed ? shieldText(n.shield) : "—"}</td>
                    <td>{n.installed ? n.users ?? "—" : "—"}</td>
                    <td>{n.installed ? when(n.synced_at) : "—"}</td>
                    <td>
                      {!n.installed && <button type="button" className="secondary" disabled={!n.ready || !!busy} onClick={() => setSetup({node: n, shield: {...view.shield_default}})}>{busy === `install-${n.server_id}` ? "Устанавливаю…" : "Установить"}</button>}
                      {n.installed && <>
                        <button type="button" className="secondary" disabled={!!busy} onClick={() => check(n)}>{busy === `status-${n.server_id}` ? "Проверяю…" : "Проверить"}</button>{" "}
                        <button type="button" className="secondary" disabled={!!busy} onClick={() => runProbe(n)}>{busy === `probe-${n.server_id}` ? "Смотрю снаружи…" : "Проверить маскировку"}</button>{" "}
                        <button type="button" className="secondary" disabled={!!busy} onClick={() => setSetup({node: n, shield: {...(n.shield || view.shield_default)}})}>{busy === `install-${n.server_id}` ? "Меняю…" : "Изменить защиты"}</button>{" "}
                        <button type="button" className="secondary" disabled={!!busy} onClick={() => setConfirm(n)}>{busy === `remove-${n.server_id}` ? "Удаляю…" : "Удалить"}</button>
                      </>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {setup && (
          <form role="dialog" aria-label="Защиты от обнаружения" className="card" data-masque-panel-setup onSubmit={(e) => { e.preventDefault(); if (shieldOk) install(setup.node, setup.shield); }}>
            <h3>{setup.node.installed ? `Защиты на ноде «${setup.node.name}»` : `Установка MASQUE на «${setup.node.name}»`}</h3>
            <p className="muted">Всегда включено: на порту виден сайт SelfSteal; в туннель попадает только запрос на секретный путь; любой другой запрос, даже на этот путь, получает страницу сайта; служебные страницы прокси заменены.</p>
            <label className="check"><input type="checkbox" checked={setup.shield.strict_sni} onChange={(e) => setSetup({...setup, shield: {...setup.shield, strict_sni: e.target.checked}})} /> Строгий SNI — без имени домена сертификат не выдаётся, сканер по IP не узнает домен</label>
            <label className="check"><input type="checkbox" checked={setup.shield.tls_like_site} onChange={(e) => setSetup({...setup, shield: {...setup.shield, tls_like_site: e.target.checked}})} /> TLS как у сайта — версии, шифры и кривые те же, что у сайта на порту 443</label>
            <label className="check"><input type="checkbox" checked={setup.shield.probe_ban} onChange={(e) => setSetup({...setup, shield: {...setup.shield, probe_ban: e.target.checked}})} /> Блокировка зондирования — адрес, который подбирает пароли или пути, видит только сайт</label>
            {setup.shield.probe_ban && <>
              <label>Отказов до блокировки (5–500)
                <input inputMode="numeric" value={String(setup.shield.ban_after)} onChange={(e) => setSetup({...setup, shield: {...setup.shield, ban_after: Number(e.target.value.replace(/\D/g, "") || 0)}})} />
              </label>
              <label>Срок блокировки, минут (1–1440)
                <input inputMode="numeric" value={String(setup.shield.ban_minutes)} onChange={(e) => setSetup({...setup, shield: {...setup.shield, ban_minutes: Number(e.target.value.replace(/\D/g, "") || 0)}})} />
              </label>
              <p className="muted">Клиент сам повторяет попытку несколько раз, поэтому порог не делайте маленьким. У мобильных операторов один адрес бывает у многих абонентов: покупатель с истёкшей подпиской может на время закрыть MASQUE соседям по адресу.</p>
              {!shieldOk && <p role="alert">Порог — от 5 до 500, срок — от 1 до 1440 минут.</p>}
            </>}
            {setup.node.installed && <p>Контейнеры будут пересозданы: открытые туннели на этой ноде переподключатся.</p>}
            <button type="submit" disabled={!shieldOk || !!busy}>{setup.node.installed ? "Применить" : "Установить"}</button>{" "}
            <button type="button" className="secondary" onClick={() => setSetup(null)}>Отмена</button>
          </form>
        )}
        {probe && (
          <div data-masque-panel-probe>
            <h3>Маскировка ноды «{probe.node}» снаружи</h3>
            <p role="status"><StatusBadge tone={probe.data.same ? "ok" : "warn"}>{probe.data.same ? "Порт отвечает как сайт" : "Есть отличия от сайта"}</StatusBadge> Сравнение ответов порта {probe.data.port} и порта 443.</p>
            <ul>{probe.data.checks.map((c) => <li key={c.check}><strong>{c.check}:</strong> {c.same ? "одинаково" : c.differences.join("; ")}</li>)}</ul>
            <p className="muted">Чего маскировка не скрывает:</p>
            <ul className="muted">{probe.data.limits.map((l) => <li key={l}>{l}</li>)}</ul>
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
              <thead><tr><th>Подписка</th><th>Покупатель</th><th>Логин</th><th>Трафик MASQUE</th><th>Туннелей</th><th>Действует до</th><th>Ссылка</th></tr></thead>
              <tbody>
                {users.items.map((u) => <tr key={u.subscription_id}><td>{u.subscription_id}</td><td>{u.user_id}</td><td><code>{u.login}</code></td><td>{mb(u.traffic_bytes)}{u.over_limit && <> <StatusBadge tone="warn">лимит исчерпан</StatusBadge></>}</td><td>{u.tunnels || "без лимита"}</td><td>{when(u.expires_at)}</td>
                  <td><button type="button" className="secondary" onClick={() => copy(u.url)} aria-label={`Скопировать ссылку подписки ${u.subscription_id}`}>Скопировать</button>{" "}
                    <button type="button" className="secondary" disabled={!!busy} onClick={() => setReissueOf(u)} aria-label={`Выдать новую ссылку подписке ${u.subscription_id}`}>Новая ссылка</button></td></tr>)}
              </tbody>
            </table>
            {reissueOf && (
              <div role="alertdialog" aria-label="Выдать новую ссылку" className="card" data-masque-panel-reissue>
                <p>Выдать подписке {reissueOf.subscription_id} новую ссылку MASQUE? Старая ссылка и логин перестанут работать сразу, покупателю нужно будет добавить новую.</p>
                <button type="button" onClick={() => reissue(reissueOf)}>Выдать новую</button>{" "}
                <button type="button" className="secondary" onClick={() => setReissueOf(null)}>Отмена</button>
              </div>
            )}
            {users.total > users.items.length && <p className="muted">Показаны первые {users.items.length} из {users.total}.</p>}
          </div>
        ))}
        <p className="muted">Образы: {view.images.xray}, {view.images.haproxy}.</p>
      </>}
    </section>
  );
}
