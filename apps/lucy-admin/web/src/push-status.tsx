import React, {useEffect, useState} from "react";
import {Smartphone} from "lucide-react";
import {StatusBadge, type Tone} from "./components/ui/status";

type Status = {
  providers: {fcm: {configured: boolean; project_id: string | null}; apns: {configured: boolean; environment: string; bundle_id: string | null}};
  devices: {android: number; ios: number};
  revoked_7d: Record<string, number>;
  deliveries_24h: Record<string, number>;
  top_errors_24h: {error: string; count: number}[];
};

const DELIVERY: [string, string, Tone][] = [
  ["sent", "Доставлено", "ok"],
  ["queued", "В очереди", "info"],
  ["sending", "Отправляется", "info"],
  ["failed", "Ошибка", "danger"],
  ["skipped", "Пропущено", "idle"],
  ["expired", "Истекло", "warn"],
];
const REASONS: Record<string, string> = {
  session_ended: "выход из аккаунта",
  invalid_token: "токен недействителен",
  unregistered: "выключено клиентом",
  removed: "удалено клиентом",
  replaced: "токен обновлён",
  reassigned: "вход в другой аккаунт",
  account_closed: "аккаунт закрыт",
  limit: "лимит устройств",
};

/** Native push readiness: provider keys, registered devices and 24h delivery outcome. */
export function PushStatus({request}: {request: (path: string, options?: RequestInit) => Promise<any>}) {
  const [data, setData] = useState<Status | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    request("/api/admin/push/status")
      .then((value: Status) => live && setData(value))
      .catch((e: any) => live && setError(e?.message || "Нет доступа"));
    return () => {
      live = false;
    };
  }, [request]);

  if (error) return <p className="muted" role="status">Push-уведомления: {error}</p>;
  if (!data)
    return (
      <section className="card push-status" aria-busy="true">
        <div className="ui-skeleton" style={{height: 96}} />
      </section>
    );
  const provider = (ok: boolean, label: string, detail: string) => (
    <div className="push-provider">
      <StatusBadge tone={ok ? "ok" : "idle"}>{ok ? "Настроен" : "Не настроен"}</StatusBadge>
      <strong>{label}</strong>
      <span className="muted">{detail}</span>
    </div>
  );
  const revoked = Object.entries(data.revoked_7d);
  return (
    <section className="card push-status" aria-label="Push-уведомления">
      <h2>
        <Smartphone aria-hidden="true" /> Push-уведомления
      </h2>
      <div className="push-grid">
        {provider(data.providers.fcm.configured, "Android · FCM", data.providers.fcm.project_id || "FCM_PROJECT_ID не задан")}
        {provider(data.providers.apns.configured, "iOS · APNs", `${data.providers.apns.bundle_id || "—"} · ${data.providers.apns.environment}`)}
        <div className="push-provider">
          <strong>Активные устройства</strong>
          <span>
            Android {data.devices.android} · iOS {data.devices.ios}
          </span>
        </div>
      </div>
      <div className="push-deliveries" aria-label="Доставка за 24 часа">
        {DELIVERY.filter(([key]) => data.deliveries_24h[key]).map(([key, label, tone]) => (
          <StatusBadge key={key} tone={tone}>
            {label}: {data.deliveries_24h[key]}
          </StatusBadge>
        ))}
        {!Object.keys(data.deliveries_24h).length && <span className="muted">За 24 часа отправок не было</span>}
      </div>
      {revoked.length > 0 && (
        <p className="muted">
          Отключено за 7 дней: {revoked.map(([key, count]) => `${REASONS[key] || key} — ${count}`).join(", ")}
        </p>
      )}
      {data.top_errors_24h.length > 0 && (
        <ul className="push-errors">
          {data.top_errors_24h.map((row) => (
            <li key={row.error}>
              <code>{row.error}</code> × {row.count}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
