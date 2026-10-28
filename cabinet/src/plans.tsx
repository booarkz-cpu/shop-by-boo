import React from "react";
import {Check, CreditCard, Gift, Wallet} from "lucide-react";

type Pick = Record<string, number>;
type Props = {
  plans: any[];
  constructors: any[];
  pick: Record<number, Pick>;
  setPick: React.Dispatch<React.SetStateAction<Record<number, Pick>>>;
  defaultPick: (row: any) => Pick;
  constructorTotal: (row: any, selected: Pick) => number;
  promo: string;
  setPromo: (value: string) => void;
  providers: string[];
  methods?: {key: string; title: string}[];
  method?: string;
  setMethod?: (value: string) => void;
  provider: string;
  setProvider: (value: string) => void;
  profiles: any[];
  profileTarget: string;
  setProfileTarget: (value: string) => void;
  busy: boolean;
  currency: string;
  buy: (plan: any) => void;
  buyWallet: (plan: any) => void;
  buyConstructor: (row: any, wallet: boolean, gift?: boolean) => void;
  offers: React.ReactNode;
};

const AGENTS: Record<string, string> = {yookassa: "YooKassa", rollypay: "RollyPay", platega: "Platega", cryptobot: "Криптовалюта (CryptoBot)",freekassa:"Карта или СБП (Freekassa)",cloudpayments:"Карта или СБП (CloudPayments)",lava:"Карта или СБП (Lava)",pal24:"Карта или СБП (Pal24)",mulenpay:"Карта или СБП (Mulen Pay)",wata:"Карта или СБП (WATA)",antilopay:"Карта или СБП (Antilopay)",aurapay:"Карта или СБП (AuraPay)",anore:"Карта или СБП (Anore)",cashera:"Карта или СБП (Cashera)",paritypay:"Карта или СБП (ParityPay)", sandbox: "Тестовый платёж"};

function features(plan: any): string[] {
  const out: string[] = [];
  if (plan.traffic_limit_gb === 0 || plan.traffic_limit_gb === null || plan.traffic_limit_gb === undefined) out.push("Безлимитный трафик");
  else out.push(`${plan.traffic_limit_gb} ГБ трафика`);
  if (plan.device_limit) out.push(`До ${plan.device_limit} устройств`);
  out.push("Все серверы и протоколы");
  return out;
}

