import React, {useEffect, useState} from "react";

/** v28.48 «Компании»: корпоративные тарифы — реквизиты, места, пул устройств, счета и их оплата. */
type Request = (path: string, options?: RequestInit) => Promise<any>;
const EMPTY = {name: "", inn: "", kpp: "", legal_address: "", contact_email: "", country: "RU", plan_id: 0, seats: 5, devices_per_seat: 2, seat_price: "300", enabled: true, admin_user_id: ""};

export function CorporateAdmin({request, toast, api}: {request: Request; toast: (t: string) => void; api: string}) {
  const [d, setD] = useState<any>(null);
  const [plans, setPlans] = useState<any[]>([]);
  const [form, setForm] = useState<any>(null);
  const [months, setMonths] = useState(1);
  const [seller, setSeller] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/corporate").then((r: any) => { setD(r); setSeller(r.seller); }).catch(e => setError(e.message));
  useEffect(() => { load(); request("/api/plans").then(setPlans).catch(() => setPlans([])); }, [request]);
  async function act(fn: () => Promise<any>, ok: string) { setError(""); try { await fn(); toast(ok); await load(); } catch (e: any) { setError(e.message); } }
  const body = (f: any) => JSON.stringify({...f, plan_id: Number(f.plan_id), seats: Number(f.seats), devices_per_seat: Number(f.devices_per_seat),
    seat_price: String(f.seat_price), admin_user_id: f.admin_user_id ? Number(f.admin_user_id) : null, contact_email: f.contact_email || null});
  const field = (k: string, label: string, type = "text") => <label>{label}<input type={type} value={form[k] ?? ""} onChange={e => setForm({...form, [k]: e.target.value})}/></label>;
  return (
    <div className="card">
      <div className="toolbar"><h3>Компании (корпоративные тарифы)</h3><button onClick={() => setForm({...EMPTY, plan_id: plans[0]?.id || 0})}>Новая компания</button></div>
      <p className="muted">Компания покупает места на одном тарифе. Её администратор приглашает сотрудников по ссылке и распределяет устройства из пула. Оплата — по счёту: когда деньги пришли, отметьте счёт оплаченным, и доступ всех сотрудников продлится.</p>
      {error ? <p className="error">{error}</p> : null}
      {form ? <div className="card">
        <div className="toolbar">{field("name", "Название")}{field("inn", "ИНН")}{field("kpp", "КПП")}{field("contact_email", "E-mail")}</div>
        <div className="toolbar">{field("legal_address", "Юридический адрес")}
          <label>Тариф<select value={form.plan_id} onChange={e => setForm({...form, plan_id: Number(e.target.value)})}>{plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          {field("seats", "Мест", "number")}{field("devices_per_seat", "Устройств на место", "number")}{field("seat_price", "Цена места в месяц", "number")}{field("admin_user_id", "ID клиента-администратора", "number")}
          <label><input type="checkbox" checked={!!form.enabled} onChange={e => setForm({...form, enabled: e.target.checked})}/> Активна</label>
        </div>
        <div className="toolbar"><button className="primary" onClick={() => act(() => request(form.id ? `/api/admin/corporate/${form.id}` : "/api/admin/corporate", {method: form.id ? "PUT" : "POST", body: body(form)}).then(() => setForm(null)), "Компания сохранена")}>Сохранить</button><button onClick={() => setForm(null)}>Отмена</button></div>
      </div> : null}
      {!d ? <p>Загрузка…</p> : d.companies.length === 0 ? <p className="muted">Компаний пока нет.</p> : (
        <table className="table"><thead><tr><th>Компания</th><th>Тариф</th><th>Места</th><th>Оплачено до</th><th>Счета</th><th></th></tr></thead>
          <tbody>{d.companies.map((c: any) => (
            <tr key={c.id}>
              <td><b>{c.name}</b><div className="muted">ИНН {c.inn || "—"} · код {c.invite_code}</div></td>
              <td>{c.plan || "—"}</td><td>{c.seats_used}/{c.seats} · {c.device_pool} устр.</td>
              <td>{c.paid_until ? c.paid_until.slice(0, 10) : "не оплачено"}{c.active ? "" : " ⏸"}</td>
              <td>{c.invoices.map((i: any) => <div key={i.id}>
                <a href={`${api}/api/admin/corporate/invoices/${i.id}.html`} target="_blank" rel="noopener">№ {i.number}</a> · {i.amount} · {i.status === "paid" ? "оплачен" : i.status === "cancelled" ? "отменён" : "ждёт оплаты"}
                {i.status === "issued" ? <> <button onClick={() => confirm(`Деньги по счёту ${i.number} пришли?`) && act(() => request(`/api/admin/corporate/invoices/${i.id}/paid`, {method: "POST"}), "Счёт оплачен, доступ продлён")}>Оплачен</button>
                  <button onClick={() => act(() => request(`/api/admin/corporate/invoices/${i.id}/cancel`, {method: "POST"}), "Счёт отменён")}>Отменить</button></> : null}
              </div>)}</td>
              <td><button onClick={() => setForm({...EMPTY, ...c, seat_price: c.seat_price, admin_user_id: ""})}>Изменить</button>
                <label>Мес.<input type="number" min={1} max={36} value={months} style={{width: 56}} onChange={e => setMonths(Number(e.target.value))}/></label>
                <button onClick={() => act(() => request(`/api/admin/corporate/${c.id}/invoices`, {method: "POST", body: JSON.stringify({months})}), "Счёт выставлен")}>Выставить счёт</button></td>
            </tr>))}</tbody>
        </table>)}
      {seller ? <details><summary>Реквизиты продавца для счетов</summary>
        <div className="toolbar">{(["name", "inn", "kpp", "address", "bank", "bik", "account", "corr_account"] as const).map(k => (
          <label key={k}>{({name: "Название", inn: "ИНН", kpp: "КПП", address: "Адрес", bank: "Банк", bik: "БИК", account: "Расчётный счёт", corr_account: "Корр. счёт"} as any)[k]}
            <input value={seller[k] || ""} onChange={e => setSeller({...seller, [k]: e.target.value})}/></label>))}
          <button className="primary" onClick={() => act(() => request("/api/admin/corporate-seller", {method: "PUT", body: JSON.stringify(seller)}), "Реквизиты сохранены")}>Сохранить</button></div>
      </details> : null}
    </div>
  );
}
