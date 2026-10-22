import React, {useEffect, useState} from "react";
import {Globe2, RefreshCw, ShieldAlert} from "lucide-react";
import {StatusBadge, type Tone} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Entry = {freshness: "fresh" | "stale" | "error" | "missing"; data: any; fetched_at: string | null; age_hours: number | null; error: string | null} | null;
type Address = {ip: string; version: 4 | 6; private: boolean; registry: Entry; reputation: Entry};
type Node = {uuid: string; name: string; status: string; country: string | null; address: string; addresses: Address[]; warnings: {level: "danger" | "warn" | "info"; text: string}[]};
type Source = {id: string; label: string; enabled: boolean; ttl_hours: number; limit: number; window_minutes: number; blocked_until: string | null; last_error: string | null};
type Report = {
  enabled: boolean;
  sources: Source[];
  nodes: Node[];
  asn_concentration: {asn: number; nodes: string[]}[];
  generated_at: string;
  remnawave_error: string | null;
  customers: {days: number; asns: {asn: string; org: string | null; users: number}[]; countries: {country: string; users: number}[]};
};

const FRESH: Record<string, [Tone, string]> = {fresh: ["ok", "свежие"], stale: ["warn", "устарели"], error: ["danger", "ошибка"], missing: ["idle", "ещё не получены"]};
const LEVEL: Record<string, Tone> = {danger: "danger", warn: "warn", info: "info"};

function age(entry: Entry) {
  if (!entry || entry.age_hours === null) return "";
  return entry.age_hours < 1 ? "меньше часа назад" : entry.age_hours < 48 ? `${Math.round(entry.age_hours)} ч назад` : `${Math.round(entry.age_hours / 24)} дн назад`;
}

