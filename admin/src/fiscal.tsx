import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const when = (v?: string | null) => (v ? new Date(v).toLocaleString() : "—");
const STATUS: Record<string, string> = {queued: "в очереди", sent: "отправлен, ждём ответ", retry: "повтор", failed: "ошибка", done: "сформирован"};

/** «Тарифы и оплата → Чеки в налоговую»: «Мой налог», АТОЛ Онлайн or ЮKassa receipts for every payment. */
export function FiscalReceipts({d, request, reload, toast}: {d: any; request: Request; reload: () => void; toast: (m: string) => void}) {
  const [form, setForm] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState("");
  useEffect(() => { if (d?.config) setForm({...d.config, providers_text: (d.config.providers || []).join(", ")}); }, [d]);
  if (!d?.config || !form) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const set = (k: string, v: any) => setForm((f: any) => ({...f, [k]: v}));
  const field = (k: string, label: string, props: any = {}) => <label>{label}<input value={form[k] ?? ""} onChange={(e) => set(k, e.target.value)} {...props}/></label>;
  const secret = (k: string, label: string) => <label>{label}{form[k + "_set"] && <span className="muted"> · сохранён</span>}
    <input type="password" autoComplete="new-password" value={form[k] ?? ""} placeholder={form[k + "_set"] ? "оставьте пустым, чтобы не менять" : ""} onChange={(e) => set(k, e.target.value)}/></label>;
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try {
      const {providers_text, ...rest} = form;
      const body = {...rest, providers: String(providers_text || "").split(",").map((s: string) => s.trim()).filter(Boolean)};
      for (const k of Object.keys(body)) if (k.endsWith("_set")) delete body[k];
      await request("/api/admin/fiscal", {method: "PUT", body: JSON.stringify(body)});
      toast("Настройки чеков сохранены"); reload();
    } catch (err: any) { toast(err?.message || "Не удалось сохранить"); }
    finally { setBusy(false); }
  }
  async function test() {
    setCheck("Проверяем…");
    try { const r = await request("/api/admin/fiscal/test", {method: "POST"}); setCheck((r.ok ? "✅ " : "⚠️ ") + r.message); }
    catch (err: any) { setCheck("⚠️ " + (err?.message || "Нет связи")); }
  }
  async function retry(id: number) {
    try { const r = await request(`/api/admin/fiscal/receipts/${id}/retry`, {method: "POST"}); toast(`Чек #${id}: ${STATUS[r.status] || r.status}`); reload(); }
    catch (err: any) { toast(err?.message || "Не удалось"); }
  }
  const mode = form.mode;
  return <div className="stack" data-fiscal>
    <div className="kpis">
      {["done", "sent", "retry", "failed"].map((k) => <div className="card kpi" key={k}><span>{STATUS[k]}</span><b>{d.counts?.[k] || 0}</b></div>)}
    </div>
    <form className="card stack" onSubmit={save}>
      <h3>Чеки в налоговую</h3>
      <p className="muted">После каждой оплаты магазин сам формирует чек: самозанятому — в «Мой налог», ИП и ООО — через онлайн-кассу (АТОЛ Онлайн или «Чеки от ЮKassa»). При возврате денег чек аннулируется или формируется «возврат прихода». Чеки создаются только для оплат после включения; оплаты с баланса не дублируются — чек уже был при пополнении.</p>
      <label>Способ<select aria-label="Способ" value={mode} onChange={(e) => set("mode", e.target.value)}>
        {Object.entries(d.modes).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
      {mode !== "off" && <>
        {field("service_name", "Название услуги в чеке ({plan} — тариф, {days} — дней)")}
        {field("topup_name", "Название при пополнении баланса")}
        <label>Платёжные системы, для которых нужен чек<input value={form.providers_text} onChange={(e) => set("providers_text", e.target.value)} placeholder="yookassa, platega, rollypay"/></label>
        <label className="check"><input type="checkbox" checked={!!form.refunds} onChange={(e) => set("refunds", e.target.checked)}/> Чек при возврате</label>
      </>}
      {mode === "npd" && <fieldset className="stack"><legend>«Мой налог»</legend>
        <p className="muted">Вход в личный кабинет самозанятого lknpd.nalog.ru: ИНН (12 цифр) и пароль от него. Чек уходит в ФНС от имени самозанятого; покупатель — физическое лицо.</p>
        {field("npd_inn", "ИНН самозанятого", {inputMode: "numeric", maxLength: 12})}
        {secret("npd_password", "Пароль «Мой налог»")}
      </fieldset>}
      {(mode === "atol" || mode === "yookassa") && <fieldset className="stack"><legend>Реквизиты продавца (54-ФЗ)</legend>
        {field("inn", "ИНН продавца", {inputMode: "numeric", maxLength: 12})}
        <label>Система налогообложения<select aria-label="Система налогообложения" value={form.taxation} onChange={(e) => set("taxation", e.target.value)}>
          {Object.entries(d.taxation).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>НДС<select aria-label="НДС" value={form.vat} onChange={(e) => set("vat", e.target.value)}>
          {Object.entries(d.vat).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        {field("company_email", "E-mail продавца")}
        {field("payment_address", "Адрес сайта (место расчётов)", {placeholder: "https://shop.example.com"})}
        {field("fallback_email", "E-mail для чека, если у клиента нет подтверждённой почты")}
      </fieldset>}
      {mode === "atol" && <fieldset className="stack"><legend>АТОЛ Онлайн</legend>
        {field("atol_login", "Логин")}{secret("atol_password", "Пароль")}{field("atol_group", "Код группы ККТ")}{field("atol_api", "Адрес API")}
      </fieldset>}
      {mode === "yookassa" && <fieldset className="stack"><legend>ЮKassa</legend>
        <p className="muted">Включите «Чеки от ЮKassa» в личном кабинете ЮKassa. Пустые поля — ключи магазина из настроек оплаты.</p>
        {field("yookassa_shop_id", "shopId")}{secret("yookassa_secret_key", "Секретный ключ")}
      </fieldset>}
      <div className="row">
        <button className="primary" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить"}</button>
        {d.config.mode !== "off" && <button type="button" onClick={test}>Проверить подключение</button>}
      </div>
      {check && <p role="status">{check}</p>}
    </form>
    <div className="card">
      <h3>Журнал чеков</h3>
      {(d.items || []).length === 0 ? <p className="muted">Чеков ещё нет.</p> :
        <table><thead><tr><th>#</th><th>Платёж</th><th>Тип</th><th>Сумма</th><th>Статус</th><th>Чек</th><th>Обновлён</th><th/></tr></thead>
          <tbody>{d.items.map((r: any) => <tr key={r.id} data-receipt={r.id}>
            <td>{r.id}</td><td>{r.payment_id}</td><td>{r.kind === "income" ? "приход" : "возврат"} · {r.provider}</td><td>{r.amount}</td>
            <td>{STATUS[r.status] || r.status}{r.last_error ? <><br/><span className="muted">{r.last_error}</span></> : null}</td>
            <td>{r.receipt_url ? <a href={r.receipt_url} target="_blank" rel="noreferrer">открыть</a> : (r.external_id || "—")}</td>
            <td>{when(r.updated_at)}</td>
            <td>{r.status !== "done" && <button onClick={() => retry(r.id)}>Повторить</button>}</td></tr>)}</tbody></table>}
    </div>
  </div>;
}
