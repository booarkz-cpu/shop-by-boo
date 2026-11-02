import React, {useEffect, useState} from "react";
import {LoadState, SuccessNote} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const NAMES = ["Lucy Mini", "Lucy Max", "Lucy Ultra"];
// The section reloads after a save (the plan list above must show the new plans) and mounts this card again;
// the result line survives that one remount.
let lastSaved = {line: "", at: 0};

/** «Тарифы → Тарифы Lucy» (v28.63.0, stage 8): creates or updates Lucy Mini (trial, 1 device), Lucy Max (2 devices,
 *  no traffic limit) and Lucy Ultra (4 devices, cheaper per device). Prices are the owner's; the API checks that
 *  Ultra is the better deal. Device and traffic limits are enforced by Remnawave (hwidDeviceLimit, trafficLimitBytes). */
export function LucyPlans({request, reload}: {request: Request; reload: () => void}) {
  const [state, setState] = useState<any>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(() => { const x = Date.now() - lastSaved.at < 10000 ? lastSaved.line : ""; lastSaved = {line: "", at: 0}; return x; });
  const [form, setForm] = useState({max_price: "", ultra_price: "", duration_days: "30", trial_days: "3", trial_traffic_gb: "", remnawave_profile_id: ""});
  const load = () => {
    setError("");
    request("/api/admin/lucy-plans").then(x => {
      setState(x);
      const max = x.plans["Lucy Max"], ultra = x.plans["Lucy Ultra"], mini = x.plans["Lucy Mini"];
      setForm(f => ({...f, max_price: max?.price || f.max_price, ultra_price: ultra?.price || f.ultra_price,
        duration_days: String(max?.duration_days || f.duration_days), trial_days: String(mini?.duration_days || f.trial_days),
        trial_traffic_gb: mini?.traffic_limit_gb ? String(mini.traffic_limit_gb) : f.trial_traffic_gb,
        remnawave_profile_id: max?.remnawave_profile_id || f.remnawave_profile_id}));
    }).catch((e: any) => setError(e.message));
  };
  useEffect(load, []);
  const set = (k: string) => (e: any) => setForm({...form, [k]: e.target.value});
  async function apply(e: React.FormEvent) {
    e.preventDefault(); setError(""); setSaved("");
    try {
      const out = await request("/api/admin/lucy-plans", {method: "POST", body: JSON.stringify({
        max_price: form.max_price, ultra_price: form.ultra_price, duration_days: Number(form.duration_days), trial_days: Number(form.trial_days),
        trial_traffic_gb: form.trial_traffic_gb ? Number(form.trial_traffic_gb) : null, remnawave_profile_id: form.remnawave_profile_id || null})});
      setState(out);
      const line = NAMES.map(n => `${n}: ${out.result[n] === "created" ? "создан" : "обновлён"}`).join(" · ");
      setSaved(line); lastSaved = {line, at: Date.now()};
      reload();
    } catch (err: any) { setError(err.message); }
  }
  if (!state) return <LoadState error={error} onRetry={load} label="Загрузка тарифов Lucy…"/>;
  const perDevice = (p: string, n: number) => Number(p) > 0 ? (Number(p) / n).toFixed(2) : "—";
  return <div className="card" data-lucy-plans>
    <h3>Тарифы Lucy</h3>
    <p className="muted">Lucy Mini — пробный: 1 устройство, не продаётся, пробный период выдаётся только на нём. Lucy Max — 2 устройства, Lucy Ultra — 4; трафик без лимита.
      Лимит устройств выполняет Remnawave, если в панели включён HWID-лимит (HWID_DEVICE_LIMIT_ENABLED); безлимитный трафик — если узлы его не ограничивают.</p>
    <div className="table-wrap"><table>
      <thead><tr><th>Тариф</th><th>Есть в магазине</th><th>Цена</th><th>Дней</th><th>Устройств</th><th>Трафик</th><th>В продаже</th></tr></thead>
      <tbody>{NAMES.map(n => { const p = state.plans[n]; return <tr key={n} data-plan={n}>
        <td><b>{n}</b>{n === "Lucy Mini" && state.trial_is_mini && <div className="muted">пробный тариф</div>}</td>
        <td>{p ? `№${p.id}` : "нет"}</td><td>{p?.price ?? "—"}</td><td>{p?.duration_days ?? "—"}</td><td>{p?.device_limit ?? "—"}</td>
        <td>{p ? (p.traffic_limit_gb ? `${p.traffic_limit_gb} ГБ` : "без лимита") : "—"}</td><td>{p ? (p.enabled ? "да" : "нет") : "—"}</td>
      </tr>; })}</tbody>
    </table></div>
    <form className="filters" onSubmit={apply}>
      <label className="field">Цена Lucy Max<input required inputMode="decimal" value={form.max_price} onChange={set("max_price")}/></label>
      <label className="field">Цена Lucy Ultra<input required inputMode="decimal" value={form.ultra_price} onChange={set("ultra_price")}/></label>
      <label className="field">Срок Max и Ultra, дней<input required type="number" min={1} max={3650} value={form.duration_days} onChange={set("duration_days")}/></label>
      <label className="field">Пробный период, дней<input required type="number" min={1} max={30} value={form.trial_days} onChange={set("trial_days")}/></label>
      <label className="field">Трафик пробного, ГБ (пусто — без лимита)<input type="number" min={1} value={form.trial_traffic_gb} onChange={set("trial_traffic_gb")}/></label>
      <label className="field">Внутренний сквад Remnawave (UUID, необязательно)<input value={form.remnawave_profile_id} onChange={set("remnawave_profile_id")} maxLength={255}/></label>
      <button className="primary">{NAMES.some(n => state.plans[n]) ? "Обновить тарифы Lucy" : "Создать тарифы Lucy"}</button>
    </form>
    <p className="muted">За устройство: Max — {perDevice(form.max_price, 2)}, Ultra — {perDevice(form.ultra_price, 4)}. Ultra должен быть дешевле за устройство.
      Оплаченные подписки сохраняют лимиты, с которыми их купили; новые условия действуют с новых оплат.</p>
    {error && <div role="alert" className="error">{error}</div>}
    {saved && <SuccessNote>{saved}</SuccessNote>}
    {state.trial_plan_id && <button type="button" onClick={async () => { if (!window.confirm("Разрешить пробный период на любом тарифе в продаже?")) return;
      try { await request("/api/admin/lucy-plans/trial", {method: "DELETE"}); load(); } catch (err: any) { setError(err.message); } }}>Пробный период на любом тарифе</button>}
  </div>;
}
