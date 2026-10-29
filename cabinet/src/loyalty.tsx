import React, {useEffect, useState} from "react";

/** v28.51 «Уровни лояльности»: текущий уровень, что он даёт и сколько осталось до следующего. */
type RequestFn = (path: string, options?: RequestInit) => Promise<any>;

const perks = (x: any) => [x.cashback_percent ? `кешбэк ${x.cashback_percent}%` : "", x.discount_percent ? `скидка ${x.discount_percent}%` : "", x.bonus_days ? `+${x.bonus_days} дн. при переходе` : ""].filter(Boolean).join(", ") || "—";

export function LoyaltySection({request}: {request: RequestFn}) {
  const [l, setL] = useState<any>(null);
  useEffect(() => { request("/api/me/loyalty").then(setL).catch(() => setL(null)); }, [request]);
  if (!l || !l.enabled) return null;
  return (
    <div className="workspace-form loyalty-section">
      <h3>Ваш уровень: {l.title}</h3>
      <p>{perks(l)}{Number(l.cashback_earned) > 0 ? ` · кешбэка получено ${l.cashback_earned} ₽` : ""}</p>
      {l.next ? <p className="section-sub">До уровня «{l.next.title}»: {l.next.need || "совсем немного"}. Там: {perks(l.next)}.</p>
              : <p className="section-sub">У вас высший уровень — спасибо, что вы с нами!</p>}
      <div className="loyalty-levels">
        {l.levels.map((x: any, i: number) => <div key={x.title} className={i === l.index ? "loyalty-level current" : "loyalty-level"}>
          <strong>{x.title}</strong><span>{i === 0 ? "с первой оплаты" : `${x.months} мес. или ${x.spent} ₽`}</span><span>{perks(x)}</span>
        </div>)}
      </div>
    </div>
  );
}
