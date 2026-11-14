import React, {useEffect, useMemo, useState} from "react";
import {Eye, EyeOff, Pencil, Plus, RefreshCw, Trash2, TriangleAlert} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
export type Plan = {
  id: number;
  name: string;
  price: number;
  duration_days: number;
  traffic_limit_gb: number | null;
  device_limit: number | null;
  remnawave_profile_id: string | null;
  enabled: boolean;
  family_seats?: number;
};
type Squad = {uuid: string; name: string; members?: number | null; inbounds?: number | null};
type Form = {name: string; price: string; duration_days: string; traffic_limit_gb: string; device_limit: string; remnawave_profile_id: string; enabled: boolean; family_seats?: string};

const DURATIONS = [
  {days: 30, label: "1 месяц"},
  {days: 90, label: "3 месяца"},
  {days: 180, label: "6 месяцев"},
  {days: 365, label: "12 месяцев"},
];
const EMPTY: Form = {name: "", price: "", duration_days: "30", traffic_limit_gb: "0", device_limit: "3", remnawave_profile_id: "", enabled: true, family_seats: "0"};

export function durationLabel(days: number): string {
  return DURATIONS.find((d) => d.days === days)?.label || `${days} дн.`;
}

/** Validates the form and builds the API body; returns an error text instead when the form is wrong. */
export function planBody(form: Form): {body?: Record<string, unknown>; error?: string} {
  const name = form.name.trim();
  const price = Number(form.price.replace(",", "."));
  const days = Number(form.duration_days);
  const traffic = form.traffic_limit_gb.trim() === "" ? 0 : Number(form.traffic_limit_gb);
  const devices = form.device_limit.trim() === "" ? null : Number(form.device_limit);
  if (!name) return {error: "Укажите название тарифа"};
  if (!Number.isFinite(price) || price <= 0) return {error: "Цена должна быть больше нуля"};
  if (!Number.isInteger(days) || days < 1 || days > 3650) return {error: "Срок — целое число дней от 1 до 3650"};
  if (!Number.isInteger(traffic) || traffic < 0) return {error: "Трафик — целое число ГБ, 0 — без ограничения"};
  if (devices !== null && (!Number.isInteger(devices) || devices < 1 || devices > 100)) return {error: "Устройств — от 1 до 100"};
  const seats = (form.family_seats || "").trim() === "" ? 0 : Number(form.family_seats);
  if (!Number.isInteger(seats) || seats < 0 || seats > 10) return {error: "Мест в семье — от 0 до 10"};
  return {
    body: {
      name,
      price: Math.round(price * 100) / 100,
      duration_days: days,
      traffic_limit_gb: traffic === 0 ? null : traffic,
      device_limit: devices,
      remnawave_profile_id: form.remnawave_profile_id.trim() || null,
      enabled: form.enabled,
      family_seats: seats,
    },
  };
}

function toForm(plan: Plan): Form {
  return {
    name: plan.name,
    price: String(plan.price),
    duration_days: String(plan.duration_days),
    traffic_limit_gb: String(plan.traffic_limit_gb || 0),
    device_limit: plan.device_limit ? String(plan.device_limit) : "",
    remnawave_profile_id: plan.remnawave_profile_id || "",
    enabled: plan.enabled,
    family_seats: String(plan.family_seats || 0),
  };
}