/** Tariff catalogue: fixed plans, constructor and the purchase/renewal target. */
export function Plans(props: Props) {
  const {plans, constructors, pick, setPick, defaultPick, constructorTotal, promo, setPromo, providers, methods = [], method = "", setMethod, provider, setProvider, profiles, profileTarget, setProfileTarget, busy, currency, buy, buyWallet, buyConstructor, offers} = props;
  const cheapestPerDay = plans.length ? Math.min(...plans.map((p) => Number(p.final_price ?? p.price) / Math.max(1, Number(p.duration_days) || 1))) : 0;
  return (
    <div className="plans">
      {offers}
      <h2 className="section-title">Тарифы</h2>
      <p className="section-sub">Выберите тариф и способ оплаты</p>

      <section className="form-card checkout-options">
        <label className="field">
          Для какой подписки
          <select value={profileTarget} disabled={busy} onChange={(e) => setProfileTarget(e.target.value)}>
            <option value="current">Продлить выбранную подписку</option>
            <option value="new">Новая независимая подписка</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.plan || `№${p.id}`}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Промокод
          <input value={promo} onChange={(e) => setPromo(e.target.value.toUpperCase())} placeholder="Промокод" autoCapitalize="characters" />
        </label>
        {methods.length > 0 && (
          <fieldset className="field pay-methods">
            <legend>Способ оплаты</legend>
            {methods.map((m) => (
              <label key={m.key} className="check">
                <input type="radio" name="pay-method" checked={method === m.key} onChange={() => setMethod?.(m.key)} /> {m.title}
              </label>
            ))}
          </fieldset>
        )}
        {methods.length === 0 && providers.length > 0 && (
          <label className="field">
            Провайдер оплаты
            <select value={provider} onChange={(e) => setProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p} value={p}>
                  {AGENTS[p] || p}
                </option>
              ))}
            </select>
          </label>
        )}
      </section>

      <div className="plan-grid">
        {plans.map((p) => {
          const price = Number(p.final_price ?? p.price);
          const perDay = price / Math.max(1, Number(p.duration_days) || 1);
          const best = plans.length > 1 && Math.abs(perDay - cheapestPerDay) < 0.005;
          return (
            <article className="plan-card" data-best={best || undefined} key={p.id}>
              {best && <span className="plan-flag">Выгоднее всего</span>}
              <h3>{p.name}</h3>
              <p className="price">
                <strong>
                  {p.final_price ?? p.price} {currency}
                </strong>
                <span> · {p.duration_days} дней</span>
              </p>
              {Number(p.discount) > 0 && (
                <p className="plan-discount">
                  <s>
                    {p.price} {currency}
                  </s>{" "}
                  −{p.discount_percent}%
                </p>
              )}
              <ul className="plan-features">
                {features(p).map((f) => (
                  <li key={f}>
                    <Check aria-hidden="true" />
                    {f}
                  </li>
                ))}
              </ul>
              <div className="btn-row">
                <button type="button" className="btn-primary" disabled={busy || !provider} onClick={() => buy(p)}>
                  <CreditCard aria-hidden="true" />
                  Оплатить
                </button>
                <button type="button" className="btn-ghost" disabled={busy} onClick={() => buyWallet(p)}>
                  <Wallet aria-hidden="true" />
                  С баланса
                </button>
              </div>
            </article>
          );
        })}
        {!plans.length && <p className="section-sub">Выберите тариф</p>}
      </div>

      {!!constructors.length && <h3 className="section-title section-title-sm">Конструктор тарифов</h3>}
      {constructors.map((row) => {
        const selected = pick[row.id] || defaultPick(row);
        const total = constructorTotal(row, selected);
        return (
          <article className="form-card stack constructor-card" key={row.id}>
            <h3>{row.name}</h3>
            <p className="section-sub">{row.description || "Соберите тариф: устройства, трафик и срок"}</p>
            <div className="constructor-fields">
              {(["devices", "traffic_gb", "days"] as const).map((kind) => (
                <label className="field" key={kind}>
                  {kind === "devices" ? "Устройства" : kind === "traffic_gb" ? "Трафик" : "Срок"}
                  <select
                    value={selected[kind] || ""}
                    onChange={(e) =>
                      setPick((prev) => ({
                        ...prev,
                        [row.id]: {...(prev[row.id] || defaultPick(row)), [kind]: Number(e.target.value)},
                      }))
                    }
                  >
                    {(row.options || [])
                      .filter((o: any) => o.kind === kind)
                      .map((o: any) => (
                        <option key={o.id} value={o.id}>
                          {o.label} · {o.value === 0 && kind === "traffic_gb" ? "Безлимит" : o.value}
                          {Number(o.price) ? ` · +${o.price}` : ""}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
            </div>
            <p className="price">
              <strong>
                {total} {currency}
              </strong>
            </p>
            <div className="btn-row">
              <button type="button" className="btn-primary" disabled={busy || !provider} onClick={() => buyConstructor(row, false)}>
                <CreditCard aria-hidden="true" />
                Оплатить
              </button>
              <button type="button" className="btn-ghost" disabled={busy} onClick={() => buyConstructor(row, true)}>
                <Wallet aria-hidden="true" />
                С баланса
              </button>
              <button type="button" className="btn-ghost" disabled={busy} onClick={() => buyConstructor(row, true, true)}>
                <Gift aria-hidden="true" />
                Купить в подарок с баланса
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}
