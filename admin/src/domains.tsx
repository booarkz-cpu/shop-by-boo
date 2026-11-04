import React, {useEffect, useState} from "react";
import {EmptyState, LoadState} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (text: string) => void};
const post = (body?: unknown): RequestInit => ({method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});
const when = (v?: string | null) => (v ? new Date(v).toLocaleString() : "—");
const DNS: Record<string, string> = {unknown: "не проверен", ok: "в порядке", missing: "нет записи", mismatch: "другой адрес", caa: "CAA запрещает", error: "ошибка DNS"};
const CERT: Record<string, string> = {unknown: "не проверен", valid: "действует", expiring: "скоро истекает", expired: "истёк", invalid: "недоверенный", missing: "нет"};
const SERVED: Record<string, string> = {shop: "Caddy магазина", remnawave: "Caddy сервера Remnawave", external: "Внешний"};

/** «Серверы → Домены и сертификаты» (v28.67.0, stage 11): Domain Manager, certificates and what each Caddy serves.
 *  Portal domains served by the shop's Caddy get their certificates on demand (deploy/Caddyfile asks /caddy/ask),
 *  so a domain added here works without editing files or restarting. */
export function Domains({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [certs, setCerts] = useState<any>(null);
  const [routes, setRoutes] = useState<any>(null);
  const [servers, setServers] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<Record<number, any>>({});
  const [form, setForm] = useState({domain: "", purpose: "subscription", served_by: "shop", server_id: "", expected_ip: ""});
  const [removing, setRemoving] = useState<number | null>(null);
  const load = () => {
    setError("");
    Promise.all([request("/api/admin/rw/domains"), request("/api/admin/rw/certificates"), request("/api/admin/rw/proxy-routes"),
      request("/api/admin/rw/servers").catch(() => ({servers: []}))])
      .then(([a, b, c, s]) => { setD(a); setCerts(b); setRoutes(c); setServers(s.servers || []); })
      .catch((e: any) => setError(e.message));
  };
  useEffect(load, []);
  if (!d) return <LoadState error={error} onRetry={load} label="Загрузка доменов…"/>;
  const run = async (key: string, fn: () => Promise<any>, ok?: string) => {
    setError(""); setBusy(key);
    try { const out = await fn(); if (ok) toast(ok); load(); return out; } catch (e: any) { setError(e.message); } finally { setBusy(""); }
  };
  const add = (e: React.FormEvent) => { e.preventDefault(); run("add", async () => {
    await request("/api/admin/rw/domains", post({domain: form.domain, purpose: form.purpose, served_by: form.served_by,
      server_id: form.served_by === "remnawave" ? Number(form.server_id) || null : null, expected_ip: form.expected_ip || null}));
    setForm({...form, domain: "", expected_ip: ""});
  }, `Домен ${form.domain} добавлен — нажмите «Проверить»`); };
  const check = (id: number) => run(`check-${id}`, async () => { const r = await request(`/api/admin/rw/domains/${id}/check`, post()); setResult({...result, [id]: r}); });
  const shopOnly = form.served_by === "shop";
  return <div data-domains>
    <div className="card" data-domain-list>
      <h3>Домены</h3>
      <p className="muted">Домены портала подписки обслуживает Caddy магазина: сертификат Let's Encrypt выпускается сам при первом обращении, если домен включён здесь и указывает на сервер магазина ({d.shop_api_domain}).
        Домены панели и страницы подписки на серверах Remnawave проверяются отсюда, сертификат выпускает их Caddy.</p>
      {error && <div role="alert" className="error">{error}</div>}
      {d.domains.length === 0 ? <EmptyState title="Доменов пока нет" hint="Добавьте домен портала подписки, например sub.example.com."/> :
        <div className="table-wrap"><table>
          <thead><tr><th>Домен</th><th>Назначение</th><th>DNS</th><th>Сертификат</th><th>HTTPS</th><th></th></tr></thead>
          <tbody>{d.domains.map((x: any) => <React.Fragment key={x.id}><tr data-domain={x.domain}>
            <td><b>{x.domain}</b>{d.subscription_base === `https://${x.domain}` ? <div className="success">адрес подписки клиентов</div> : null}
              {!x.enabled ? <div className="muted">выключен</div> : null}</td>
            <td>{x.purpose_title}<div className="muted">{SERVED[x.served_by]}</div></td>
            <td data-status={x.dns_status}>{DNS[x.dns_status] || x.dns_status}<div className="muted">{when(x.dns_checked_at)}</div></td>
            <td data-status={x.cert_status}>{CERT[x.cert_status] || x.cert_status}<div className="muted">{x.cert_issuer || ""}{x.cert_expires_at ? ` · до ${new Date(x.cert_expires_at).toLocaleDateString()}` : ""}</div></td>
            <td>{x.http_status ?? "—"}</td>
            <td className="actions">
              <button onClick={() => check(x.id)} disabled={busy === `check-${x.id}`}>{busy === `check-${x.id}` ? "Проверка…" : "Проверить"}</button>
              {(d.dns_providers || []).map((p: any) => <button key={p.id} onClick={() => run(`dns-${p.id}-${x.id}`, async () => {
                const r = await request(`/api/admin/rw/domains/${x.id}/dns-record?provider=${p.id}`, post());
                toast(`${p.title}: запись A → ${r.content} (${r.action === "created" ? "создана" : r.action === "unchanged" ? "уже верная" : "обновлена"})`); })}>Запись A в {p.title}</button>)}
              {x.purpose === "subscription" && x.served_by === "shop" && d.subscription_base !== `https://${x.domain}` &&
                <button onClick={() => run(`primary-${x.id}`, () => request(`/api/admin/rw/domains/${x.id}/primary`, post()), "Клиенты получают ссылки на этом домене")}>Сделать адресом подписки</button>}
              <button onClick={() => run(`toggle-${x.id}`, () => request(`/api/admin/rw/domains/${x.id}`, {method: "PATCH", body: JSON.stringify({enabled: !x.enabled})}))}>{x.enabled ? "Выключить" : "Включить"}</button>
              {removing === x.id ? <button className="danger" onClick={() => run(`del-${x.id}`, () => request(`/api/admin/rw/domains/${x.id}`, {method: "DELETE"}), "Домен удалён")}>Точно удалить</button>
                : <button onClick={() => setRemoving(x.id)}>Удалить</button>}
            </td></tr>
            {(result[x.id] || x.last_error) && <tr><td colSpan={6} data-domain-result>
              {result[x.id] ? <ul><li>DNS: {result[x.id].dns}</li><li>TLS: {result[x.id].tls}</li><li>HTTPS: {result[x.id].http ?? "нет ответа"}</li></ul> : <span className="muted">{x.last_error}</span>}
              {x.dns_records && Object.keys(x.dns_records).length ? <details><summary>Записи DNS</summary><ul>{["A", "AAAA", "CNAME", "TXT", "CAA"].map(t =>
                <li key={t}><b>{t}</b>: {(x.dns_records[t] || []).join(", ") || "—"}</li>)}</ul>{x.dns_records.expected?.length ? <p className="muted">Ожидается: {x.dns_records.expected.join(", ")}</p> : null}</details> : null}
            </td></tr>}
          </React.Fragment>)}</tbody>
        </table></div>}
      <form onSubmit={add} className="grid-form" data-add-domain>
        <h4>Добавить домен</h4>
        <label>Домен<input value={form.domain} onChange={e => setForm({...form, domain: e.target.value.trim().toLowerCase()})} required placeholder="sub.example.com"/></label>
        <label>Кто обслуживает<select value={form.served_by} onChange={e => setForm({...form, served_by: e.target.value, purpose: e.target.value === "shop" ? "subscription" : form.purpose === "subscription" ? "panel" : form.purpose})}>
          {Object.entries(SERVED).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>Назначение<select value={form.purpose} disabled={shopOnly} onChange={e => setForm({...form, purpose: e.target.value})}>
          {Object.entries(d.purposes).filter(([k]) => !shopOnly || k === "subscription").map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        {form.served_by === "remnawave" && <label>Сервер<select value={form.server_id} required onChange={e => setForm({...form, server_id: e.target.value})}>
          <option value="">— выберите —</option>{servers.map((s: any) => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}</select></label>}
        <label>Ожидаемый адрес (необязательно)<input value={form.expected_ip} onChange={e => setForm({...form, expected_ip: e.target.value.trim()})} placeholder="203.0.113.10"/></label>
        <div className="wide"><button className="primary" disabled={busy === "add" || !form.domain}>Добавить</button></div>
      </form>
      {!(d.dns_providers || []).length && <p className="muted">Записи DNS можно создавать отсюда: задайте токен Cloudflare API (право Zone:DNS:Edit), ключ Bunny DNS или токен Gcore DNS в «Настройки → Параметры → Remnawave». Без ключа создайте запись A у регистратора — адрес показан в проверке.</p>}
    </div>
    <div className="card" data-certificates>
      <h3>Сертификаты</h3>
      <p className="muted">Выпуск и продление — автоматически, Let's Encrypt (HTTP-01 или TLS-ALPN-01): порты 80 и 443 сервера должны быть открыты. {certs?.dns01}.</p>
      <button onClick={() => run("certs", async () => { const r = await request("/api/admin/rw/certificates/check", post()); toast(`Проверено доменов: ${r.checked}${r.problems.length ? `, с ошибками: ${r.problems.join(", ")}` : ""}`); })} disabled={busy === "certs"}>Проверить все</button>
      {certs?.certificates?.length ? <div className="table-wrap"><table>
        <thead><tr><th>Домен</th><th>Состояние</th><th>Издатель</th><th>Действует до</th><th>Продление</th></tr></thead>
        <tbody>{certs.certificates.map((c: any) => <tr key={c.domain} data-cert={c.domain} data-status={c.status}><td>{c.domain}</td><td>{CERT[c.status] || c.status}</td><td>{c.issuer || "—"}</td>
          <td>{c.expires_at ? `${new Date(c.expires_at).toLocaleDateString()} (${c.days_left} дн.)` : "—"}</td><td className="muted">{c.renewal}</td></tr>)}</tbody>
      </table></div> : <p className="muted">Сертификаты появятся после проверки доменов.</p>}
    </div>
    <div className="card" data-proxy-routes>
      <h3>Маршруты Caddy</h3>
      <p className="muted">Один Caddy на сервере магазина и по одному на серверах Remnawave. Второй прокси на портах 80/443 не ставится.</p>
      {routes && <div className="table-wrap"><table>
        <thead><tr><th>Домен</th><th>Куда</th><th>Откуда маршрут</th></tr></thead>
        <tbody>
          {routes.shop.map((r: any) => <tr key={`s-${r.domain}`}><td>{r.domain}</td><td>{r.target}</td><td className="muted">{r.source}</td></tr>)}
          {routes.portal.map((r: any) => <tr key={`p-${r.domain}`}><td>{r.domain}{r.primary ? " ★" : ""}</td><td>{r.target}</td><td className="muted">{r.source}{r.enabled ? "" : " · выключен"}</td></tr>)}
          {routes.remnawave.map((r: any) => <tr key={`r-${r.domain}`}><td>{r.domain}</td><td>{r.target}</td><td className="muted">Мастер установки №{r.installation_id} · {r.tls === "acme" ? "Let's Encrypt" : "внутренний сертификат"}</td></tr>)}
        </tbody>
      </table></div>}
    </div>
  </div>;
}
