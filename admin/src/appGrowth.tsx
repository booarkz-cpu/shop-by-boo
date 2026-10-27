import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const when = (v?: string | null) => (v ? new Date(v).toLocaleString() : "—");

/** «Приложения: push-кампании»: a message to a segment, in-app and as push on every app with push on. */
export function PushCampaigns({d, request, reload, toast}: {d: any; request: Request; reload: () => void; toast: (m: string) => void}) {
  const segments: Record<string, string> = d?.segments || {};
  const [segment, setSegment] = useState("expiring");
  const [days, setDays] = useState(3);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
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
    if (!window.confirm(`Отправить «${title}» ${reach.recipients} получателям?`)) return;
    setBusy(true);
    try {
      const row = await request("/api/admin/push-campaigns", {method: "POST", body: JSON.stringify({segment, days, title, body})});
      toast(`Отправлено: ${row.recipients}, с push: ${row.with_push}`);
      setTitle(""); setBody(""); reload();
    } catch (err: any) { toast(err?.message || "Не удалось отправить"); }
    finally { setBusy(false); }
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
        <button className="primary" disabled={busy || !title.trim() || !body.trim()}>{busy ? "Отправляем…" : "Отправить"}</button>
      </form>
    </div>
    <div className="card">
      <h3>Отправленные</h3>
      {(d.items || []).length === 0 ? <p className="muted">Кампаний ещё не было.</p> :
        <table><thead><tr><th>Когда</th><th>Сегмент</th><th>Заголовок</th><th>Получателей</th><th>С push</th><th>Кто</th></tr></thead>
          <tbody>{d.items.map((c: any) => <tr key={c.id} data-campaign={c.id}>
            <td>{when(c.created_at)}</td><td>{segments[c.segment] || c.segment}{["expiring", "expired", "inactive"].includes(c.segment) ? ` · ${c.days} дн.` : ""}</td>
            <td><b>{c.title}</b><br/><span className="muted">{c.body}</span></td><td>{c.recipients}</td><td>{c.with_push}</td><td>{c.created_by}</td></tr>)}</tbody></table>}
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
  if (!data?.funnel) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const top = Math.max(1, data.funnel[0]?.count || 0, ...data.funnel.map((f: any) => f.count));
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
      <p className="muted">Уникальные установки, дошедшие до шага. «Оплатили» — клиенты приложения с оплаченным платежом магазина за период.</p>
      {data.funnel.map((f: any, i: number) => <div className="reason-row" key={f.step} data-step={f.step}>
        <span>{f.title}</span><span className="bar" style={{width: `${Math.round(f.count * 100 / top)}%`}}/>
        <b>{f.count}{i > 0 && data.funnel[i - 1].count > 0 ? ` · ${Math.round(f.count * 100 / data.funnel[i - 1].count)}%` : ""}</b></div>)}
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
