import React, {useEffect, useState} from "react";

/** v28.37: modules carried over from the comparison snapshots (docs/ru/SNAPSHOT_RECONCILIATION.md). */
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (text: string) => void};
const put = (body: any): RequestInit => ({method: "PUT", body: JSON.stringify(body)});
const post = (body?: any): RequestInit => ({method: "POST", body: JSON.stringify(body ?? {})});
const day = (v?: string | null) => (v ? String(v).slice(0, 16).replace("T", " ") : "—");

function useData(request: Request, path: string): [any, () => void, string, (e: string) => void] {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => { setError(""); request(path).then(setData).catch((e: any) => setError(e.message)); };
  useEffect(load, [request, path]);
  return [data, load, error, setError];
}

function Card({title, hint, error, children}: {title: string; hint?: string; error?: string; children: React.ReactNode}) {
  return <div className="card"><h3>{title}</h3>{hint ? <p className="muted">{hint}</p> : null}{error ? <p className="error">{error}</p> : null}{children}</div>;
}

async function act(fn: () => Promise<any>, toast: (t: string) => void, ok: string, setError: (e: string) => void, after?: () => void) {
  setError("");
  try { await fn(); toast(ok); after?.(); } catch (e: any) { setError(e.message); }
}

/** «Клиенты → Модерация». */
export function Moderation({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/moderation");
  const [ban, setBan] = useState("");
  const [lists, setLists] = useState<any>(null);
  const [invite, setInvite] = useState<any>({note: "", max_uses: 1, days: 30});
  const [created, setCreated] = useState<any>(null);
  if (!d) return <Card title="Модерация" error={error}><p>Загрузка…</p></Card>;
  const cfg = d.config;
  const black = lists ?? {telegram_ids: (d.blacklist_items.telegram_ids || []).join("\n"), emails: (d.blacklist_items.emails || []).join("\n"), domains: (d.blacklist_items.domains || []).join("\n")};
  const split = (t: string) => t.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
  return (
    <Card title="Модерация" error={error} hint="Кто может зарегистрироваться и кто остаётся: чёрный список, временные почтовые ящики, регистрация по приглашениям, массовая блокировка и клиенты, заблокировавшие бота.">
      <label className="check"><input type="checkbox" checked={cfg.block_disposable} onChange={(e) => act(() => request("/api/admin/moderation", put({...cfg, block_disposable: e.target.checked})), toast, "Сохранено", setError, load)}/> Не принимать временные почтовые ящики ({d.disposable_builtin} доменов в списке)</label>
      <label className="check"><input type="checkbox" checked={cfg.invite_only} onChange={(e) => act(() => request("/api/admin/moderation", put({...cfg, invite_only: e.target.checked})), toast, "Сохранено", setError, load)}/> Регистрация только по приглашениям</label>
      <h4>Приглашения</h4>
      <div className="toolbar">
        <input placeholder="Для кого" value={invite.note} onChange={(e) => setInvite({...invite, note: e.target.value})}/>
        <input type="number" min={0} title="Сколько раз (0 — без ограничения)" value={invite.max_uses} onChange={(e) => setInvite({...invite, max_uses: Number(e.target.value)})}/>
        <input type="number" min={0} title="Дней действует" value={invite.days} onChange={(e) => setInvite({...invite, days: Number(e.target.value)})}/>
        <button onClick={() => act(async () => setCreated(await request("/api/admin/moderation/invites", post(invite))), toast, "Приглашение создано", setError, load)}>Создать приглашение</button>
      </div>
      {created ? <div className="alert">Код <b>{created.code}</b><br/>Бот: {created.bot_link}<br/>Кабинет: {created.cabinet_link}</div> : null}
      {d.invites.length ? <table className="table"><tbody>{d.invites.map((i: any) => <tr key={i.id}><td>{i.note || i.id}</td><td>{i.uses}/{i.max_uses || "∞"}</td><td>{i.disabled ? "выключено" : day(i.expires_at)}</td>
        <td>{i.disabled ? null : <button onClick={() => act(() => request(`/api/admin/moderation/invites/${i.id}`, {method: "DELETE"}), toast, "Выключено", setError, load)}>Выключить</button>}</td></tr>)}</tbody></table> : null}
      <h4>Чёрный список</h4>
      <div className="grid3">
        <label>Telegram ID<textarea rows={4} value={black.telegram_ids} onChange={(e) => setLists({...black, telegram_ids: e.target.value})}/></label>
        <label>Email<textarea rows={4} value={black.emails} onChange={(e) => setLists({...black, emails: e.target.value})}/></label>
        <label>Домены почты<textarea rows={4} value={black.domains} onChange={(e) => setLists({...black, domains: e.target.value})}/></label>
      </div>
      <button onClick={() => act(() => request("/api/admin/moderation/blacklist", put({telegram_ids: split(black.telegram_ids).map(Number).filter(Boolean), emails: split(black.emails), domains: split(black.domains)})), toast, "Чёрный список сохранён", setError, () => { setLists(null); load(); })}>Сохранить список</button>
      <h4>Массовая блокировка</h4>
      <textarea rows={3} placeholder="Telegram ID — по одному в строке, через запятую или столбец CSV" value={ban} onChange={(e) => setBan(e.target.value)}/>
      <div className="toolbar">
        <button className="danger" disabled={!ban.trim()} onClick={() => act(async () => { const r = await request("/api/admin/moderation/ban", post({text: ban})); toast(`ID: ${r.ids}, заблокировано клиентов: ${r.customers}, в чёрный список: ${r.blacklisted}`); }, toast, "Готово", setError, load)}>Заблокировать</button>
        <button disabled={!ban.trim()} onClick={() => act(() => request("/api/admin/moderation/ban", post({text: ban, unban: true})), toast, "Разблокировано", setError, load)}>Разблокировать</button>
      </div>
      <h4>Заблокировали бота</h4>
      <p>{d.scan?.total ? `${d.scan.running ? "Идёт проверка" : "Проверено"}: ${d.scan.checked} из ${d.scan.total}, заблокировали бота: ${d.scan.blocked ?? 0}` : "Проверка не запускалась."} Можно закрыть неактивных (нет подписки, баланса и оплат за 90 дней): {d.cleanup_candidates}.</p>
      <div className="toolbar">
        <button onClick={() => act(() => request("/api/admin/moderation/blocked-scan", post()), toast, "Проверка запущена", setError, load)}>Проверить</button>
        <button className="danger" disabled={!d.cleanup_candidates} onClick={() => window.confirm(`Закрыть ${d.cleanup_candidates} аккаунтов? Это необратимо.`) && act(() => request("/api/admin/moderation/blocked-cleanup", post()), toast, "Аккаунты закрыты", setError, load)}>Закрыть неактивных</button>
      </div>
    </Card>
  );
}

/** Customer card timeline («Действия клиента»). */
export function ActivityLookup({request}: {request: Request}) {
  const [id, setId] = useState("");
  const [items, setItems] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  return (
    <Card title="Действия клиента" error={error} hint="Всё, что клиент делал в боте, кабинете, Mini App и приложениях, его оплаты, обращения, входы и действия администраторов — одной лентой.">
      <div className="toolbar"><input placeholder="ID клиента" value={id} onChange={(e) => setId(e.target.value.replace(/\D/g, ""))}/>
        <button disabled={!id} onClick={() => request(`/api/admin/users/${id}/activity`).then((r: any) => setItems(r.items)).catch((e: any) => setError(e.message))}>Показать</button></div>
      {items ? (items.length ? <table className="table"><tbody>{items.map((e, i) => <tr key={i}><td>{day(e.at)}</td><td>{e.surface}</td><td>{e.action}</td><td className="muted">{Object.entries(e.detail || {}).map(([k, v]) => `${k}: ${v}`).join(", ")}</td></tr>)}</tbody></table> : <p>Событий нет.</p>) : null}
    </Card>
  );
}

/** «Маркетинг → Обязательные каналы». */
export function ChannelGate({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/channels");
  const [rows, setRows] = useState<any[] | null>(null);
  if (!d) return <Card title="Обязательные каналы" error={error}><p>Загрузка…</p></Card>;
  const list = rows ?? d.channels;
  const set = (i: number, patch: any) => setRows(list.map((c: any, j: number) => (j === i ? {...c, ...patch} : c)));
  return (
    <Card title="Обязательные каналы" error={error} hint="Клиент должен быть подписан на каналы: везде (бот, кабинет, Mini App), перед пробным периодом или перед покупкой. Бот должен быть администратором канала.">
      {list.map((c: any, i: number) => (
        <div className="toolbar" key={i}>
          <input placeholder="@канал или -100…" value={c.chat} onChange={(e) => set(i, {chat: e.target.value})}/>
          <input placeholder="Название" value={c.title} onChange={(e) => set(i, {title: e.target.value})}/>
          <input placeholder="https://t.me/…" value={c.url} onChange={(e) => set(i, {url: e.target.value})}/>
          <select value={c.scope} onChange={(e) => set(i, {scope: e.target.value})}>{Object.entries(d.scopes).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select>
          <button onClick={() => setRows(list.filter((_: any, j: number) => j !== i))}>Убрать</button>
        </div>
      ))}
      <div className="toolbar">
        <button onClick={() => setRows([...list, {chat: "", title: "", url: "", scope: "buy"}])}>Добавить канал</button>
        <button className="primary" onClick={() => act(() => request("/api/admin/channels", put({channels: list})), toast, "Каналы сохранены", setError, () => { setRows(null); load(); })}>Сохранить</button>
      </div>
    </Card>
  );
}

/** «Запуск и оповещения»: техработы при падении панели. */
export function PanelGuard({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/panel-guard");
  if (!d) return <Card title="Защита при падении панели" error={error}><p>Загрузка…</p></Card>;
  const cfg = d.config;
  const save = (patch: any) => act(() => request("/api/admin/panel-guard", put({...cfg, ...patch})), toast, "Сохранено", setError, load);
  return (
    <Card title="Защита при падении панели" error={error} hint="Если Remnawave не отвечает несколько минут подряд, магазин сам включает техработы и снимает их, когда панель вернётся. Техработы, включённые вручную, защита не снимает.">
      {d.state.active ? <div className="alert">Сейчас техработы включены защитой с {day(d.state.since)}.</div> : null}
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => save({enabled: e.target.checked})}/> Включать техработы автоматически</label>
      <label>Неудачных проверок подряд (минут)<input type="number" min={1} max={60} defaultValue={cfg.fail_after} onBlur={(e) => save({fail_after: Number(e.target.value)})}/></label>
      <label>Удачных проверок для снятия<input type="number" min={1} max={60} defaultValue={cfg.recover_after} onBlur={(e) => save({recover_after: Number(e.target.value)})}/></label>
    </Card>
  );
}

/** «Мониторинг → Журнал ошибок». */
export function ErrorLog({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/errors");
  const [open, setOpen] = useState<number | null>(null);
  if (!d) return <Card title="Журнал ошибок" error={error}><p>Загрузка…</p></Card>;
  return (
    <Card title={`Журнал ошибок (${d.open})`} error={error} hint="Ошибки API, фоновых процессов и бота, сгруппированные по месту. Секреты в текстах скрыты. Хранятся 30 дней.">
      {d.items.length === 0 ? <p>Открытых ошибок нет.</p> : <table className="table"><thead><tr><th>Последний раз</th><th>Где</th><th>Сообщение</th><th>Раз</th><th></th></tr></thead>
        <tbody>{d.items.map((e: any) => <React.Fragment key={e.id}><tr onClick={() => setOpen(open === e.id ? null : e.id)}><td>{day(e.last_seen)}</td><td>{e.process} · {e.logger}</td><td>{e.message.slice(0, 160)}</td><td>{e.count}</td>
          <td><button onClick={(ev) => { ev.stopPropagation(); act(() => request(`/api/admin/errors/${e.id}/resolve`, post()), toast, "Отмечено", setError, load); }}>Решено</button></td></tr>
          {open === e.id && e.traceback ? <tr><td colSpan={5}><pre style={{whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto"}}>{e.traceback}</pre></td></tr> : null}</React.Fragment>)}</tbody></table>}
      {d.open ? <button onClick={() => act(() => request("/api/admin/errors/resolve-all", post()), toast, "Все отмечены", setError, load)}>Отметить все решёнными</button> : null}
    </Card>
  );
}

/** «Тарифы»: льготный доступ, сброс трафика, суточные тарифы. */
export function AccessPolicies({request, toast}: Props) {
  const [g, loadG, error, setError] = useData(request, "/api/admin/grace");
  const [daily, loadD] = useData(request, "/api/admin/daily-billing");
  if (!g || !daily) return <Card title="Льготный доступ и суточные тарифы" error={error}><p>Загрузка…</p></Card>;
  const cfg = g.config;
  const save = (patch: any) => act(() => request("/api/admin/grace", put({...cfg, ...patch})), toast, "Сохранено", setError, loadG);
  return (
    <Card title="Льготный доступ и суточные тарифы" error={error}>
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => save({enabled: e.target.checked})}/> Льготный доступ: после окончания подписки VPN работает ещё несколько часов, клиент получает сообщение со ссылкой на продление</label>
      <label>Часов<input type="number" min={1} max={168} defaultValue={cfg.hours} onBlur={(e) => save({hours: Number(e.target.value)})}/></label>
      <label>Не чаще чем раз в (дней)<input type="number" min={0} max={365} defaultValue={cfg.cooldown_days} onBlur={(e) => save({cooldown_days: Number(e.target.value)})}/></label>
      <p className="muted">Сейчас в льготном доступе: {g.in_grace}.</p>
      <label className="check"><input type="checkbox" checked={!!cfg.reset_traffic_on_payment} onChange={(e) => save({reset_traffic_on_payment: e.target.checked})}/> Сбрасывать израсходованный трафик при оплате продления</label>
      <h4>Суточные тарифы</h4>
      <label className="check"><input type="checkbox" checked={daily.enabled} onChange={(e) => act(() => request("/api/admin/daily-billing", put({enabled: e.target.checked})), toast, "Сохранено", setError, loadD)}/> Тарифы на 1 день продлеваются сами каждый день с баланса (у клиентов с включённым автопродлением)</label>
      <p className="muted">{daily.plans.length ? `Суточные тарифы: ${daily.plans.map((p: any) => `${p.name} — ${p.price} ₽`).join(", ")}` : "Создайте тариф со сроком 1 день в разделе «Тарифы»."}</p>
    </Card>
  );
}

/** «Маркетинг → Пачки подарочных кодов». */
export function GiftBatches({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/gift-batches");
  const [form, setForm] = useState<any>({plan_id: "", count: 50, tag: "", days: "", valid_days: 90});
  if (!d) return <Card title="Пачки подарочных кодов" error={error}><p>Загрузка…</p></Card>;
  return (
    <Card title="Пачки подарочных кодов" error={error} hint="Одноразовые подарочные коды на тариф для розыгрышей, партнёров и офлайн-продаж; CSV с готовыми ссылками на бота и кабинет. Активация — в один клик по ссылке.">
      <div className="toolbar">
        <input placeholder="ID тарифа" value={form.plan_id} onChange={(e) => setForm({...form, plan_id: e.target.value.replace(/\D/g, "")})}/>
        <input placeholder="Метка (FEST)" value={form.tag} onChange={(e) => setForm({...form, tag: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "")})}/>
        <input type="number" title="Сколько кодов" value={form.count} onChange={(e) => setForm({...form, count: Number(e.target.value)})}/>
        <input placeholder="Дней (как в тарифе)" value={form.days} onChange={(e) => setForm({...form, days: e.target.value.replace(/\D/g, "")})}/>
        <input type="number" title="Действуют дней" value={form.valid_days} onChange={(e) => setForm({...form, valid_days: Number(e.target.value)})}/>
        <button disabled={!form.plan_id || form.tag.length < 2} onClick={() => act(() => request("/api/admin/gift-batches", post({...form, plan_id: Number(form.plan_id), days: form.days ? Number(form.days) : null})), toast, "Коды созданы", setError, load)}>Создать</button>
      </div>
      <table className="table"><tbody>{d.batches.map((b: any) => <tr key={b.tag}><td>{b.tag}</td><td>тариф {b.plan_id}</td><td>использовано {b.used} из {b.count}</td><td>до {day(b.expires_at)}</td>
        <td><a href={`/api/admin/gift-batches/${b.tag}.csv`}>CSV</a> <button onClick={() => act(() => request(`/api/admin/gift-batches/${b.tag}`, {method: "DELETE"}), toast, "Неиспользованные выключены", setError, load)}>Выключить</button></td></tr>)}</tbody></table>
    </Card>
  );
}

/** «Маркетинг → Закреплённое сообщение». */
export function PinnedMessage({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/pinned-message");
  const [form, setForm] = useState({text: "", button_text: "", button_url: ""});
  if (!d) return <Card title="Закреплённое сообщение" error={error}><p>Загрузка…</p></Card>;
  const m = d.message || {};
  return (
    <Card title="Закреплённое сообщение" error={error} hint="Бот отправит сообщение всем клиентам и закрепит его в чате. Новые клиенты получат его при /start. Новое сообщение открепляет прежнее.">
      {m.active ? <div className="alert">Сейчас закреплено: {m.text.slice(0, 120)}… — доставлено {m.progress?.sent ?? 0}{m.progress?.total ? ` из ${m.progress.total}` : ""}{d.sending ? " (идёт рассылка)" : ""}
        <button onClick={() => act(() => request("/api/admin/pinned-message", {method: "DELETE"}), toast, "Откреплено", setError, load)}>Открепить</button></div> : null}
      <textarea rows={4} placeholder="Текст (HTML Telegram: <b>, <i>, <a href>)" value={form.text} onChange={(e) => setForm({...form, text: e.target.value})}/>
      <div className="toolbar"><input placeholder="Кнопка" value={form.button_text} onChange={(e) => setForm({...form, button_text: e.target.value})}/>
        <input placeholder="https://…" value={form.button_url} onChange={(e) => setForm({...form, button_url: e.target.value})}/>
        <button className="primary" disabled={!form.text.trim()} onClick={() => window.confirm("Отправить и закрепить у всех клиентов?") && act(() => request("/api/admin/pinned-message", post(form)), toast, "Рассылка запущена", setError, load)}>Закрепить у всех</button></div>
    </Card>
  );
}

/** «Рефералы → Конкурсы». */
export function ReferralContests({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/referral-contests");
  const [form, setForm] = useState<any>({title: "", starts_at: "", ends_at: "", metric: "paid", prizes: "1:30:0\n2:14:0\n3:7:0"});
  if (!d) return <Card title="Конкурсы рефералов" error={error}><p>Загрузка…</p></Card>;
  const prizes = () => form.prizes.split("\n").map((l: string) => l.split(":").map((x) => x.trim())).filter((p: string[]) => p[0]).map(([place, days, amount]: string[]) => ({place: Number(place), days: Number(days || 0), amount: amount || "0"}));
  return (
    <Card title="Конкурсы рефералов" error={error} hint="Кто приведёт больше друзей за период. Считаются друзья, которые оплатили (или просто пришли). Призы — дни подписки и деньги на баланс, выдаются один раз по окончании. Клиенты видят таблицу в боте (/contest), кабинете, Mini App и приложениях.">
      <div className="toolbar">
        <input placeholder="Название" value={form.title} onChange={(e) => setForm({...form, title: e.target.value})}/>
        <input type="datetime-local" value={form.starts_at} onChange={(e) => setForm({...form, starts_at: e.target.value})}/>
        <input type="datetime-local" value={form.ends_at} onChange={(e) => setForm({...form, ends_at: e.target.value})}/>
        <select value={form.metric} onChange={(e) => setForm({...form, metric: e.target.value})}><option value="paid">оплатившие друзья</option><option value="invited">пришедшие друзья</option></select>
      </div>
      <label>Призы: место:дней:рублей, по строке<textarea rows={3} value={form.prizes} onChange={(e) => setForm({...form, prizes: e.target.value})}/></label>
      <button className="primary" disabled={!form.title || !form.starts_at || !form.ends_at} onClick={() => act(() => request("/api/admin/referral-contests", post({title: form.title, starts_at: form.starts_at, ends_at: form.ends_at, metric: form.metric, prizes: prizes()})), toast, "Конкурс создан", setError, load)}>Создать конкурс</button>
      {d.contests.map((c: any) => <div key={c.id}><h4>{c.title} — {c.status === "active" ? `до ${day(c.ends_at)}` : c.status === "finished" ? "завершён" : "отменён"}</h4>
        <ol>{(c.top || []).map((r: any) => <li key={r.place}>{r.name} — {r.score}{r.days ? `, приз ${r.days} дн.` : ""}{r.amount && r.amount !== "0" ? `, ${r.amount} ₽` : ""}</li>)}</ol>
        {c.status === "active" ? <button onClick={() => act(() => request(`/api/admin/referral-contests/${c.id}`, {method: "DELETE"}), toast, "Отменён", setError, load)}>Отменить</button> : null}</div>)}
    </Card>
  );
}

/** «Аналитика → Рекламные конверсии». */
export function AdPostbacks({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/ads/postbacks");
  const [form, setForm] = useState<any>(null);
  if (!d) return <Card title="Рекламные конверсии" error={error}><p>Загрузка…</p></Card>;
  const f = form ?? {enabled: d.enabled, urls: d.urls || {}, metrika_counter: d.metrika_counter, metrika_secret: d.metrika_secret, metrika_goals: d.metrika_goals || {}};
  return (
    <Card title="Рекламные конверсии" error={error} hint="Постбэки в рекламные сети и трекеры и офлайн-конверсии Яндекс Метрики: регистрация, пробный период, покупка. Клик приходит из ссылки: бот ?start=…__cid_<id>, кабинет ?click_id=<id>; идентификатор Метрики кабинет передаёт сам. Подстановки: {click_id} {user_id} {event} {amount} {currency} {order_id}.">
      <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => setForm({...f, enabled: e.target.checked})}/> Отправлять конверсии</label>
      {d.events.map((ev: string) => <label key={ev}>Постбэк «{ev}»<input value={f.urls[ev] || ""} placeholder="https://tracker…?click={click_id}" onChange={(e) => setForm({...f, urls: {...f.urls, [ev]: e.target.value}})}/></label>)}
      <div className="toolbar"><input placeholder="Номер счётчика Метрики" value={f.metrika_counter} onChange={(e) => setForm({...f, metrika_counter: e.target.value.replace(/\D/g, "")})}/>
        <input placeholder="Measurement secret" value={f.metrika_secret} onChange={(e) => setForm({...f, metrika_secret: e.target.value})}/></div>
      <button className="primary" onClick={() => act(() => request("/api/admin/ads/postbacks", put(f)), toast, "Сохранено", setError, () => { setForm(null); load(); })}>Сохранить</button>
      {d.log.length ? <p className="muted">Последние отправки: {d.log.map((l: any) => `${l.label} → ${l.status}`).join("; ")}</p> : null}
    </Card>
  );
}

/** «Поддержка → Автоответы». */
export function SupportAutoreply({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/support/autoreply");
  if (!d) return <Card title="Автоответы" error={error}><p>Загрузка…</p></Card>;
  const save = (patch: any) => act(() => request("/api/admin/support/autoreply", put({enabled: d.enabled, min_score: d.min_score, use_llm: d.use_llm, ...patch})), toast, "Сохранено", setError, load);
  return (
    <Card title="Автоответы поддержки" error={error} hint="Новое обращение, на которое явно отвечает база знаний, получает ответ сразу (с пометкой «Автоответ»). Обращение остаётся открытым для оператора. Вопросы о возвратах, списаниях и удалении аккаунта всегда ждут человека.">
      <label className="check"><input type="checkbox" checked={d.enabled} onChange={(e) => save({enabled: e.target.checked})}/> Отвечать автоматически</label>
      <label>Совпадающих слов не меньше<input type="number" min={1} max={10} defaultValue={d.min_score} onBlur={(e) => save({min_score: Number(e.target.value)})}/></label>
      <label className="check"><input type="checkbox" checked={d.use_llm} disabled={!d.llm_configured} onChange={(e) => save({use_llm: e.target.checked})}/> Отвечать моделью ИИ {d.llm_configured ? "" : "(модель не настроена)"}</label>
      <p className="muted">Вопросов в базе знаний: {d.faq_items}. Отправлено автоответов: {d.sent || 0}.</p>
    </Card>
  );
}

/** «Серверы → Качество связи». */
export function ConnectionQuality({request}: {request: Request}) {
  const [d, , error] = useData(request, "/api/admin/connection-quality");
  if (!d) return <Card title="Качество связи" error={error}><p>Загрузка…</p></Card>;
  return (
    <Card title="Качество связи по операторам" error={error} hint={`Приложения проверяют серверы при запуске и раз в 6 часов и сообщают результат по оператору связи (без адресов и трафика). За ${d.window_days} дней. Красным — пары, где сервер почти не открывается: похоже на блокировку у оператора.`}>
      {d.cells.length === 0 ? <p>Отчётов пока нет.</p> : <table className="table"><thead><tr><th>Оператор / сеть</th><th>Сервер</th><th>Попыток</th><th>Успешно</th><th>Медиана</th></tr></thead>
        <tbody>{d.cells.map((c: any, i: number) => <tr key={i} className={c.flagged ? "error" : ""}><td>{c.carrier}</td><td>{c.server}</td><td>{c.attempts}</td><td>{Math.round(c.success * 100)} %</td><td>{c.median_ms ?? "—"} мс</td></tr>)}</tbody></table>}
    </Card>
  );
}

/** «Аналитика → Риск оттока». */
export function Churn({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/churn");
  if (!d) return <Card title="Риск оттока" error={error}><p>Загрузка…</p></Card>;
  const cfg = d.config;
  const save = (patch: any) => act(() => request("/api/admin/churn", put({...cfg, ...patch})), toast, "Сохранено", setError, load);
  return (
    <Card title="Риск оттока" error={error} hint="Платящие клиенты, которые скорее всего уйдут, и почему. Персональная скидка — одноразовый промокод на 7 дней, не чаще раза в 30 дней.">
      <div className="toolbar"><label>Порог риска<input type="number" min={10} max={100} defaultValue={cfg.threshold} onBlur={(e) => save({threshold: Number(e.target.value)})}/></label>
        <label>Скидка, %<input type="number" min={1} max={90} defaultValue={cfg.percent} onBlur={(e) => save({percent: Number(e.target.value)})}/></label>
        <label className="check"><input type="checkbox" checked={cfg.auto} onChange={(e) => save({auto: e.target.checked})}/> Отправлять автоматически раз в день</label></div>
      <p className="muted">Оценено клиентов: {d.scored}; под угрозой: {d.at_risk.length}.</p>
      <table className="table"><tbody>{d.at_risk.map((r: any) => <tr key={r.user_id}><td>№{r.user_id} {r.name}</td><td><b>{r.score}</b></td><td className="muted">{r.reasons.join("; ")}</td>
        <td><button onClick={() => act(async () => { const o = await request(`/api/admin/churn/${r.user_id}/offer`, post()); toast(`Отправлен промокод ${o.code}`); }, toast, "Готово", setError, load)}>Скидка</button></td></tr>)}</tbody></table>
    </Card>
  );
}

/** «Аналитика → Прибыль и расходы». */
export function Pnl({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/pnl?months=6");
  const [costs, loadCosts] = useData(request, "/api/admin/pnl/costs");
  const [form, setForm] = useState<any>({month: new Date().toISOString().slice(0, 7), category: "servers", vendor: "", node: "", amount: "", note: ""});
  const [fees, setFees] = useState<any>(null);
  if (!d || !costs) return <Card title="Прибыль и расходы" error={error}><p>Загрузка…</p></Card>;
  const f = fees ?? d.fees;
  return (
    <Card title="Прибыль и расходы (P&L)" error={error} hint="Выручка за вычетом возвратов, комиссий касс, расходов на серверы, домены и софт и рекламы (из юнит-экономики).">
      <table className="table"><thead><tr><th>Месяц</th><th>Выручка</th><th>Возвраты</th><th>Комиссии</th><th>Расходы</th><th>Реклама</th><th>Прибыль</th><th>Маржа</th></tr></thead>
        <tbody>{d.months.map((m: any) => <tr key={m.month}><td>{m.month}</td><td>{m.revenue}</td><td>{m.refunds}</td><td>{m.fees}</td><td>{Object.values(m.costs).reduce((a: number, b: any) => a + Number(b), 0)}</td><td>{m.ads}</td><td><b>{m.profit}</b></td><td>{m.margin ?? "—"} %</td></tr>)}</tbody></table>
      <p>Активных клиентов: {d.active_customers}; прибыль на клиента за месяц: {d.profit_per_customer ?? "—"} ₽.</p>
      {d.nodes.length ? <p className="muted">Ноды (текущий месяц): {d.nodes.map((n: any) => `${n.node} — ${n.cost} ₽ (${n.per_customer ?? "—"} ₽ на клиента)`).join("; ")}</p> : null}
      <h4>Комиссии касс, %</h4>
      <div className="toolbar">{["yookassa", "platega", "rollypay", "cryptobot", "freekassa", "stars"].map((p) => <label key={p}>{p}<input type="number" step="0.1" min={0} max={30} value={f[p] ?? ""} onChange={(e) => setFees({...f, [p]: e.target.value})}/></label>)}
        <button onClick={() => act(() => request("/api/admin/pnl/fees", put(Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])))), toast, "Комиссии сохранены", setError, () => { setFees(null); load(); })}>Сохранить</button></div>
      <h4>Расходы</h4>
      <div className="toolbar">
        <input type="month" value={form.month} onChange={(e) => setForm({...form, month: e.target.value})}/>
        <select value={form.category} onChange={(e) => setForm({...form, category: e.target.value})}>{costs.categories.map((c: string) => <option key={c} value={c}>{({servers: "серверы", domains: "домены", software: "софт", staff: "люди", other: "другое"} as any)[c]}</option>)}</select>
        <input placeholder="Поставщик" value={form.vendor} onChange={(e) => setForm({...form, vendor: e.target.value})}/>
        <input placeholder="Нода (для серверов)" value={form.node} onChange={(e) => setForm({...form, node: e.target.value})}/>
        <input placeholder="Сумма" value={form.amount} onChange={(e) => setForm({...form, amount: e.target.value})}/>
        <button disabled={!form.amount} onClick={() => act(() => request("/api/admin/pnl/costs", post(form)), toast, "Расход добавлен", setError, () => { load(); loadCosts(); })}>Добавить</button>
      </div>
      <table className="table"><tbody>{costs.costs.map((c: any) => <tr key={c.id}><td>{c.month}</td><td>{c.category}</td><td>{c.vendor}</td><td>{c.node}</td><td>{c.amount}</td>
        <td><button onClick={() => act(() => request(`/api/admin/pnl/costs/${c.id}`, {method: "DELETE"}), toast, "Удалено", setError, () => { load(); loadCosts(); })}>Удалить</button></td></tr>)}</tbody></table>
    </Card>
  );
}

/** «Аналитика → Расход трафика». */
export function TrafficUsage({request}: {request: Request}) {
  const [d, , error] = useData(request, "/api/admin/analytics/traffic");
  if (!d) return <Card title="Расход трафика" error={error}><p>{error ? null : "Загрузка…"}</p></Card>;
  return (
    <Card title="Расход трафика" error={error} hint="Из Remnawave, обновляется раз в 10 минут.">
      <p>Пользователей панели: {d.users}; всего {d.total_gb} ГБ, в среднем {d.average_gb} ГБ; у предела (90 %+): {d.near_limit}.</p>
      <table className="table"><thead><tr><th>Клиент</th><th>Пользователь панели</th><th>ГБ</th><th>Лимит</th><th>Статус</th></tr></thead>
        <tbody>{d.top.map((u: any, i: number) => <tr key={i}><td>{u.customer_id ? `№${u.customer_id}` : "—"}</td><td>{u.panel_user}</td><td>{u.used_gb}</td><td>{u.limit_gb ?? "∞"}</td><td>{u.status}</td></tr>)}</tbody></table>
    </Card>
  );
}

/** «Серверы → Панель Remnawave». */
export function PanelAdmin({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/panel/overview");
  if (!d) return <Card title="Панель Remnawave" error={error}><p>{error ? null : "Загрузка…"}</p></Card>;
  return (
    <Card title="Панель Remnawave" error={error} hint="Профили конфигурации, Internal Squads и хосты панели с повседневными действиями. Редактор конфигурации Xray остаётся в самой панели.">
      <h4>Профили</h4><ul>{d.profiles.map((p: any) => <li key={p.uuid}>{p.name}: {p.inbounds.map((i: any) => `${i.tag} (${i.type}:${i.port})`).join(", ")} <span className="muted">{p.uuid}</span></li>)}</ul>
      <h4>Internal Squads</h4>
      <table className="table"><tbody>{d.squads.map((s: any) => <tr key={s.uuid}><td>{s.name}</td><td>{s.members ?? "?"} участн.</td><td>{s.inbounds.join(", ")}</td>
        <td><button onClick={() => window.confirm(`Добавить всех клиентов в «${s.name}»?`) && act(() => request(`/api/admin/panel/squads/${s.uuid}/add-all`, post()), toast, "Задание запущено", setError, load)}>Добавить всех</button>
          <button onClick={() => window.confirm(`Убрать всех клиентов из «${s.name}»?`) && act(() => request(`/api/admin/panel/squads/${s.uuid}/remove-all`, post()), toast, "Задание запущено", setError, load)}>Убрать всех</button></td></tr>)}</tbody></table>
      <h4>Хосты</h4>
      <table className="table"><tbody>{d.hosts.map((h: any) => <tr key={h.uuid}><td>{h.remark}</td><td>{h.address}:{h.port}</td><td>{h.disabled ? "выключен" : "включён"}</td>
        <td><button onClick={() => act(() => request(`/api/admin/panel/hosts/${h.uuid}`, put({disabled: !h.disabled})), toast, "Сохранено", setError, load)}>{h.disabled ? "Включить" : "Выключить"}</button></td></tr>)}</tbody></table>
    </Card>
  );
}

/** «Настройки → Шаблоны писем» и покупка без Telegram. */
export function EmailTemplates({request, toast}: Props) {
  const [d, load, error, setError] = useData(request, "/api/admin/email-templates");
  const [guest, loadGuest] = useData(request, "/api/admin/guest-checkout");
  const [edit, setEdit] = useState<any>({});
  if (!d || !guest) return <Card title="Шаблоны писем" error={error}><p>Загрузка…</p></Card>;
  return (
    <Card title="Шаблоны писем и покупка по email" error={error} hint={`Подстановки: ${d.placeholders.join(" ")}. Ссылка {link} обязательна.`}>
      <label className="check"><input type="checkbox" checked={guest.enabled} onChange={(e) => act(() => request("/api/admin/guest-checkout", put({enabled: e.target.checked})), toast, "Сохранено", setError, loadGuest)}/> Покупка на сайте по email без Telegram (письмо со ссылкой задать пароль{guest.smtp ? "" : " — SMTP не настроен, письмо не уйдёт"})</label>
      {d.templates.map((t: any) => { const v = edit[t.purpose] ?? {subject: t.subject, body: t.body}; return <div key={t.purpose}>
        <h4>{t.title}{t.custom ? " (изменён)" : ""}</h4>
        <input value={v.subject} onChange={(e) => setEdit({...edit, [t.purpose]: {...v, subject: e.target.value}})}/>
        <textarea rows={4} value={v.body} onChange={(e) => setEdit({...edit, [t.purpose]: {...v, body: e.target.value}})}/>
        <div className="toolbar"><button onClick={() => act(() => request(`/api/admin/email-templates/${t.purpose}`, put(v)), toast, "Шаблон сохранён", setError, load)}>Сохранить</button>
          {t.custom ? <button onClick={() => act(() => request(`/api/admin/email-templates/${t.purpose}`, {method: "DELETE"}), toast, "Вернули стандартный", setError, () => { setEdit({...edit, [t.purpose]: undefined}); load(); })}>Стандартный</button> : null}</div></div>; })}
    </Card>
  );
}

/** Ready themes for the Mini App and the cabinet. */
export function ThemePresets({request, toast}: Props) {
  const [d, , error, setError] = useData(request, "/api/admin/app-config/themes");
  if (!d) return <Card title="Темы Mini App" error={error}><p>Загрузка…</p></Card>;
  async function apply(theme: any) {
    const cfg = await request("/api/admin/app-config");
    const {id: _id, title: _title, ...colors} = theme;
    await request("/api/admin/app-config", put({...cfg.overrides, theme: {...cfg.overrides.theme, ...colors}}));
  }
  return (
    <Card title="Готовые темы Mini App и кабинета" error={error} hint="Один клик заполняет цвета и скругление; дальше всё можно поправить в редакторе ниже.">
      <div className="toolbar">{d.themes.map((t: any) => <button key={t.id} style={{background: t.background, color: t.text, border: `2px solid ${t.accent}`, borderRadius: t.radius}}
        onClick={() => act(() => apply(t), toast, `Тема «${t.title}» применена`, setError)}>{t.title}</button>)}</div>
    </Card>
  );
}
