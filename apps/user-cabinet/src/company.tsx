import React, {useEffect, useState} from "react";

/** v28.48 «Компания»: корпоративный тариф — сотрудник видит свой доступ, администратор управляет местами, устройствами и счетами. */
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Flash = (text: string, error?: boolean) => void;

export function companyCodeFromUrl(search = typeof location === "undefined" ? "" : location.search): string {
  const params = new URLSearchParams(search);
  const raw = params.get("company") || (params.get("tgWebAppStartParam") || params.get("startapp") || "").replace(/^company_/, "");
  return /^[A-Za-z0-9]{6,32}$/.test(raw) && (params.get("company") || /^company_/.test(params.get("tgWebAppStartParam") || params.get("startapp") || "")) ? raw : "";
}

const day = (v?: string | null) => (v ? new Date(v + (String(v).endsWith("Z") ? "" : "Z")).toLocaleDateString() : "—");

export function CompanySection({request, flash, api, reload}: {request: Request; flash: Flash; api: string; reload?: () => Promise<void> | void}) {
  const [d, setD] = useState<any>(null);
  const [code, setCode] = useState(companyCodeFromUrl());
  const [busy, setBusy] = useState(false);
  const load = () => request("/api/me/company").then(setD).catch((e: any) => flash(e.message, true));
  useEffect(() => { load(); }, []);
  async function act(fn: () => Promise<any>, ok: string) {
    if (busy) return;
    setBusy(true);
    try { await fn(); flash(ok); await load(); await reload?.(); } catch (e: any) { flash(e.message || "Ошибка", true); } finally { setBusy(false); }
  }
  if (!d) return <p role="status">Загрузка…</p>;
  if (!d.member || (d.role === "admin" && !d.joined && code)) {
    return <section className="company-section">
      <h2 className="section-title">Компания</h2>
      <p>Если работодатель подключил корпоративный VPN, откройте ссылку-приглашение или введите код.</p>
      <form className="workspace-form" onSubmit={(e) => { e.preventDefault(); act(() => request("/api/me/company/join", {method: "POST", body: JSON.stringify({code: code.trim()})}), "Вы в компании — доступ подключается"); }}>
        <label className="field">Код приглашения<input value={code} maxLength={32} onChange={(e) => setCode(e.target.value)} /></label>
        <button className="btn-primary" disabled={busy || code.trim().length < 6}>Присоединиться</button>
      </form>
    </section>;
  }
  const c = d.company;
  const admin = d.role === "admin";
  return <section className="company-section">
    <h2 className="section-title">{c.name}</h2>
    <div className="form-card">
      <p>Тариф: <b>{c.plan || "—"}</b> · оплачено до <b>{day(c.paid_until)}</b>{c.active ? "" : " — доступ приостановлен до оплаты"}</p>
      <p>Места: {c.seats_used} из {c.seats}{admin ? ` · устройства: ${d.devices_used} из ${c.device_pool}` : ` · ваши устройства: ${d.my_devices}`}</p>
      {!admin && !d.has_seat && <p className="section-sub">Все места заняты: доступ появится, когда администратор добавит места.</p>}
      {admin && !d.joined && <button className="btn-ghost" disabled={busy} onClick={() => act(() => request("/api/me/company/join", {method: "POST", body: JSON.stringify({code: c.invite_code})}), "Ваш доступ подключается")}>Подключить VPN и мне</button>}
      {!admin && <button className="btn-ghost" disabled={busy} onClick={() => confirm("Выйти из компании? Доступ по корпоративному тарифу закончится.") && act(() => request(`/api/me/company/members/${d.member_id ?? ""}`, {method: "DELETE"}), "Вы вышли из компании")}>Выйти из компании</button>}
    </div>
    {admin && <>
      <div className="form-card">
        <h3>Приглашение</h3>
        <p className="section-sub">Отправьте ссылку сотрудникам: по ней они присоединятся и получат свой доступ.</p>
        <code className="copyable">{d.invite_link}</code>
        <div className="toolbar">
          <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText(d.invite_link).then(() => flash("Ссылка скопирована"))}>Скопировать</button>
          <button className="btn-ghost" disabled={busy} onClick={() => act(() => request("/api/me/company/invite", {method: "POST"}), "Ссылка обновлена, старая больше не работает")}>Новая ссылка</button>
        </div>
      </div>
      <div className="form-card">
        <h3>Сотрудники</h3>
        <table className="table"><thead><tr><th>Сотрудник</th><th>Устройств</th><th>Место</th><th></th></tr></thead><tbody>
          {(d.members || []).map((m: any) => <tr key={m.id}>
            <td>{m.name}{m.role === "admin" ? " · администратор" : ""}</td>
            <td><input type="number" min={1} max={50} defaultValue={m.devices} style={{width: 64}} onBlur={(e) => Number(e.target.value) !== m.devices && act(() => request(`/api/me/company/members/${m.id}`, {method: "PUT", body: JSON.stringify({devices: Number(e.target.value)})}), "Устройства сохранены")} /></td>
            <td>{m.seated ? "есть" : m.role === "admin" ? "—" : "ждёт места"}</td>
            <td>{m.role !== "admin" && <button className="btn-ghost" disabled={busy} onClick={() => confirm("Убрать сотрудника из компании?") && act(() => request(`/api/me/company/members/${m.id}`, {method: "DELETE"}), "Сотрудник убран")}>Убрать</button>}</td>
          </tr>)}
        </tbody></table>
      </div>
      <div className="form-card">
        <h3>Счета</h3>
        {(d.invoices || []).length === 0 ? <p className="section-sub">Счетов пока нет — их выставляет магазин.</p> :
          <ul>{d.invoices.map((i: any) => <li key={i.id}><a href={`${api}/api/me/company/invoices/${i.id}.html`} target="_blank" rel="noopener">Счёт № {i.number}</a> · {i.amount} {i.currency} · {i.status === "paid" ? "оплачен" : i.status === "cancelled" ? "отменён" : "ожидает оплаты"}</li>)}</ul>}
      </div>
    </>}
  </section>;
}
