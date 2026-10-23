import React, {useEffect, useState} from "react";
import {Mail, RefreshCw, Trash2, Upload} from "lucide-react";
import {StatusBadge, type Tone} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Finding = {check: string; status: "ok" | "info" | "warn" | "fail"; title: string; detail: string; record: string | null};
type Report = {id: number; org_name: string; report_id: string; reporter_email: string | null; sender_matches: boolean; policy: string | null; date_begin: string; date_end: string; source: string; messages: number; passed: number; failed: number};
type Source = {ip: string; messages: number; passed: number; failed: number; dispositions: Record<string, number>; header_from: string[]; dkim_domains: string[]};
type View = {
  domain: string;
  smtp_from: string;
  check: {domain: string; checked_at: string; status: string; findings: Finding[]; selectors: string[]} | null;
  intake: {configured: boolean; mailbox: string; folder: string; retention_days: number; last_success: string | null; last_error: string | null; imported: number; duplicates: number; rejected: number; journal: {at: string; outcome: string; detail: string; source: string}[]};
  summary: {days: number; reports: number; messages: number; passed: number; failed: number; pass_rate: number | null; sources: Source[]; reporters: {org: string; reports: number}[]};
  reports: Report[];
};

const TONE: Record<string, Tone> = {ok: "ok", info: "info", warn: "warn", fail: "danger"};
const LABEL: Record<string, string> = {ok: "В порядке", info: "Инфо", warn: "Внимание", fail: "Ошибка"};
const CHECKS: Record<string, string> = {domain: "Домен", mx: "MX", spf: "SPF", dkim: "DKIM", dmarc: "DMARC"};
const OUTCOME: Record<string, [Tone, string]> = {imported: ["ok", "Принят"], duplicate: ["idle", "Повтор"], rejected: ["warn", "Отклонён"]};

const day = (value: string | null) => (value ? new Date(value + (value.endsWith("Z") ? "" : "Z")).toLocaleString("ru-RU", {dateStyle: "short", timeStyle: "short"}) : "—");
const num = (value: number) => value.toLocaleString("ru-RU");

