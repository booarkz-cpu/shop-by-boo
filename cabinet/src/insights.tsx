import React, {useEffect, useState} from "react";

/** v28.37 customer surfaces: avatar, «Моя статистика», one-click offers, referral contest, smart cart, guest purchase. */
type RequestFn = (path: string, options?: RequestInit) => Promise<any>;

/** Telegram profile photo (avatar.py) with the initial as a fallback. */
export function Avatar({api, name, className = "profile-avatar"}: {api: string; name: string; className?: string}) {
  const [failed, setFailed] = useState(false);
  const initial = String(name || "?").slice(0, 1).toUpperCase();
  return <span className={className} aria-hidden="true">{failed ? initial
    : <img src={`${api}/api/me/avatar`} alt="" width={32} height={32} style={{borderRadius: "50%", objectFit: "cover"}} onError={() => setFailed(true)}/>}</span>;
}

/** «Моя статистика» (customer_insights.py). */
export function MyStats({request}: {request: RequestFn}) {
  const [s, setS] = useState<any>(null);
  useEffect(() => { request("/api/me/stats").then(setS).catch(() => setS(null)); }, [request]);
  if (!s) return null;
  const items: [string, string][] = [
    ["С нами", `${s.days_with_us} дн.`],
    ["Оплачено VPN", `${s.days_paid} дн.`],
    ["Трафик за период", s.traffic_used_gb === null ? "—" : `${s.traffic_used_gb} ГБ${s.traffic_limit_gb ? ` из ${s.traffic_limit_gb}` : ""}`],
    ["Трафик всего", s.traffic_lifetime_gb === null ? "—" : `${s.traffic_lifetime_gb} ГБ`],
    ["Устройства", `${s.devices}${s.device_limit ? ` из ${s.device_limit}` : ""}`],
    ["Обходов блокировок", String(s.blocked_servers_avoided)],
  ];
  return <section className="form-card"><h3>Моя статистика</h3><div className="metrics">{items.map(([k, v]) =>
    <div className="metric" key={k}><span className="label">{k}</span><strong className="value">{v}</strong></div>)}</div></section>;
}

/** One-click offers: buys through the quote/purchase API or the normal checkout. */
export function UpsellOffers({request, onChanged, onCheckout}: {request: RequestFn; onChanged: () => void; onCheckout: (body: any) => void}) {
  const [offers, setOffers] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => { request("/api/me/upsell").then((r: any) => setOffers(r.offers || [])).catch(() => setOffers([])); }, [request]);
  if (!offers.length) return null;
  async function take(o: any) {
    setBusy(true); setMsg("");
    try {
      if (o.checkout) { onCheckout(o.checkout); return; }
      const quote = await request("/api/me/subscription/quote", {method: "POST", body: JSON.stringify(o.quote)});
      await request("/api/me/subscription/purchase", {method: "POST", headers: {"Idempotency-Key": crypto.randomUUID()}, body: JSON.stringify({quote_id: quote.id})});
      setMsg("Готово: условия подписки обновлены"); onChanged();
    } catch (e: any) { setMsg(e.message || "Не получилось — попробуйте в разделе «Тарифы»"); } finally { setBusy(false); }
  }
  return <section className="form-card"><h3>Для вас</h3>{msg && <p className="workspace-alert" role="status">{msg}</p>}
    {offers.map((o, i) => <div className="btn-row" key={i}><div><strong>{o.title}</strong><br/><span className="muted">{o.reason}</span></div>
      <button className="btn-primary" disabled={busy} onClick={() => take(o)}>{o.price} ₽</button></div>)}</section>;
}

/** The current referral contest with the leaderboard and the customer's place. */
export function ReferralContest({request}: {request: RequestFn}) {
  const [c, setC] = useState<any>(null);
  useEffect(() => { request("/api/me/referral-contest").then((r: any) => setC(r.contest)).catch(() => setC(null)); }, [request]);
  if (!c) return null;
  return <section className="form-card"><h3>🏆 {c.title}</h3>
    <p>До {new Date(c.ends_at).toLocaleDateString()} · считаются друзья, которые {c.metric === "paid" ? "оплатили подписку" : "пришли по вашей ссылке"}.</p>
    <p>Призы: {c.prizes.map((p: any) => `${p.place} место — ${p.days ? `${p.days} дн.` : ""}${p.days && Number(p.amount) ? " и " : ""}${Number(p.amount) ? `${p.amount} ₽` : ""}`).join("; ")}</p>
    <ol>{c.top.map((r: any) => <li key={r.place}>{r.name} — {r.score}</li>)}</ol>
    <p><strong>{c.me ? `Вы на ${c.me.place} месте (${c.me.score})` : "Пригласите друга, чтобы попасть в таблицу"}</strong></p></section>;
}

/** «Не хватает на балансе»: save the purchase, top up the difference, the shop buys it after the top-up (smart_cart.py). */
export async function topUpAndBuy(request: RequestFn, body: any, topup: (amount: string) => Promise<void>): Promise<string> {
  const cart = await request("/api/me/cart", {method: "POST", body: JSON.stringify(body)});
  if (cart.bought) return "Оплачено с баланса";
  await topup(cart.topup);
  return `Пополните баланс на ${cart.topup} ₽ — покупка пройдёт сама сразу после пополнения`;
}

/** Guest purchase by e-mail (guest_checkout.py): shown on the sign-in screen when enabled. */
export function GuestPurchase({request, onReady}: {request: RequestFn; onReady: () => void}) {
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function start(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const invite = new URLSearchParams(location.search).get("invite") || undefined;
      await request("/api/auth/guest", {method: "POST", body: JSON.stringify({email: email.trim(), consent, invite})});
      onReady();
    } catch (err: any) { setError(err.message || "Не получилось"); } finally { setBusy(false); }
  }
  return <form className="form-card stack" onSubmit={start} aria-label="Покупка по email">
    <h3>Купить без Telegram</h3><p className="muted">Укажите почту — подписка и инструкции будут в кабинете, а письмо поможет задать пароль.</p>
    {error && <p className="workspace-alert" role="alert">{error}</p>}
    <label className="field">Email<input type="email" required maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)}/></label>
    <label className="check"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}/> Принимаю условия публичной оферты</label>
    <button className="btn-primary" disabled={busy || !consent}>Продолжить к оплате</button></form>;
}

/** Report a screen to the activity timeline (activity_log.py); silent and best-effort. */
export function reportScreen(request: RequestFn, screen: string) {
  const surface = (window as any).Telegram?.WebApp?.initData ? "miniapp" : "cabinet";
  request("/api/me/activity", {method: "POST", body: JSON.stringify({surface, action: "screen", screen: screen.slice(0, 48)})}).catch(() => undefined);
}