/** DNS, ASN/registry and reputation of VPN nodes, with freshness of every source. */
export function NetworkIntel({data, request, toast}: {data: Report; request: RequestFn; toast: (m: string) => void}) {
  const [view, setView] = useState<Report>(data);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => setView(data), [data]);
  if (!view?.sources) return <p className="muted card">Загрузка данных сети…</p>;

  async function refresh(ip: string) {
    setBusy(ip);
    setError("");
    try {
      const result = await request("/api/admin/network/intel/refresh", {method: "POST", body: JSON.stringify({ip})});
      const failed = Object.entries(result.results || {}).filter(([, v]) => v !== "fetched");
      toast(failed.length ? `Обновлено частично: ${failed.map(([k, v]) => `${k} — ${v}`).join(", ")}` : `Данные ${ip} обновлены`);
      setView(await request("/api/admin/network/intel"));
    } catch (e: any) {
      setError(e.message || "Не удалось обновить");
    } finally {
      setBusy("");
    }
  }

  const problems = view.nodes.reduce((n, node) => n + node.warnings.filter((w) => w.level !== "info").length, 0);
  return (
    <div className="network-intel">
      <section className="card" aria-label="Источники сетевых данных">
        <h2>
          <Globe2 aria-hidden="true" /> Сеть узлов: ASN и репутация
        </h2>
        <p className="muted">
          Адреса узлов берутся из Remnawave. Внутренние и зарезервированные адреса не отправляются наружу. Данные кэшируются и показываются с отметкой свежести; при сбое источника остаются последние полученные данные.
        </p>
        {!view.enabled && <p className="error">Сетевая аналитика выключена (NETWORK_INTEL_ENABLED=false).</p>}
        {view.remnawave_error && <p className="error" role="alert">{view.remnawave_error}: список узлов недоступен.</p>}
        <div className="intel-sources">
          {view.sources.map((s) => (
            <div key={s.id} className="intel-source">
              <StatusBadge tone={s.blocked_until ? "warn" : s.enabled ? "ok" : "idle"}>{s.blocked_until ? "Пауза по лимиту" : s.enabled ? "Подключён" : "Не подключён"}</StatusBadge>
              <strong>{s.label}</strong>
              <span className="muted">
                Хранение {s.ttl_hours >= 48 ? `${s.ttl_hours / 24} дн` : `${s.ttl_hours} ч`} · до {s.limit} запросов за {s.window_minutes} мин
              </span>
              {s.id === "abuseipdb" && !s.enabled && <span className="muted">Задайте ABUSEIPDB_API_KEY, чтобы проверять репутацию.</span>}
              {s.last_error && <span className="muted">{s.last_error}</span>}
            </div>
          ))}
        </div>
        <p className="muted">
          Узлов: {view.nodes.length} · требуют внимания: {problems}
          {view.asn_concentration.length > 0 && ` · в одной сети: ${view.asn_concentration.map((g) => `AS${g.asn} (${g.nodes.length})`).join(", ")}`}
        </p>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {view.nodes.map((node) => (
        <article key={node.uuid || node.name} className="card intel-node" aria-label={`Узел ${node.name}`}>
          <header className="intel-node-head">
            <div>
              <h3>{node.name}</h3>
              <span className="muted mono">
                {node.address || "—"}
                {node.country ? ` · в панели ${node.country}` : ""}
              </span>
            </div>
            <StatusBadge tone={node.status === "online" ? "ok" : node.status === "disabled" ? "idle" : "warn"}>{node.status}</StatusBadge>
          </header>
          {node.warnings.length > 0 && (
            <ul className="intel-warnings">
              {node.warnings.map((w, i) => (
                <li key={i}>
                  <StatusBadge tone={LEVEL[w.level]}>{w.level === "danger" ? "Важно" : w.level === "warn" ? "Внимание" : "Инфо"}</StatusBadge> {w.text}
                </li>
              ))}
            </ul>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>IP</th>
                  <th>Сеть (RIPEstat)</th>
                  <th>Репутация (AbuseIPDB)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {node.addresses.map((a) => {
                  const reg = a.registry?.data;
                  const rep = a.reputation?.data;
                  return (
                    <tr key={a.ip}>
                      <td>
                        <code>{a.ip}</code> <span className="muted">IPv{a.version}</span>
                      </td>
                      <td>
                        {a.private ? (
                          <span className="muted">внутренний адрес — не проверяется</span>
                        ) : a.registry ? (
                          <>
                            {reg ? (
                              <span>
                                {reg.asn ? `AS${reg.asn}` : "ASN нет"} {reg.holder || ""}
                                {reg.prefix ? ` · ${reg.prefix}` : ""}
                                {reg.country ? ` · ${reg.country}` : ""}
                              </span>
                            ) : (
                              <span className="muted">нет данных</span>
                            )}{" "}
                            <StatusBadge tone={FRESH[a.registry.freshness][0]}>{FRESH[a.registry.freshness][1]}</StatusBadge> <span className="muted">{age(a.registry)}</span>
                          </>
                        ) : (
                          <span className="muted">источник выключен</span>
                        )}
                      </td>
                      <td>
                        {a.private ? (
                          "—"
                        ) : a.reputation ? (
                          <>
                            {rep ? (
                              <span>
                                <StatusBadge tone={rep.score >= 50 ? "danger" : rep.score >= 10 ? "warn" : "ok"}>{rep.score}/100</StatusBadge> жалоб {rep.reports}
                                {rep.usage ? ` · ${rep.usage}` : ""}
                                {rep.tor ? " · Tor" : ""}
                              </span>
                            ) : (
                              <span className="muted">нет данных</span>
                            )}{" "}
                            <StatusBadge tone={FRESH[a.reputation.freshness][0]}>{FRESH[a.reputation.freshness][1]}</StatusBadge> <span className="muted">{age(a.reputation)}</span>
                          </>
                        ) : (
                          <span className="muted">не подключено</span>
                        )}
                      </td>
                      <td>
                        {!a.private && view.enabled && (
                          <button type="button" className="ghost" aria-label={`Обновить данные ${a.ip}`} disabled={!!busy} onClick={() => refresh(a.ip)}>
                            <RefreshCw aria-hidden="true" className={busy === a.ip ? "spin" : undefined} />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {node.addresses.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">Адреса не определены</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      ))}

      <section className="card" aria-label="Сети клиентов">
        <h3>
          <ShieldAlert aria-hidden="true" /> Откуда подключаются клиенты · {view.customers.days} дн
        </h3>
        <p className="muted">Сводка по наблюдениям подключений: число клиентов по сети и стране. Отдельные IP-адреса клиентов здесь не показываются.</p>
        <div className="intel-customers">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Сеть</th>
                  <th>Клиентов</th>
                </tr>
              </thead>
              <tbody>
                {view.customers.asns.map((r) => (
                  <tr key={r.asn}>
                    <td>
                      {r.asn === "unknown" ? "не определена" : r.asn} {r.org || ""}
                    </td>
                    <td>{r.users}</td>
                  </tr>
                ))}
                {!view.customers.asns.length && (
                  <tr>
                    <td colSpan={2} className="muted">Наблюдений пока нет</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Страна</th>
                  <th>Клиентов</th>
                </tr>
              </thead>
              <tbody>
                {view.customers.countries.map((r) => (
                  <tr key={r.country}>
                    <td>{r.country}</td>
                    <td>{r.users}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <p className="muted intel-attribution">Источники: RIPEstat Data API (RIPE NCC), AbuseIPDB.</p>
      </section>
    </div>
  );
}