function PlanForm({initial, squads, squadError, busy, onSubmit, onCancel, submitLabel}: {
  initial: Form;
  squads: Squad[];
  squadError: string | null;
  busy: boolean;
  onSubmit: (form: Form) => void;
  onCancel?: () => void;
  submitLabel: string;
}) {
  const [form, setForm] = useState<Form>(initial);
  useEffect(() => setForm(initial), [initial]);
  const custom = !DURATIONS.some((d) => String(d.days) === form.duration_days);
  const known = squads.some((s) => s.uuid === form.remnawave_profile_id);
  const set = (patch: Partial<Form>) => setForm({...form, ...patch});
  return (
    <form className="plan-form" onSubmit={(e) => { e.preventDefault(); onSubmit(form); }}>
      <div className="grid2">
        <label className="field">Название тарифа
          <input required maxLength={255} value={form.name} onChange={(e) => set({name: e.target.value})} placeholder="Например: 3 месяца" />
        </label>
        <label className="field">Цена, ₽
          <input required inputMode="decimal" value={form.price} onChange={(e) => set({price: e.target.value})} placeholder="499" />
        </label>
        <label className="field">Срок
          <select value={custom ? "custom" : form.duration_days} onChange={(e) => set({duration_days: e.target.value === "custom" ? "" : e.target.value})}>
            {DURATIONS.map((d) => (
              <option key={d.days} value={d.days}>
                {d.label} ({d.days} дн.)
              </option>
            ))}
            <option value="custom">Другой срок…</option>
          </select>
        </label>
        {custom && (
          <label className="field">Срок, дней
            <input required inputMode="numeric" value={form.duration_days} onChange={(e) => set({duration_days: e.target.value})} placeholder="14" />
          </label>
        )}
        <label className="field">Трафик, ГБ (0 — без ограничения)
          <input inputMode="numeric" value={form.traffic_limit_gb} onChange={(e) => set({traffic_limit_gb: e.target.value})} />
        </label>
        <label className="field">Устройств (пусто — без ограничения)
          <input inputMode="numeric" value={form.device_limit} onChange={(e) => set({device_limit: e.target.value})} />
        </label>
        <label className="field">Мест в семейной подписке (0 — без семьи)
          <input inputMode="numeric" value={form.family_seats ?? "0"} onChange={(e) => set({family_seats: e.target.value})} />
        </label>
        <label className="field">Профиль Remnawave (Internal Squad)
          {squads.length > 0 ? (
            <select value={known || !form.remnawave_profile_id ? form.remnawave_profile_id : "__typed"} onChange={(e) => set({remnawave_profile_id: e.target.value === "__typed" ? form.remnawave_profile_id : e.target.value})}>
              <option value="">— не выбран —</option>
              {squads.map((s) => (
                <option key={s.uuid} value={s.uuid}>
                  {s.name}
                  {s.inbounds != null ? ` · инбаундов: ${s.inbounds}` : ""}
                </option>
              ))}
              {!known && form.remnawave_profile_id && <option value="__typed">{form.remnawave_profile_id} (нет в панели)</option>}
            </select>
          ) : (
            <input maxLength={255} value={form.remnawave_profile_id} onChange={(e) => set({remnawave_profile_id: e.target.value})} placeholder="UUID из Remnawave → Internal Squads" />
          )}
        </label>
        <label className="field checkbox">
          В продаже
          <input type="checkbox" checked={form.enabled} onChange={(e) => set({enabled: e.target.checked})} />
        </label>
      </div>
      {squadError && <p className="muted">Список профилей из Remnawave не получен ({squadError}) — вставьте UUID вручную.</p>}
      <div className="inline">
        <button className="primary" type="submit" disabled={busy}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel}>
            Отмена
          </button>
        )}
      </div>
    </form>
  );
}

