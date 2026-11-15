import React, {useEffect, useState} from "react";

/** v28.50 «Заморозка подписки»: пауза оплаченной подписки вместо отмены (отпуск, перерыв). */
type RequestFn = (path: string, options?: RequestInit) => Promise<any>;

const day = (v?: string) => v ? new Date(v + (v.endsWith("Z") ? "" : "Z")).toLocaleDateString("ru-RU") : "—";

export function FreezeSection({request, reload, subscriptionId}: {request: RequestFn; reload: () => Promise<void>; subscriptionId?: number}) {
  const [s, setS] = useState<any>(null);
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const query = subscriptionId ? `?subscription_id=${subscriptionId}` : "";
  const load = () => request(`/api/me/freeze${query}`).then(x => { setS(x); setDays(d => Math.min(Math.max(d, x.min_days), x.max_days)); }).catch(() => setS(null));
  useEffect(() => { load(); }, [request, subscriptionId]);
  if (!s || !s.enabled) return null;
  async function act(path: string, body: any) {
    setBusy(true); setError("");
    try { await request(path, {method: "POST", body: JSON.stringify(body)}); await load(); await reload(); }
    catch (e: any) { setError(e.message || "Не получилось"); }
    finally { setBusy(false); }
  }
  if (s.frozen) return (
    <div className="workspace-form freeze-section">
      <h3>Подписка заморожена</h3>
      <p>VPN выключен до {day(s.frozen.until)}. Оплаченные дни сохранены — срок подписки сдвинут на время заморозки.</p>
      <div className="btn-row"><button className="btn-primary" disabled={busy} onClick={() => act("/api/me/freeze/thaw", {subscription_id: s.subscription_id})}>Разморозить сейчас</button></div>
      <p className="section-sub">При досрочной разморозке неиспользованные дни заморозки вычитаются из срока.</p>
      {error && <p className="error">{error}</p>}
    </div>
  );
  return (
    <div className="workspace-form freeze-section">
      <h3>Заморозить подписку</h3>
      <p className="section-sub">Уезжаете или делаете перерыв? Поставьте подписку на паузу: VPN выключится, а оплаченные дни сохранятся. В этом году можно ещё {s.days_left} дн. и {s.times_left} раз.</p>
      {s.reason ? <p className="section-sub">{s.reason}</p> : <>
        <label className="field">На сколько дней<input type="number" min={s.min_days} max={Math.min(s.max_days, s.days_left)} value={days} onChange={e => setDays(Number(e.target.value))}/></label>
        <div className="btn-row"><button className="btn-ghost" disabled={busy} onClick={() => confirm(`Заморозить подписку на ${days} дн.? VPN выключится до разморозки.`) && act("/api/me/freeze", {days, subscription_id: s.subscription_id})}>Заморозить</button></div>
      </>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
