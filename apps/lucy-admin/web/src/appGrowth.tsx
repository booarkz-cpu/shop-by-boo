import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const when = (v?: string | null) => (v ? new Date(v).toLocaleString() : "—");

const STATUS: Record<string, string> = {sent: "отправлена", sending: "отправляется", scheduled: "запланирована", cancelled: "отменена"};
const moscow = (v?: string | null) => (v ? `${v.replace("T", " ")} МСК` : "—");

/** «Приложения: push-кампании»: a message to a segment — now or at a Moscow time, optionally as an A/B test of two texts. */
export function PushCampaigns({d, request, reload, toast}: {d: any; request: Request; reload: () => void; toast: (m: string) => void}) {
  const segments: Record<string, string> = d?.segments || {};
  const [segment, setSegment] = useState("expiring");
  const [days, setDays] = useState(3);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [later, setLater] = useState(false);
  const [sendAt, setSendAt] = useState("");
  const [ab, setAb] = useState(false);
  const [titleB, setTitleB] = useState("");
  const [bodyB, setBodyB] = useState("");
  const [bPercent, setBPercent] = useState(50);
  const [window_, setWindow] = useState(7);
  const [reach, setReach] = useState<{recipients: number; with_push: number} | null>(null);
  const [busy, setBusy] = useState(false);
  const needsDays = ["expiring", "expired", "inactive"].includes(segment);
  useEffect(() => {
    if (!d?.segments) return;
    let live = true;
    setReach(null);
    request("/api/admin/push-campaigns/preview", {method: "POST", body: JSON.stringify({segment, days})})
      .then((r) => live && setReach(r)).catch(() => live && setReach(null));
    return () => { live = false; };
  }, [segment, days, d?.segments]);
  if (!d?.segments) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const ready = d.push_ready || {};
  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!reach || reach.recipients === 0) { toast("В сегменте нет получателей"); return; }
    if (later && !sendAt) { toast("Укажите дату и время отправки"); return; }
    const what = later ? `Запланировать «${title}» на ${moscow(sendAt)}?` : `Отправить «${title}» ${reach.recipients} получателям?`;
    if (!window.confirm(ab ? `${what} A/B: вариант B получат ${bPercent}%.` : what)) return;
    setBusy(true);
    try {
      const payload: any = {segment, days, title, body, conversion_days: window_, send_at: later ? sendAt : ""};
      if (ab) Object.assign(payload, {title_b: titleB, body_b: bodyB, b_percent: bPercent});
      const row = await request("/api/admin/push-campaigns", {method: "POST", body: JSON.stringify(payload)});
      toast(row.status === "scheduled" ? `Запланировано на ${moscow(row.scheduled_msk)}` : `Отправлено: ${row.recipients}, с push: ${row.with_push}`);
      setTitle(""); setBody(""); setTitleB(""); setBodyB(""); reload();
    } catch (err: any) { toast(err?.message || "Не удалось отправить"); }
    finally { setBusy(false); }
  }
  async function cancel(id: number) {
    if (!window.confirm("Отменить запланированную кампанию?")) return;
    try { await request(`/api/admin/push-campaigns/${id}/cancel`, {method: "POST"}); toast("Кампания отменена"); reload(); }
    catch (err: any) { toast(err?.message || "Не удалось отменить"); }
  }
  return <div className="stack" data-push-campaigns>
    <div className="card">
      <h3>Новая кампания</h3>
      <p className="muted">Сообщение попадает в «Уведомления» приложения, кабинета и Mini App каждому клиенту сегмента и приходит push-уведомлением на телефоны, где push включён. Сегмент считается в момент отправки.</p>
      <p className="muted">Push: Android (FCM) — {ready.fcm ? "настроен" : "не настроен"}, iOS (APNs) — {ready.apns ? "настроен" : "не настроен"}.</p>
      <form onSubmit={send} className="stack">
        <label>Кому
          <select value={segment} onChange={(e) => setSegment(e.target.value)} aria-label="Сегмент">
            {Object.entries(segments).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {needsDays && <label>Дней (N)<input type="number" min={1} max={90} value={days} onChange={(e) => setDays(Math.max(1, Math.min(90, Number(e.target.value) || 1)))}/></label>}
        <p data-reach className="muted">{reach ? `Получателей: ${reach.recipients} · с push: ${reach.with_push}` : "Считаем получателей…"}</p>
        <label>Заголовок<input maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} required placeholder="Подписка заканчивается через 3 дня"/></label>
        <label>Текст<textarea maxLength={1000} rows={4} value={body} onChange={(e) => setBody(e.target.value)} required placeholder="Продлите сейчас со скидкой 10% по промокоду LUSI10"/></label>
        <label className="check"><input type="checkbox" checked={ab} onChange={(e) => setAb(e.target.checked)}/> A/B-тест: второй вариант текста</label>
        {ab && <div className="stack" data-ab>
          <label>Заголовок B<input maxLength={120} value={titleB} onChange={(e) => setTitleB(e.target.value)} required/></label>
          <label>Текст B<textarea maxLength={1000} rows={3} value={bodyB} onChange={(e) => setBodyB(e.target.value)} required/></label>
          <label>Доля варианта B, %<input type="number" min={1} max={90} value={bPercent} onChange={(e) => setBPercent(Math.max(1, Math.min(90, Number(e.target.value) || 50)))}/></label>
          <p className="muted">Получатели делятся случайно, но постоянно: один клиент всегда видит один вариант. Итог — доля оплативших за окно ниже.</p>
        </div>}
        <label>Считать оплаты в течение, дней<input type="number" min={1} max={30} value={window_} onChange={(e) => setWindow(Math.max(1, Math.min(30, Number(e.target.value) || 7)))}/></label>
        <label className="check"><input type="checkbox" checked={later} onChange={(e) => setLater(e.target.checked)}/> Отправить позже</label>
        {later && <label>Когда (время московское)<input type="datetime-local" value={sendAt} min={d.now_msk} onChange={(e) => setSendAt(e.target.value)} aria-label="Когда отправить"/></label>}
        <button className="primary" disabled={busy || !title.trim() || !body.trim() || (ab && (!titleB.trim() || !bodyB.trim()))}>
          {busy ? "Отправляем…" : later ? "Запланировать" : "Отправить"}</button>
      </form>
    </div>
    <div className="card">
      <h3>Кампании</h3>
      {(d.items || []).length === 0 ? <p className="muted">Кампаний ещё не было.</p> :
        <table><thead><tr><th>Когда</th><th>Статус</th><th>Сегмент</th><th>Текст</th><th>Получателей</th><th>С push</th><th>Кто</th><th></th></tr></thead>
          <tbody>{d.items.map((c: any) => <tr key={c.id} data-campaign={c.id} data-status={c.status}>
            <td>{c.status === "scheduled" ? moscow(c.scheduled_msk) : when(c.sent_at || c.created_at)}</td>
            <td>{STATUS[c.status] || c.status}</td>
            <td>{segments[c.segment] || c.segment}{["expiring", "expired", "inactive"].includes(c.segment) ? ` · ${c.days} дн.` : ""}</td>
            <td><b>{c.title}</b><br/><span className="muted">{c.body}</span>
              {c.title_b && <><br/><span className="badge">B · {c.b_percent}%</span> <b>{c.title_b}</b><br/><span className="muted">{c.body_b}</span></>}
              {c.results && <div data-ab-results>{c.results.variants.map((v: any) => <p key={v.variant} className={c.results.winner === v.variant ? "winner" : ""}>
                {v.variant.toUpperCase()}: {v.paid} из {v.recipients} оплатили ({v.conversion}%), {v.revenue} ₽{c.results.winner === v.variant ? " — лучше" : ""}</p>)}
                <p className="muted">{c.results.winner ? `Разница значима (p = ${c.results.p_value}).` : "Разница пока не значима."} {c.results.complete ? "Окно закрыто." : `Окно ${c.results.window_days} дн. ещё идёт.`}</p></div>}
            </td><td>{c.recipients}</td><td>{c.with_push}</td><td>{c.created_by}</td>
            <td>{c.status === "scheduled" && <button onClick={() => cancel(c.id)}>Отменить</button>}</td></tr>)}</tbody></table>}
    </div>
  </div>;
}

