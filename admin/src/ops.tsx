import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

/** «Аналитика → Запуск и оповещения»: launch readiness checks and operator alerts. */
export function OpsReadiness({request, toast}: {request: Request; toast: (m: string) => void}) {
  const [ready, setReady] = useState<any>(null);
  const [alerts, setAlerts] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    setError("");
    try {
      const [r, a] = await Promise.all([request("/api/admin/ops/readiness"), request("/api/admin/ops/alerts")]);
      setReady(r); setAlerts(a);
    } catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);
  async function test() {
    if (busy) return; setBusy(true); setError("");
    try { const r = await request("/api/admin/ops/alerts/test", {method: "POST"}); toast(r.ok ? "Тестовое оповещение отправлено" : "Не удалось отправить: проверьте бота и chat ID"); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  if (!ready || !alerts) return <div className="card">{error ? <div role="alert" className="error">{error}</div> : <p className="muted">Загрузка…</p>}</div>;
  return <div className="ops">
    <div className="card">
      <h3>{ready.ready ? "Магазин готов к приёму оплат" : "Перед запуском осталось"}</h3>
      <p className="muted">Обязательные пункты нужны для продаж, рекомендованные — для уведомлений клиентам и спокойной эксплуатации. Живая проверка касс — по <a href="https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/PAYMENTS_LIVE_CHECKLIST.md" target="_blank" rel="noreferrer">чек-листу</a>.</p>
      {error && <div role="alert" className="error">{error}</div>}
      <ul className="ops-checks">
        {ready.checks.map((c: any) => <li key={c.key} data-check={c.key} data-ok={c.ok ? "1" : "0"}>
          <span className={c.ok ? "ops-ok" : c.level === "required" ? "ops-bad" : "ops-warn"}>{c.ok ? "✓" : c.level === "required" ? "✗" : "!"}</span>
          <div><b>{c.title}</b>{c.level !== "required" && <span className="muted"> · рекомендуется</span>}{c.hint && <p className="muted">{c.hint}</p>}</div>
        </li>)}
      </ul>
      <button onClick={load}>Проверить снова</button>
    </div>
    <div className="card">
      <h3>Оповещения о сбоях</h3>
      <p className="muted">Каждые 5 минут магазин ищет сбои: оплата без выдачи доступа, зависшая выдача, отключённая касса, молчащий фоновый процесс, недоступный Remnawave, упавшая проверка мониторинга или резервная копия, отрицательный баланс клиента. Каждая проблема приходит один раз и повторяется не чаще, чем раз в {alerts.repeat_hours} ч; когда она уходит — приходит «Решено».</p>
      <p>Telegram: <b>{alerts.recipients.telegram ? "настроен" : "не настроен"}</b> · почта: <b>{alerts.recipients.email ? "настроена" : "не настроена"}</b></p>
      {!alerts.recipients.telegram && !alerts.recipients.email && <p className="muted">Укажите в .env <code>ALERT_TELEGRAM_CHAT_ID</code> (группа или ваш ID; без него — <code>ADMIN_TELEGRAM_ID</code>) или <code>ALERT_EMAIL</code> с SMTP и перезапустите backend.</p>}
      <button className="primary" disabled={busy || (!alerts.recipients.telegram && !alerts.recipients.email)} onClick={test}>Отправить тестовое оповещение</button>
      <h4>Сейчас</h4>
      {alerts.problems.length === 0 ? <p className="muted">Проблем нет.</p> : alerts.problems.map((p: any) => <div className="ops-problem" key={p.key} data-problem={p.key}>
        <b>{p.title}</b><p className="muted">{p.detail}</p></div>)}
    </div>
  </div>;
}
