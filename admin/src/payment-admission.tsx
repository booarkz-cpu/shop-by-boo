import React, {useCallback, useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

const PROVIDERS: [string, string][] = [["yookassa", "ЮKassa"], ["platega", "Platega"], ["rollypay", "RollyPay"]];
const STAGE: Record<string, string> = {
  pending: "ожидает", checkout: "создание заказа", awaiting_payment: "ждёт оплату на странице провайдера", webhook: "ожидание webhook",
  fulfillment: "выдача VPN", duplicate: "повтор webhook", tamper: "поддельные webhook", refund: "возврат",
  late_success: "успех после возврата", done: "готово",
};
const RUN_STATUS: Record<string, string> = {queued: "в очереди", running: "выполняется", passed: "пройдена", failed: "не пройдена", cancelled: "остановлена"};
const name = (p: string) => (PROVIDERS.find(x => x[0] === p) || [p, p])[1];
const when = (v?: string | null) => v ? new Date(v).toLocaleString() : "—";

/** E2E v2: the staging run and the production admission of its signed result. */
export function PaymentAdmission({request, toast}: {request: Request; toast: (m: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => request("/api/admin/e2e-v2/overview").then(setData).catch((e: any) => setError(e.message)), [request]);
  useEffect(() => { load(); }, [load]);
  const active = (data?.runs || []).some((r: any) => r.status === "queued" || r.status === "running");
  useEffect(() => { if (!active) return; const t = setInterval(load, 3000); return () => clearInterval(t); }, [active, load]);
  if (error) return <div className="card"><div role="alert" className="error">{error}</div></div>;
  if (!data) return <div className="card"><p className="muted">Загрузка…</p></div>;
  return data.staging
    ? <StagingRuns data={data} request={request} toast={toast} reload={load}/>
    : <Admission data={data} request={request} toast={toast} reload={load}/>;
}

function Checks({data, checks}: {data: any; checks: string[]}) {
  return <ul className="e2e-checks">{data.checks.map((c: any) =>
    <li key={c.id} className={checks.includes(c.id) ? "done" : undefined}>{checks.includes(c.id) ? "✓" : "·"} {c.label}</li>)}</ul>;
}

function StagingRuns({data, request, toast, reload}: any) {
  const configured = data.providers_configured || {};
  const [nonce, setNonce] = useState("");
  const [plans, setPlans] = useState<any[]>([]);
  const [planId, setPlanId] = useState("");
  const [providers, setProviders] = useState<string[]>(PROVIDERS.map(p => p[0]).filter(p => configured[p]));
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/plans").then((rows: any[]) => { const ok = (rows || []).filter(p => p.enabled && Number(p.price) > 0); setPlans(ok); if (ok[0]) setPlanId(String(ok[0].id)); }).catch(() => setPlans([])); }, [request]);
  const runs = data.runs || [];
  const current = runs.find((r: any) => r.status === "queued" || r.status === "running");

  async function start(e: React.FormEvent) {
    e.preventDefault(); if (busy) return; setBusy(true); setError("");
    try {
      await request("/api/admin/e2e-v2/runs", {method: "POST", body: JSON.stringify({nonce: nonce.trim(), plan_id: Number(planId), providers, payment_timeout_seconds: minutes * 60})});
      toast("Проверка запущена"); setNonce(""); reload();
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function cancel(id: string) {
    try { await request(`/api/admin/e2e-v2/runs/${id}/cancel`, {method: "POST"}); toast("Проверка остановлена"); reload(); } catch (err: any) { setError(err.message); }
  }

  return <div className="grid2">
    <div className="card">
      <h3>Проверка E2E v2 на стенде</h3>
      <p className="muted">Это стенд (APP_ENV=staging). Магазин создаёт настоящий заказ через обычный checkout, вы оплачиваете его на странице песочницы провайдера, дальше всё проверяется автоматически: webhook, выдача, повторы, подделки, возврат и отзыв доступа. Результат подписывается ключом стенда.</p>
      <label className="field">Открытый ключ стенда
        <input readOnly value={data.public_key || ""} onFocus={e => e.currentTarget.select()}/>
      </label>
      <p className="muted">Вставьте этот ключ на рабочем сервере в разделе «Проверка платежей» один раз.</p>
      {error && <div role="alert" className="error">{error}</div>}
      {current ? <p>Проверка уже выполняется — дождитесь её окончания или остановите.</p> :
        <form onSubmit={start}>
          <label className="field">Код запуска с рабочего сервера
            <input required value={nonce} onChange={e => setNonce(e.target.value)} placeholder="e2e2n.…"/>
          </label>
          <label className="field">Тариф для заказа
            <select required value={planId} onChange={e => setPlanId(e.target.value)}>
              {plans.length === 0 && <option value="">Нет включённых тарифов с ценой</option>}
              {plans.map(p => <option key={p.id} value={p.id}>{p.name} — {p.price}</option>)}
            </select>
          </label>
          <fieldset><legend>Платёжные системы</legend>
            {PROVIDERS.map(([id, label]) => <label key={id} className="inline">
              <input type="checkbox" disabled={!configured[id]} checked={providers.includes(id)}
                     onChange={e => setProviders(e.target.checked ? [...providers, id] : providers.filter(x => x !== id))}/>
              {label}{configured[id] ? "" : " — ключи песочницы не заданы в .env стенда"}
            </label>)}
          </fieldset>
          <label className="field">Время на оплату, минут
            <input type="number" min={5} max={120} value={minutes} onChange={e => setMinutes(Number(e.target.value))}/>
          </label>
          <button className="primary" disabled={busy || !nonce || !planId || providers.length === 0}>Запустить проверку</button>
        </form>}
    </div>
    <div className="card">
      <h3>Запуски</h3>
      {runs.length === 0 ? <p className="muted">Запусков ещё не было.</p> : runs.map((run: any) => <div key={run.id} className="e2e-run" data-run-id={run.id}>
        <div className="toolbar"><b>{RUN_STATUS[run.status] || run.status}</b><span className="muted">{when(run.created_at)} · {run.admin}</span>
          {(run.status === "queued" || run.status === "running") && <button className="danger" onClick={() => cancel(run.id)}>Остановить</button>}</div>
        {run.error && <div className="error">{run.error}</div>}
        {run.cases.map((c: any) => <div key={c.provider} className="e2e-case">
          <p><b>{name(c.provider)}</b> — {c.status === "passed" ? "пройдено" : c.status === "failed" ? "не пройдено" : STAGE[c.stage] || c.stage}{c.payment_id ? ` · заказ #${c.payment_id}` : ""}</p>
          {c.checkout_url && <p><a href={c.checkout_url} target="_blank" rel="noreferrer noopener">Открыть страницу оплаты</a> и оплатите тестовой картой провайдера.</p>}
          {c.error && <p className="error">{c.error}</p>}
          <Checks data={data} checks={c.checks}/>
        </div>)}
        {run.attestation && run.status === "passed" && <label className="field">Подписанный результат — скопируйте на рабочий сервер
          <textarea readOnly rows={4} value={run.attestation} onFocus={e => e.currentTarget.select()}/>
        </label>}
      </div>)}
    </div>
  </div>;
}

function Admission({data, request, toast, reload}: any) {
  const a = data.admission || {};
  const cfg = a.config || {};
  const status = a.status || {};
  const [key, setKey] = useState(cfg.public_key || "");
  const [providers, setProviders] = useState<string[]>(cfg.providers || ["yookassa"]);
  const [url, setUrl] = useState(cfg.staging_url || "");
  const [attestation, setAttestation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (fn: () => Promise<any>, ok: string) => {
    if (busy) return; setBusy(true); setError("");
    try { await fn(); toast(ok); reload(); } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  };
  const expires = status.status === "passed" && status.finished_at ? new Date(new Date(status.finished_at).getTime() + 24 * 3600 * 1000) : null;
  const fresh = !!expires && expires.getTime() > Date.now();

  return <div className="grid2">
    <div className="card">
      <h3>Допуск реальных платежей (E2E v2)</h3>
      <p className="muted">Реальные платежи открываются только после полной проверки на отдельном стенде с APP_ENV=staging: настоящий заказ, подписанный webhook, выдача, повтор и подделки webhook, возврат и отзыв доступа. Стенд должен работать на той же версии ({data.distribution_tag}). Результат действует 24 часа.</p>
      {error && <div role="alert" className="error">{error}</div>}
      <h4>1. Стенд</h4>
      <label className="field">Открытый ключ стенда
        <input value={key} onChange={e => setKey(e.target.value)} placeholder="Из раздела «Проверка платежей» на стенде"/>
      </label>
      <label className="field">Адрес стенда (для заметки)
        <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://staging.example.com"/>
      </label>
      <fieldset><legend>Платёжные системы, которые будут принимать оплату</legend>
        {PROVIDERS.map(([id, label]) => <label key={id} className="inline">
          <input type="checkbox" checked={providers.includes(id)} onChange={e => setProviders(e.target.checked ? [...providers, id] : providers.filter(x => x !== id))}/>{label}
        </label>)}
      </fieldset>
      <button disabled={busy || !key || providers.length === 0} onClick={() => run(() => request("/api/admin/e2e-v2/admission/config", {method: "PUT", body: JSON.stringify({public_key: key.trim(), providers, staging_url: url.trim()})}), "Настройки сохранены, платежи закрыты до новой проверки")}>Сохранить</button>
      <p className="muted">Сохранение закрывает реальные платежи и требует новой проверки.</p>
      <h4>2. Код запуска</h4>
      {status.status === "awaiting_attestation" && status.nonce ? <label className="field">Код для этого запуска
        <input readOnly value={status.nonce} onFocus={e => e.currentTarget.select()}/>
      </label> : null}
      <button disabled={busy || !a.config} onClick={() => run(() => request("/api/admin/e2e-v2/admission/nonce", {method: "POST"}), "Новый код запуска выдан")}>Получить код запуска</button>
      <p className="muted">Введите код на стенде при запуске проверки. Новый код отменяет предыдущий и закрывает платежи.</p>
      <h4>3. Результат со стенда</h4>
      <label className="field">Подписанный результат
        <textarea rows={4} value={attestation} onChange={e => setAttestation(e.target.value)} placeholder="e2e2.…"/>
      </label>
      <button className="primary" disabled={busy || !attestation.trim() || status.status !== "awaiting_attestation"} onClick={() => run(async () => { await request("/api/admin/e2e-v2/admission/attestation", {method: "POST", body: JSON.stringify({attestation: attestation.trim()})}); setAttestation(""); }, "Результат принят")}>Принять результат</button>
    </div>
    <div className="card">
      <h3>Состояние допуска</h3>
      <p>Проверка: <b>{status.status === "passed" ? (fresh ? "пройдена" : "устарела") : status.status === "awaiting_attestation" ? "ждёт результат со стенда" : "не пройдена"}</b></p>
      {status.status === "passed" && <>
        <p className="muted">Завершена {when(status.finished_at)} · действует до {expires ? expires.toLocaleString() : "—"} · запуск {status.run_id}</p>
        {(status.provider_results || []).map((r: any) => <p key={r.provider}>{name(r.provider)}: {r.status === "passed" ? "все этапы пройдены" : "не пройдено"}</p>)}
      </>}
      <p>Реальные платежи: <b>{a.payments_allowed ? "открыты" : "закрыты"}</b></p>
      <div className="inline">
        <button className="primary" disabled={busy || !fresh || a.gate_enabled} onClick={() => run(() => request("/api/admin/payments/production-gate", {method: "POST", body: JSON.stringify({enabled: true})}), "Реальные платежи открыты")}>Открыть реальные платежи</button>
        <button className="danger" disabled={busy || !a.gate_enabled} onClick={() => run(() => request("/api/admin/payments/production-gate", {method: "POST", body: JSON.stringify({enabled: false})}), "Реальные платежи закрыты")}>Закрыть</button>
      </div>
      <p className="muted">Через 24 часа после проверки новые оплаты, пополнения и автопродления снова блокируются, пока не будет принят свежий результат. Открывать и закрывать платежи может только администратор.</p>
      <h4>Что проверяется для каждой платёжной системы</h4>
      <Checks data={data} checks={(status.provider_results || [])[0]?.checks || []}/>
    </div>
  </div>;
}