const SCREEN_NAMES: Record<string, string> = {vpn: "VPN", locations: "Локации", premium: "Премиум", subscription: "Подписка", settings: "Настройки",
  support: "Поддержка", devices: "Устройства", family: "Семья", referral: "Пригласи друга", wallet: "Баланс", gifts: "Подарки",
  giveaways: "Розыгрыши", notifications: "Уведомления", status: "Состояние", security: "Безопасность", info: "Информация"};

/** «Приложения: аналитика»: installs, sign-in, «Подключить», checkout and per-screen conversion of the apps. */
export function AppAnalytics({d, request}: {d: any; request: Request}) {
  const [data, setData] = useState<any>(d);
  const [days, setDays] = useState(30);
  const [platform, setPlatform] = useState("");
  useEffect(() => { setData(d); }, [d]);
  useEffect(() => {
    if (days === 30 && platform === "") return;
    request(`/api/admin/app-analytics?days=${days}&platform=${platform}`).then(setData).catch(() => {});
  }, [days, platform]);
  if (!data?.funnel?.steps) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const steps: any[] = data.funnel.steps;
  const top = Math.max(1, ...steps.map((f: any) => f.count));
  const worst = data.funnel.biggest_drop;
  return <div className="retention" data-app-analytics>
    {!data.enabled && <div className="card"><p>Сбор статистики выключен: «Приложения: экраны и кнопки» → блоки экранов → «Анонимная статистика приложения».</p></div>}
    <div className="toolbar">
      <label>Период<select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Период">
        {[7, 30, 90, 180].map((n) => <option key={n} value={n}>{n} дней</option>)}</select></label>
      <label>Платформа<select value={platform} onChange={(e) => setPlatform(e.target.value)} aria-label="Платформа">
        <option value="">Android и iOS</option><option value="android">Android</option><option value="ios">iOS</option></select></label>
    </div>
    <div className="kpis">
      <div className="card kpi"><span>Активных установок</span><b>{data.active_installs}</b></div>
      <div className="card kpi"><span>Android</span><b>{data.platforms?.android || 0}</b></div>
      <div className="card kpi"><span>iOS</span><b>{data.platforms?.ios || 0}</b></div>
      <div className="card kpi"><span>Нажатий «Подключить»</span><b>{data.events?.connect_tap || 0}</b></div>
    </div>
    <div className="card">
      <h3>Воронка</h3>
      <p className="muted">Установки за период и сколько из них дошли до каждого шага по порядку: вход → тариф → оплата → подключение. «Оплатили» — по платежам магазина, не по данным приложения.</p>
      {data.funnel.cohort === 0 ? <p className="muted">Новых установок за период нет.</p> :
        <table data-funnel><thead><tr><th>Шаг</th><th></th><th>Установок</th><th>От установок</th><th>От прошлого шага</th><th>Ушли</th><th>Медиана, мин</th></tr></thead>
          <tbody>{steps.map((f: any) => <tr key={f.step} data-step={f.step} className={f.step === worst ? "funnel-worst" : ""}>
            <td>{f.title}</td><td><span className="bar" style={{display: "inline-block", width: `${Math.round(f.count * 100 / top)}px`}}/></td>
            <td>{f.count}</td><td>{f.of_installs}%</td><td>{f.step === "install" ? "—" : `${f.from_previous}%`}</td>
            <td>{f.step === "install" ? "—" : `${f.drop_off}%`}</td><td>{f.median_minutes ?? "—"}</td></tr>)}</tbody></table>}
      {worst && <p data-funnel-worst>Больше всего уходят на шаге «{steps.find((f: any) => f.step === worst)?.title}».</p>}
    </div>
    <div className="grid2">
      <div className="card">
        <h3>Экраны</h3>
        {(data.screens || []).length === 0 ? <p className="muted">Данных пока нет.</p> :
          <table><thead><tr><th>Экран</th><th>Просмотров</th><th>Установок</th><th>Дошли до оплаты</th></tr></thead>
            <tbody>{data.screens.map((s: any) => <tr key={s.screen} data-screen={s.screen}><td>{SCREEN_NAMES[s.screen] || s.screen}</td><td>{s.views}</td><td>{s.installs}</td><td>{s.to_checkout}%</td></tr>)}</tbody></table>}
      </div>
      <div className="card">
        <h3>По дням</h3>
        {(data.daily || []).length === 0 ? <p className="muted">Данных пока нет.</p> :
          <table><thead><tr><th>День</th><th>Новых установок</th><th>Активных</th></tr></thead>
            <tbody>{data.daily.slice(-14).map((r: any) => <tr key={r.day}><td>{r.day}</td><td>{r.installs}</td><td>{r.active}</td></tr>)}</tbody></table>}
        <h3>Версии</h3>
        {(data.versions || []).map((v: any) => <p key={v.platform + v.version}>{v.platform === "ios" ? "iOS" : "Android"} {v.version} — {v.installs}</p>)}
      </div>
    </div>
    <p className="muted">Приложения отправляют только случайный номер установки, платформу, версию, событие и экран — без IP-адресов, моделей устройств и рекламных идентификаторов. События хранятся 180 дней.</p>
  </div>;
}