/** Fixed plans: create, edit, hide and delete, with the Remnawave squad each plan grants. */
export function PlansEditor({data, request, reload, toast}: {data: Plan[]; request: RequestFn; reload: () => void; toast: (m: string) => void}) {
  const plans = Array.isArray(data) ? data : [];
  const [squads, setSquads] = useState<Squad[]>([]);
  const [squadError, setSquadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState(0);

  async function loadSquads() {
    try {
      const result = await request("/api/admin/remnawave/internal-squads");
      setSquads(result.squads || []);
      setSquadError(result.error || null);
    } catch (e: any) {
      setSquadError(e.message || "ошибка запроса");
    }
  }
  useEffect(() => { void loadSquads(); }, []);

  const unmapped = useMemo(() => plans.filter((p) => p.enabled && !p.remnawave_profile_id), [plans]);
  const squadName = (uuid: string | null) => (uuid ? squads.find((s) => s.uuid === uuid)?.name || uuid : null);

  async function save(form: Form, id?: number) {
    const {body, error: invalid} = planBody(form);
    if (!body) {
      setError(invalid || "Проверьте поля");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await request(id ? `/api/admin/plans/${id}` : "/api/admin/plans", {method: id ? "PUT" : "POST", body: JSON.stringify(body)});
      toast(id ? "Тариф сохранён" : "Тариф создан");
      setEditing(null);
      if (!id) setCreated((n) => n + 1);
      reload();
    } catch (e: any) {
      setError(e.message || "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(plan: Plan) {
    try {
      await request(`/api/admin/plans/${plan.id}/enabled`, {method: "POST", body: JSON.stringify({enabled: !plan.enabled})});
      toast(plan.enabled ? "Тариф снят с продажи" : "Тариф снова в продаже");
      reload();
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function remove(plan: Plan) {
    if (!window.confirm(`Удалить тариф «${plan.name}»? Тариф с продажами удалить нельзя — его можно только снять с продажи.`)) return;
    try {
      await request(`/api/admin/plans/${plan.id}`, {method: "DELETE"});
      toast("Тариф удалён");
      reload();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <>
      <div className="card">
        <h3>Новый тариф</h3>
        <p className="muted">
          Тариф сразу появляется в боте, кабинете и Mini App, если он в продаже. Профиль Remnawave (Internal Squad) определяет, к каким серверам и протоколам клиент получит доступ: без него подписка создаётся без серверов. Изменение тарифа не меняет условия уже оплаченных заказов.
        </p>
        <PlanForm key={created} initial={EMPTY} squads={squads} squadError={squadError} busy={busy} onSubmit={(f) => save(f)} submitLabel="Создать тариф" />
        {error && <p className="error" role="alert">{error}</p>}
      </div>
      {unmapped.length > 0 && (
        <div className="card plan-warning" role="status">
          <TriangleAlert aria-hidden="true" /> Без профиля Remnawave: {unmapped.map((p) => p.name).join(", ")}. Клиент такого тарифа не подключится ни к одному серверу — выберите профиль.
        </div>
      )}
      <div className="inline">
        <button type="button" className="secondary" onClick={() => { void loadSquads(); reload(); }}>
          <RefreshCw aria-hidden="true" /> Обновить профили Remnawave
        </button>
      </div>
      {plans.length ? (
        <div className="plan-grid">
          {plans.map((plan) => (
            <div className="plan card" key={plan.id} data-plan-id={plan.id}>
              {editing === plan.id ? (
                <PlanForm initial={toForm(plan)} squads={squads} squadError={squadError} busy={busy} onSubmit={(f) => save(f, plan.id)} onCancel={() => setEditing(null)} submitLabel="Сохранить" />
              ) : (
                <>
                  <div className="plan-head">
                    <h3>{plan.name}</h3>
                    <StatusBadge tone={plan.enabled ? "ok" : "idle"}>{plan.enabled ? "В продаже" : "Скрыт"}</StatusBadge>
                  </div>
                  <div className="price">
                    {plan.price} <small>₽</small>
                  </div>
                  <p className="muted">
                    {durationLabel(plan.duration_days)} · {plan.traffic_limit_gb ? `${plan.traffic_limit_gb} ГБ` : "трафик без ограничения"} · {plan.device_limit ? `устройств: ${plan.device_limit}` : "устройства без ограничения"}{plan.family_seats ? ` · семья: +${plan.family_seats}` : ""} · ID {plan.id}
                  </p>
                  <p className={plan.remnawave_profile_id ? "muted" : "error"}>Профиль Remnawave: {squadName(plan.remnawave_profile_id) || "не выбран"}</p>
                  <div className="inline">
                    <button type="button" className="secondary" onClick={() => setEditing(plan.id)}>
                      <Pencil aria-hidden="true" /> Изменить
                    </button>
                    <button type="button" className="secondary" onClick={() => toggle(plan)}>
                      {plan.enabled ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />} {plan.enabled ? "Снять с продажи" : "Вернуть в продажу"}
                    </button>
                    <button type="button" className="danger" onClick={() => remove(plan)}>
                      <Trash2 aria-hidden="true" /> Удалить
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="card empty-state">
          <h3>Тарифов пока нет</h3>
          <p>
            <Plus aria-hidden="true" /> Создайте первый тариф формой выше — он сразу появится в боте, кабинете и Mini App.
          </p>
        </div>
      )}
    </>
  );
}
