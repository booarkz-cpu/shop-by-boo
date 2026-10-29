import React from "react";
import {ArrowRight, CalendarClock, Copy, Gauge, Gift, QrCode, ShieldCheck, Smartphone, Wallet, Zap} from "lucide-react";
import {daysLeft, formatBytes, Meter, pluralDays, StatusBadge, type Tone} from "./ui";

export type Traffic = {available?: boolean; traffic_used_bytes?: number | null; traffic_limit_bytes?: number | null; devices?: number | null} | null;

type Props = {
  sub: any;
  user: any;
  traffic: Traffic;
  subUrl: string;
  currency: string;
  api: string;
  copied: boolean;
  onCopy: (url: string) => void;
  go: (kind: string) => void;
  formatDate: (value?: string | null) => string;
};

function subscriptionState(sub: any): {tone: Tone; label: string} {
  const left = daysLeft(sub?.expires_at);
  if (!sub || left === null) return {tone: "idle", label: "Нет подписки"};
  if (left <= 0) return {tone: "danger", label: "Истекла"};
  if (sub.status === "cancel_scheduled") return {tone: "warn", label: "Отмена запланирована"};
  if (sub.status === "frozen") return {tone: "warn", label: "Заморожена"};
  if (left <= 3) return {tone: "warn", label: "Скоро истечёт"};
  return {tone: "ok", label: "Активна"};
}

/** Subscription status, traffic, expiry and the fastest way to connect — the first screen. */
export function Overview({sub, user, traffic, subUrl, currency, api, copied, onCopy, go, formatDate}: Props) {
  const state = subscriptionState(sub);
  const left = daysLeft(sub?.expires_at);
  const used = traffic?.traffic_used_bytes ?? null;
  const limit = traffic?.traffic_limit_bytes ?? null;
  const unlimited = Boolean(traffic) && !limit;
  const remaining = limit && used !== null ? Math.max(0, limit - used) : null;
  const usage = limit && used !== null ? used / limit : null;
  const trafficTone: Tone = usage === null ? "info" : usage >= 0.9 ? "danger" : usage >= 0.75 ? "warn" : "ok";
  const periodTone: Tone = left === null ? "idle" : left <= 3 ? "warn" : "ok";
  return (
    <div className="overview">
      <section className="sub-hero" data-tone={state.tone} aria-label="Статус подписки">
        <div className="sub-hero-top">
          <div>
            <span className="eyebrow">Моя подписка</span>
            <h2>{sub?.name || (sub ? "VPN-подписка" : "Подписка не подключена")}</h2>
          </div>
          <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
        </div>

        {sub ? (
          <div className="sub-hero-stats">
            <div className="sub-stat">
              <span className="sub-stat-label">
                <CalendarClock aria-hidden="true" />
                Срок действия
              </span>
              <strong>{left !== null && left > 0 ? `${left} ${pluralDays(left)}` : "Истекла"}</strong>
              <small>до {formatDate(sub.expires_at)}</small>
              <Meter label="Оставшийся срок" tone={periodTone} value={left === null ? null : Math.min(1, Math.max(0, left / 30))} />
            </div>
            <div className="sub-stat">
              <span className="sub-stat-label">
                <Gauge aria-hidden="true" />
                Оставшийся трафик
              </span>
              <strong>{unlimited ? "Безлимит" : remaining !== null ? formatBytes(remaining) : "—"}</strong>
              <small>{unlimited ? "Без ограничения трафика" : limit ? `Использовано ${formatBytes(used)} из ${formatBytes(limit)}` : "Данные появятся после подключения"}</small>
              <Meter label="Использованный трафик" tone={trafficTone} value={unlimited ? 0 : usage} />
            </div>
            <div className="sub-stat">
              <span className="sub-stat-label">
                <Smartphone aria-hidden="true" />
                Устройства
              </span>
              <strong>{typeof traffic?.devices === "number" ? traffic.devices : "—"}</strong>
              <small>Подключено к подписке</small>
            </div>
          </div>
        ) : (
          <p className="sub-hero-empty">Выберите тариф или активируйте пробный период — доступ появится сразу после оплаты.</p>
        )}

        <div className="sub-hero-actions">
          {sub ? (
            <>
              <button type="button" className="btn-primary" onClick={() => go("plans")}>
                <Zap aria-hidden="true" />
                Продлить подписку
              </button>
              <button type="button" className="btn-ghost" onClick={() => go("connection")}>
                <QrCode aria-hidden="true" />
                Подключить устройство
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn-primary" onClick={() => go("plans")}>
                <Zap aria-hidden="true" />
                Выбрать тариф
              </button>
              <button type="button" className="btn-ghost" onClick={() => go("trial")}>
                <Gift aria-hidden="true" />
                Пробный период
              </button>
            </>
          )}
        </div>
      </section>

      {subUrl && (
        <section className="form-card quick-connect" aria-label="Быстрое подключение">
          <img className="connection-qr" src={api + "/api/me/connection-qr"} alt="QR-код вашей подписки" width={148} height={148} />
          <div className="quick-connect-copy">
            <h3>Быстрое подключение</h3>
            <p className="section-sub">Отсканируйте QR-код в VPN-клиенте или скопируйте ссылку подписки.</p>
            <div className="btn-row">
              <button type="button" className="btn-primary" onClick={() => onCopy(subUrl)}>
                <Copy aria-hidden="true" />
                {copied ? "Скопировано" : "Копировать ссылку"}
              </button>
              <button type="button" className="btn-ghost" onClick={() => go("connection")}>
                Инструкция
                <ArrowRight aria-hidden="true" />
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="tile-grid">
        <button type="button" className="tile" onClick={() => go("wallet")}>
          <Wallet aria-hidden="true" />
          <span>Кошелёк</span>
          <strong>
            {user?.wallet_balance || "0.00"} {currency}
          </strong>
        </button>
        <button type="button" className="tile" onClick={() => go("referral")}>
          <Gift aria-hidden="true" />
          <span>Реферальный баланс</span>
          <strong>
            {user?.referral_balance || "0.00"} {currency}
          </strong>
        </button>
        <button type="button" className="tile" onClick={() => go("security")}>
          <ShieldCheck aria-hidden="true" />
          <span>Код приглашения</span>
          <strong className="mono">{user?.referral_code || "—"}</strong>
        </button>
      </div>
    </div>
  );
}
