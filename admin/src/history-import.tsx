import React, {useEffect, useState} from "react";
import {SelectField} from "./components/select-field";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
const ROOT = "/api/admin/customer-operations/history";
const ROW_STATUS: Record<string, string> = {new: "Будет перенесено", already_imported: "Уже перенесено", conflict: "Конфликт данных", blocked: "Заблокировано"};
const JOB_STATUS: Record<string, string> = {preview: "Ожидает применения", applied: "Применён", cancelled: "Отменён", expired: "Истёк", rolled_back: "Откатан"};
const CHECK: Record<string, string> = {payments_count: "Количество платежей", payments_total: "Сумма успешных платежей", subscriptions_count: "Количество подписок"};

const EMPTY_PAYMENTS = {table: "payments", id: "", user: "", amount: "", amount_unit: "decimal", currency: "", status: "", paid_at: "", description: ""};
const EMPTY_SUBSCRIPTIONS = {table: "subscriptions", user: "", expires_at: "", remnawave_uuid: "", subscription_url: "", plan: "", traffic_gb: "", devices: ""};

function guess(columns: string[], ...names: string[]) {
  return names.find((name) => columns.includes(name)) || "";
}

/** Versioned import of subscriptions and payments from another shop with reconciliation and rollback. */
export function HistoryImport({request, currency}: {request: RequestFn; currency: string}) {
  const [file, setFile] = useState<File | null>(null);
  const [namespace, setNamespace] = useState("old-bot");
  const [usePayments, setUsePayments] = useState(true);
  const [useSubscriptions, setUseSubscriptions] = useState(true);
  const [payments, setPayments] = useState<Record<string, string>>(EMPTY_PAYMENTS);
  const [subscriptions, setSubscriptions] = useState<Record<string, string>>(EMPTY_SUBSCRIPTIONS);
  const [paymentColumns, setPaymentColumns] = useState<string[]>([]);
  const [subscriptionColumns, setSubscriptionColumns] = useState<string[]>([]);
  const [control, setControl] = useState({payments_count: "", payments_total: "", subscriptions_count: ""});
  const [plans, setPlans] = useState<any[]>([]);
  const [defaultPlan, setDefaultPlan] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [accepted, setAccepted] = useState(false);
  const [jobs, setJobs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const failure = (e: any) => setError(e.status === 403 ? "Раздел доступен только администратору." : e.message || "Не удалось выполнить действие");
  const reset = () => {
    setPreview(null);
    setAccepted(false);
  };
  async function refresh() {
    try {
      setJobs(await request(ROOT));
    } catch (e) {
      failure(e);
    }
  }
  useEffect(() => {
    refresh();
    request("/api/admin/plans").then((rows) => setPlans(Array.isArray(rows) ? rows : [])).catch(() => setPlans([]));
  }, []);

  async function inspect(kind: "payments" | "subscriptions") {
    if (!file) return;
    setBusy(true);
    setError("");
    reset();
    try {
      const data = new FormData();
      data.append("file", file);
      data.append("table", kind === "payments" ? payments.table : subscriptions.table);
      const schema = await request(ROOT + "/inspect", {method: "POST", body: data});
      const cols: string[] = schema.columns;
      if (kind === "payments") {
        setPaymentColumns(cols);
        setPayments((old) => ({...old, id: guess(cols, "id", "payment_id"), user: guess(cols, "user_id", "customer_id", "telegram_id"), amount: guess(cols, "amount", "sum", "price"), status: guess(cols, "status", "state"), paid_at: guess(cols, "paid_at", "created_at", "created", "date"), currency: guess(cols, "currency")}));
      } else {
        setSubscriptionColumns(cols);
        setSubscriptions((old) => ({...old, user: guess(cols, "user_id", "customer_id", "telegram_id"), expires_at: guess(cols, "expires_at", "expire_at", "end_date", "expires"), remnawave_uuid: guess(cols, "remnawave_uuid", "uuid", "panel_uuid"), subscription_url: guess(cols, "subscription_url", "sub_url", "url"), plan: guess(cols, "plan", "tariff", "plan_name"), traffic_gb: guess(cols, "traffic_gb", "traffic_limit_gb"), devices: guess(cols, "devices", "device_limit")}));
      }
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }

  function payload() {
    const optional = (value: string) => value || null;
    return {
      adapter: "generic-sqlite-v1",
      namespace,
      currency,
      default_plan_id: defaultPlan ? Number(defaultPlan) : null,
      payments: usePayments ? {...payments, currency: optional(payments.currency), status: optional(payments.status), paid_at: optional(payments.paid_at), description: optional(payments.description)} : null,
      subscriptions: useSubscriptions ? {...subscriptions, subscription_url: optional(subscriptions.subscription_url), plan: optional(subscriptions.plan), traffic_gb: optional(subscriptions.traffic_gb), devices: optional(subscriptions.devices)} : null,
      control: {
        payments_count: usePayments ? Number(control.payments_count) : null,
        payments_total: usePayments ? control.payments_total : null,
        subscriptions_count: useSubscriptions ? Number(control.subscriptions_count) : null,
      },
    };
  }

  async function makePreview() {
    if (!file) return;
    setBusy(true);
    setError("");
    setNotice("");
    reset();
    try {
      const data = new FormData();
      data.append("file", file);
      data.append("mapping", JSON.stringify(payload()));
      setPreview(await request(ROOT + "/preview", {method: "POST", body: data}));
      refresh();
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!preview || !accepted) return;
    setBusy(true);
    setError("");
    try {
      const r = await request(`${ROOT}/${preview.id}/apply`, {method: "POST", body: JSON.stringify({fingerprint: preview.fingerprint})});
      setNotice(`Перенос применён: платежей ${r.payments_created}, подписок ${r.subscriptions_created}; уже были перенесены: ${r.payments_already_imported} / ${r.subscriptions_already_imported}.`);
      reset();
      refresh();
    } catch (e: any) {
      failure(e);
      if (e.status === 409) reset();
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!preview) return;
    setBusy(true);
    try {
      await request(`${ROOT}/${preview.id}/cancel`, {method: "POST"});
      reset();
      refresh();
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }

  async function rollback(job: any) {
    const reason = window.prompt("Причина отката переноса (минимум 3 символа)");
    if (!reason || reason.trim().length < 3) return;
    setBusy(true);
    setError("");
    try {
      const r = await request(`${ROOT}/${job.id}/rollback`, {method: "POST", body: JSON.stringify({reason: reason.trim()})});
      setNotice(`Перенос откатан: удалено платежей ${r.payments_removed}, подписок ${r.subscriptions_removed}.`);
      refresh();
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }

  function select(kind: "payments" | "subscriptions", key: string, label: string, optional = false) {
    const cols = kind === "payments" ? paymentColumns : subscriptionColumns;
    const state = kind === "payments" ? payments : subscriptions;
    const set = kind === "payments" ? setPayments : setSubscriptions;
    return (
      <label key={key}>
        {label}
        <SelectField aria-label={label} disabled={busy} value={state[key]} onChange={(e) => { set((old) => ({...old, [key]: e.target.value})); reset(); }}>
          <option value="">{optional ? "Не переносить" : "Выберите поле"}</option>
          {cols.map((c) => <option key={c} value={c}>{c}</option>)}
        </SelectField>
      </label>
    );
  }

  const rows = preview ? [...preview.payments.rows.map((r: any) => ({...r, kind: "Платёж", key: r.source_id})), ...preview.subscriptions.rows.map((r: any) => ({...r, kind: "Подписка", key: r.remnawave_uuid}))] : [];
  const ready = !!file && (usePayments || useSubscriptions) && (!usePayments || (payments.id && payments.user && payments.amount && control.payments_count !== "" && control.payments_total !== "")) && (!useSubscriptions || (subscriptions.user && subscriptions.expires_at && subscriptions.remnawave_uuid && control.subscriptions_count !== ""));

  return (
    <section className="card history-import">
      <h2>Перенос подписок и платежей</h2>
      <p className="muted">Адаптер <code>generic-sqlite-v1</code>. Сначала перенесите профили с тем же именем источника. Платежи сохраняются как история: они не выдают доступ, не участвуют в выручке и возвратах. Подписки привязываются к существующим пользователям Remnawave по UUID.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="grid2">
        <div>
          <label>Выгрузка SQLite с подписками и платежами<input disabled={busy} type="file" accept=".db,.sqlite,.sqlite3" onChange={(e) => { setFile(e.target.files?.[0] || null); setPaymentColumns([]); setSubscriptionColumns([]); reset(); }} /></label>
          <label>Имя источника профилей<input disabled={busy} value={namespace} onChange={(e) => { setNamespace(e.target.value); reset(); }} /></label>
          <label>Тариф по умолчанию для подписок<SelectField aria-label="Тариф по умолчанию для подписок" disabled={busy} value={defaultPlan} onChange={(e) => { setDefaultPlan(e.target.value); reset(); }}><option value="">Только по названию тарифа</option>{plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</SelectField></label>
        </div>
        <div>
          <h3>Контрольные итоги из старой системы</h3>
          <p className="muted">Перенос применится, только если итоги совпадут с прочитанными строками.</p>
          {usePayments && <><label>Количество успешных и возвращённых платежей<input type="number" min="0" disabled={busy} value={control.payments_count} onChange={(e) => { setControl({...control, payments_count: e.target.value}); reset(); }} /></label>
            <label>{`Сумма успешных платежей, ${currency}`}<input inputMode="decimal" disabled={busy} value={control.payments_total} onChange={(e) => { setControl({...control, payments_total: e.target.value.replace(",", ".")}); reset(); }} /></label></>}
          {useSubscriptions && <label>Количество подписок<input type="number" min="0" disabled={busy} value={control.subscriptions_count} onChange={(e) => { setControl({...control, subscriptions_count: e.target.value}); reset(); }} /></label>}
        </div>
      </div>
      <div className="grid2">
        <fieldset disabled={busy}>
          <legend><label className="check"><input type="checkbox" checked={usePayments} onChange={(e) => { setUsePayments(e.target.checked); reset(); }} />Платежи</label></legend>
          {usePayments && <>
            <label>Таблица платежей<input value={payments.table} onChange={(e) => { setPayments({...payments, table: e.target.value}); setPaymentColumns([]); reset(); }} /></label>
            <button type="button" disabled={!file} onClick={() => inspect("payments")}>Загрузить колонки платежей</button>
            {!!paymentColumns.length && <>
              {select("payments", "id", "ID платежа")}
              {select("payments", "user", "ID клиента в источнике")}
              {select("payments", "amount", "Сумма")}
              <label>Единицы суммы<SelectField aria-label="Единицы суммы" value={payments.amount_unit} onChange={(e) => { setPayments({...payments, amount_unit: e.target.value}); reset(); }}><option value="decimal">Рубли с копейками</option><option value="minor">Копейки</option></SelectField></label>
              {select("payments", "status", "Статус", true)}
              {select("payments", "paid_at", "Дата оплаты", true)}
              {select("payments", "currency", "Валюта", true)}
              {select("payments", "description", "Описание", true)}
            </>}
          </>}
        </fieldset>
        <fieldset disabled={busy}>
          <legend><label className="check"><input type="checkbox" checked={useSubscriptions} onChange={(e) => { setUseSubscriptions(e.target.checked); reset(); }} />Подписки</label></legend>
          {useSubscriptions && <>
            <label>Таблица подписок<input value={subscriptions.table} onChange={(e) => { setSubscriptions({...subscriptions, table: e.target.value}); setSubscriptionColumns([]); reset(); }} /></label>
            <button type="button" disabled={!file} onClick={() => inspect("subscriptions")}>Загрузить колонки подписок</button>
            {!!subscriptionColumns.length && <>
              {select("subscriptions", "user", "ID клиента в источнике")}
              {select("subscriptions", "expires_at", "Окончание подписки")}
              {select("subscriptions", "remnawave_uuid", "UUID пользователя Remnawave")}
              {select("subscriptions", "subscription_url", "Ссылка подписки", true)}
              {select("subscriptions", "plan", "Название тарифа", true)}
              {select("subscriptions", "traffic_gb", "Лимит трафика, ГБ", true)}
              {select("subscriptions", "devices", "Лимит устройств", true)}
            </>}
          </>}
        </fieldset>
      </div>
      <button className="primary" disabled={busy || !ready} onClick={makePreview}>Сверить историю</button>

      {preview && <div className="history-preview">
        <h3>Сверка</h3>
        <div className="history-checks">
          {preview.reconciliation.checks.map((c: any) => <div key={c.name}><StatusBadge tone={c.ok ? "ok" : "danger"}>{c.ok ? "Совпадает" : "Расхождение"}</StatusBadge><b>{CHECK[c.name] || c.name}</b><span>ожидалось {c.expected} · прочитано {c.actual}</span></div>)}
        </div>
        <p className="muted">Пропущено платежей с другими статусами: {preview.reconciliation.skipped_payments}; возвращённых: {preview.reconciliation.refunded_payments}. Проверка действует до {new Date(preview.expires_at + "Z").toLocaleString()}.</p>
        <p>Платежи — новых {preview.payments.counts.new}, уже перенесено {preview.payments.counts.already_imported}, конфликтов {preview.payments.counts.conflict + preview.payments.counts.blocked}. Подписки — новых {preview.subscriptions.counts.new}, уже перенесено {preview.subscriptions.counts.already_imported}, конфликтов {preview.subscriptions.counts.conflict + preview.subscriptions.counts.blocked}.</p>
        <div className="table-wrap" style={{maxHeight: 420, overflow: "auto"}}><table><thead><tr><th>Тип</th><th>Источник</th><th>Клиент</th><th>Данные</th><th>Результат</th></tr></thead><tbody>
          {rows.map((r: any) => <tr key={r.kind + r.key}><td>{r.kind}</td><td><code>{r.key}</code></td><td>{r.user_id ? `#${r.user_id}` : r.user}</td><td>{r.kind === "Платёж" ? `${r.amount} ${r.currency} · ${r.status === "refunded" ? "возврат" : "оплачен"}` : `до ${new Date(r.expires_at + "Z").toLocaleDateString()}`}</td><td>{ROW_STATUS[r.status_import]}{r.reason ? ` — ${r.reason}` : ""}</td></tr>)}
          {!rows.length && <tr><td colSpan={5}>Нет строк для переноса</td></tr>}
        </tbody></table></div>
        <label className="check"><input disabled={busy} type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />Я сверил итоги и строки с исходной системой</label>
        <div className="inline">
          <button className="primary" disabled={busy || !accepted || !preview.can_apply} onClick={apply}>Применить историю</button>
          <button disabled={busy} onClick={cancel}>Отменить сверку</button>
        </div>
      </div>}

      <h3>Журнал переносов истории</h3>
      <div className="table-wrap"><table><thead><tr><th>Источник</th><th>Статус</th><th>Создано</th><th>Результат</th><th /></tr></thead><tbody>
        {jobs.map((j) => <tr key={j.id}><td>{j.namespace}<details><summary>SHA256</summary><code>{j.source_sha256}</code></details></td><td>{JOB_STATUS[j.status] || j.status}</td><td>{new Date(j.created_at + "Z").toLocaleString()}</td><td>{j.result ? (j.result.rolled_back ? `Откатан: платежей ${j.result.payments_removed}, подписок ${j.result.subscriptions_removed}` : `Платежей ${j.result.payments_created}, подписок ${j.result.subscriptions_created}, сумма ${j.result.paid_total}`) : "—"}</td><td>{j.status === "applied" && <button disabled={busy} onClick={() => rollback(j)}>Откатить</button>}</td></tr>)}
        {!jobs.length && <tr><td colSpan={5}>Переносов истории пока нет</td></tr>}
      </tbody></table></div>
    </section>
  );
}