/** SPF, DKIM, DMARC and MX of the shop's mail domain plus DMARC aggregate reports. */
export function MailDomain({data, request, toast}: {data: View; request: RequestFn; toast: (m: string) => void}) {
  const [view, setView] = useState<View>(data);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selectors, setSelectors] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [confirm, setConfirm] = useState("");
  const [opened, setOpened] = useState<any>(null);
  useEffect(() => {
    setView(data);
    if (data?.check?.selectors?.length) setSelectors(data.check.selectors.join(", "));
  }, [data]);
  if (!view?.intake) return <p className="muted card">Загрузка почтового домена…</p>;

  async function run(key: string, action: () => Promise<any>, done: (r: any) => string) {
    setBusy(key);
    setError("");
    try {
      const result = await action();
      if (result?.intake) setView(result);
      toast(done(result));
    } catch (e: any) {
      setError(e.message || "Не удалось выполнить");
    } finally {
      setBusy("");
    }
  }

  const check = () =>
    run("check", () => request("/api/admin/mail/domain/check", {method: "POST", body: JSON.stringify({dkim_selectors: selectors.split(/[\s,]+/).filter(Boolean)})}), (r) => `Проверка завершена: ${LABEL[r.check?.status === "fail" ? "fail" : r.check?.status === "warn" ? "warn" : "ok"]}`);
  const send = () => {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    run("upload", () => request("/api/admin/mail/dmarc/upload", {method: "POST", body}), (r) => (r.outcome === "duplicate" ? "Этот отчёт уже загружен" : "Отчёт загружен")).then(() => setFile(null));
  };
  const sync = () => run("sync", () => request("/api/admin/mail/dmarc/sync", {method: "POST"}), (r) => (r.result?.error ? `Ящик: ${r.result.error}` : `Писем: ${r.result?.messages ?? 0}, новых отчётов: ${r.result?.imported ?? 0}`));
  const erase = () => run("erase", () => request("/api/admin/mail/dmarc/erase", {method: "POST", body: JSON.stringify({confirm})}), (r) => `Удалено отчётов: ${r.erased}`).then(() => setConfirm(""));
  async function open(id: number) {
    try {
      setOpened(await request(`/api/admin/mail/dmarc/reports/${id}`));
    } catch (e: any) {
      setError(e.message || "Отчёт не открылся");
    }
  }

  const findings = view.check?.findings || [];
  const groups = Object.keys(CHECKS).filter((k) => findings.some((f) => f.check === k));
  const s = view.summary;
  return (
    <div className="network-intel mail-domain">
      <section className="card" aria-label="DNS почтового домена">
        <h2>
          <Mail aria-hidden="true" /> Почтовый домен {view.domain ? <code>{view.domain}</code> : null}
        </h2>
        <p className="muted">
          Проверяет записи, от которых зависит доставка писем магазина: MX, SPF, DKIM и DMARC. Записи читаются через DNS-over-HTTPS; проверка повторяется раз в сутки.
          {view.smtp_from && ` Отправитель писем: ${view.smtp_from}.`}
        </p>
        {!view.domain && <p className="error">Почтовый домен не задан: укажите MAIL_DOMAIN или SMTP_FROM в .env.</p>}
        <div className="mail-check-form">
          <label>
            <span>Селекторы DKIM провайдера (необязательно)</span>
            <input value={selectors} onChange={(e) => setSelectors(e.target.value)} placeholder="например, google, s1" />
          </label>
          <button type="button" onClick={check} disabled={busy === "check" || !view.domain}>
            <RefreshCw aria-hidden="true" className={busy === "check" ? "spin" : ""} /> Проверить сейчас
          </button>
        </div>
        {view.check ? (
          <p className="muted">
            Последняя проверка: {day(view.check.checked_at)} · итог <StatusBadge tone={TONE[view.check.status] || "idle"}>{LABEL[view.check.status] || view.check.status}</StatusBadge>
          </p>
        ) : (
          <p className="muted">Проверка ещё не выполнялась.</p>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {groups.map((group) => (
        <article key={group} className="card intel-node" aria-label={CHECKS[group]}>
          <h3>{CHECKS[group]}</h3>
          <ul className="intel-warnings">
            {findings
              .filter((f) => f.check === group)
              .map((f, i) => (
                <li key={i} className="mail-finding">
                  <StatusBadge tone={TONE[f.status]}>{LABEL[f.status]}</StatusBadge> <strong>{f.title}</strong>
                  {f.detail && <span className="muted"> — {f.detail}</span>}
                  {f.record && <code className="mail-record">{f.record}</code>}
                </li>
              ))}
          </ul>
        </article>
      ))}

      <section className="card" aria-label="Отчёты DMARC">
        <h2>Отчёты DMARC за {s.days} дней</h2>
        <p className="muted">
          Почтовые службы (Gmail, Yahoo, Mail.ru и другие) присылают отчёты на адрес из rua= в DMARC-записи: сколько писем от имени домена пришло с каждого адреса и прошли ли они проверку. Отчёт может прислать кто угодно, поэтому данные — только наблюдение: отчёт из ящика, отправитель которого не совпадает с организацией отчёта, помечен «не подтверждён».
        </p>
        <div className="intel-sources">
          <div className="intel-source">
            <strong>{num(s.messages)} писем</strong>
            <span className="muted">
              прошли DMARC: {num(s.passed)}
              {s.pass_rate !== null ? ` (${s.pass_rate}%)` : ""} · не прошли: {num(s.failed)}
            </span>
            <span className="muted">
              Отчётов: {s.reports}
              {s.reporters.length > 0 && ` от ${s.reporters.map((r) => `${r.org} (${r.reports})`).join(", ")}`}
            </span>
          </div>
          <div className="intel-source">
            <StatusBadge tone={view.intake.configured ? (view.intake.last_error ? "warn" : "ok") : "idle"}>
              {view.intake.configured ? (view.intake.last_error ? "Ошибка ящика" : "Ящик подключён") : "Ящик не подключён"}
            </StatusBadge>
            {view.intake.configured ? (
              <span className="muted">
                {view.intake.mailbox}, папка {view.intake.folder} · читается без изменений раз в 15 минут · последний успешный приём: {day(view.intake.last_success)}
              </span>
            ) : (
              <span className="muted">Задайте DMARC_IMAP_HOST, DMARC_IMAP_USER и DMARC_IMAP_PASSWORD или загружайте отчёты вручную.</span>
            )}
            {view.intake.last_error && <span className="muted">{view.intake.last_error}</span>}
            <span className="muted">
              Принято: {view.intake.imported} · повторов: {view.intake.duplicates} · отклонено: {view.intake.rejected} · хранение {view.intake.retention_days} дн
            </span>
            {view.intake.configured && (
              <button type="button" className="secondary" onClick={sync} disabled={busy === "sync"}>
                <RefreshCw aria-hidden="true" className={busy === "sync" ? "spin" : ""} /> Проверить ящик
              </button>
            )}
          </div>
        </div>
        <div className="mail-check-form">
          <label>
            <span>Файл отчёта (.xml, .xml.gz или .zip, до 5 МБ)</span>
            <input type="file" accept=".xml,.gz,.zip,application/gzip,application/zip,text/xml" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <button type="button" onClick={send} disabled={!file || busy === "upload"}>
            <Upload aria-hidden="true" /> Загрузить отчёт
          </button>
        </div>
      </section>

      {s.sources.length > 0 && (
        <section className="card" aria-label="Источники писем">
          <h3>Источники писем</h3>
          <p className="muted">Сначала адреса, письма с которых не прошли DMARC: это либо ваш сервис без SPF/DKIM, либо подделка.</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>IP-адрес</th>
                  <th>Писем</th>
                  <th>Не прошли</th>
                  <th>Решение получателя</th>
                  <th>Домен подписи DKIM</th>
                </tr>
              </thead>
              <tbody>
                {s.sources.map((source) => (
                  <tr key={source.ip}>
                    <td className="mono">{source.ip}</td>
                    <td>{num(source.messages)}</td>
                    <td>{source.failed ? <StatusBadge tone="warn">{num(source.failed)}</StatusBadge> : "0"}</td>
                    <td>{Object.entries(source.dispositions).map(([k, v]) => `${k}: ${num(v)}`).join(", ") || "—"}</td>
                    <td>{source.dkim_domains.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {view.reports.length > 0 && (
        <section className="card" aria-label="Последние отчёты">
          <h3>Последние отчёты</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Организация</th>
                  <th>Период</th>
                  <th>Писем</th>
                  <th>Не прошли</th>
                  <th>Источник</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {view.reports.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {r.org_name} {r.source === "imap" && !r.sender_matches && <StatusBadge tone="idle">не подтверждён</StatusBadge>}
                    </td>
                    <td>
                      {day(r.date_begin)} — {day(r.date_end)}
                    </td>
                    <td>{num(r.messages)}</td>
                    <td>{num(r.failed)}</td>
                    <td>{r.source === "imap" ? "ящик" : "загрузка"}</td>
                    <td>
                      <button type="button" className="secondary" onClick={() => open(r.id)}>
                        Записи
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {opened && (
            <div className="mail-opened">
              <h4>
                {opened.org_name}, отчёт {opened.report_id}
              </h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>IP-адрес</th>
                      <th>Писем</th>
                      <th>DKIM</th>
                      <th>SPF</th>
                      <th>Решение</th>
                      <th>From</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opened.records.map((x: any, i: number) => (
                      <tr key={i}>
                        <td className="mono">{x.source_ip}</td>
                        <td>{num(x.count)}</td>
                        <td>{x.dkim || "—"}</td>
                        <td>{x.spf || "—"}</td>
                        <td>{x.disposition || "—"}</td>
                        <td>{x.header_from || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button type="button" className="secondary" onClick={() => setOpened(null)}>
                Скрыть записи
              </button>
            </div>
          )}
        </section>
      )}

      {view.intake.journal.length > 0 && (
        <section className="card" aria-label="Журнал приёма">
          <h3>Журнал приёма</h3>
          <ul className="intel-warnings">
            {view.intake.journal.map((j, i) => (
              <li key={i}>
                <StatusBadge tone={OUTCOME[j.outcome]?.[0] || "idle"}>{OUTCOME[j.outcome]?.[1] || j.outcome}</StatusBadge> {day(j.at)} · {j.source === "imap" ? "ящик" : "загрузка"} · {j.detail}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card" aria-label="Удаление отчётов">
        <h3>Удаление отчётов</h3>
        <p className="muted">Отчёты старше {view.intake.retention_days} дней удаляются автоматически (DMARC_REPORT_RETENTION_DAYS). Удалить все отчёты и журнал может администратор с правом управления безопасностью; письма в ящике не меняются.</p>
        <div className="mail-check-form">
          <label>
            <span>Введите УДАЛИТЬ для подтверждения</span>
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="УДАЛИТЬ" />
          </label>
          <button type="button" className="danger" onClick={erase} disabled={confirm.trim() !== "УДАЛИТЬ" || busy === "erase"}>
            <Trash2 aria-hidden="true" /> Удалить все отчёты
          </button>
        </div>
      </section>
    </div>
  );
}
