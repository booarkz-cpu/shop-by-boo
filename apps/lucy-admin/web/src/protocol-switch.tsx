import React, {useEffect, useRef, useState} from "react";
import {ArrowRight, RotateCcw, Wrench} from "lucide-react";
import {StatusBadge} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Inbound = {tag: string; protocol: string; port: number; network: string; security: string; hosts: number; nodes: number; nodes_online: number; switchable: boolean};
type Profile = {uuid: string; name: string; inbounds: Inbound[]};
type Stage = {key: string; title: string; status: string; started_at: string | null; finished_at: string | null; log: string[]};
type NodeRow = {n: number; uuid: string; country: string | null; name: string; online: boolean; disabled: boolean; was_online: boolean | null; transport: string; error: string | null; checked_at: string};
type Job = {id: string; created_at: string; actor: string; profile_name: string; inbound_tag: string; from: string; to: string; status: string; summary: string;
  hosts_updated: number; restored: string[]; nodes: NodeRow[]; checks: number; stages: Stage[]};

const API = "/api/admin/rw/protocol-switch";
const time = (v: string | null) => (v ? new Date(v).toLocaleTimeString("ru-RU") : "—");
const flag = (code: string | null) => (code && /^[A-Z]{2}$/.test(code) ? String.fromCodePoint(...[...code].map((c) => 127397 + c.charCodeAt(0))) : "🌐");
const STAGE: Record<string, [string, "ok" | "warn" | "danger" | "idle"]> = {
  done: ["выполнен", "ok"], running: ["идёт", "warn"], partial: ["частично", "warn"], failed: ["ошибка", "danger"], skipped: ["не требуется", "idle"], pending: ["ожидает", "idle"]};
const JOB: Record<string, [string, "ok" | "warn" | "danger" | "idle"]> = {
  succeeded: ["Успешно", "ok"], partial: ["Частично", "warn"], checking: ["Проверяется", "warn"], switching: ["Выполняется", "warn"], failed: ["Ошибка", "danger"],
  failed_inconsistent: ["Ошибка, состояние не восстановлено", "danger"], rolled_back: ["Возвращён прежний транспорт", "idle"], unchanged: ["Без изменений", "idle"]};
const MAX_CHECKS = 12; // one look every 5 seconds: a minute for the nodes to come back

/** «Починка блока: смена протокола» — four stages with logs, the node table and the way back. */
export function ProtocolSwitch({request, toast}: {request: RequestFn; toast: (m: string) => void}) {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [transports, setTransports] = useState<Record<string, string>>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState("");
  const [tag, setTag] = useState("");
  const [target, setTarget] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [watching, setWatching] = useState(false); // stage 4 is polling: the owner may still press «вернуть»
  const timer = useRef<number | undefined>(undefined);

  async function load() {
    try {
      const d = await request(API);
      setProfiles(d.profiles);
      setTransports(d.transports);
      setJobs(d.jobs);
      setError("");
    } catch (e: any) {
      setError(e.message || "Панель Remnawave не отвечает");
    }
  }
  useEffect(() => {
    load();
    return () => window.clearTimeout(timer.current);
  }, []);

  const chosenProfile = profiles?.find((p) => p.uuid === profile);
  const chosen = chosenProfile?.inbounds.find((i) => i.tag === tag);

  // Stage 4: the page asks the panel again every 5 seconds until all nodes are back or a minute has passed.
  function watch(current: Job, tries: number) {
    window.clearTimeout(timer.current);
    if (current.status === "succeeded" || tries >= MAX_CHECKS) {
      setBusy(false);
      setWatching(false);
      load();
      return;
    }
    setWatching(true);
    timer.current = window.setTimeout(async () => {
      try {
        const next: Job = await request(`${API}/${current.id}/check`, {method: "POST"});
        setJob(next);
        watch(next, tries + 1);
      } catch (e: any) {
        toast(e.message || "Панель не ответила на проверку нод");
        setBusy(false);
        setWatching(false);
      }
    }, tries === 0 ? 1500 : 5000);
  }

  async function start() {
    if (busy || !chosen || !target) return;
    if (!window.confirm(`Перевести inbound ${chosen.tag} с ${transports[chosen.network] || chosen.network} на ${transports[target]}? Клиенты этого inbound переподключатся; им нужно обновить подписку.`)) return;
    setBusy(true);
    try {
      const next: Job = await request(API, {method: "POST", body: JSON.stringify({profile_uuid: profile, inbound_tag: tag, target})});
      setJob(next);
      if (next.status === "checking") watch(next, 0);
      else {
        setBusy(false);
        load();
      }
    } catch (e: any) {
      toast(e.message || "Не удалось запустить смену протокола");
      setBusy(false);
    }
  }
  async function recheck() {
    if (busy || !job) return;
    setBusy(true);
    watch({...job, status: "checking"}, MAX_CHECKS - 1);
  }
  async function rollback() {
    if ((busy && !watching) || !job) return;
    if (!window.confirm(`Вернуть inbound ${job.inbound_tag} на прежний транспорт ${transports[job.from] || job.from}?`)) return;
    setBusy(true);
    setWatching(false);
    window.clearTimeout(timer.current);
    try {
      setJob(await request(`${API}/${job.id}/rollback`, {method: "POST"}));
      toast("Прежний транспорт возвращён");
      await load();
    } catch (e: any) {
      toast(e.message || "Не удалось вернуть прежний транспорт");
    } finally {
      setBusy(false);
    }
  }

  const intro = (
    <>
      <h2><Wrench aria-hidden="true" /> Починка блока: смена протокола</h2>
      <p className="muted">
        Если транспорт перестал работать у клиентов (например, gRPC), inbound переводится на другой: TCP, XHTTP или gRPC.
        Порт, ключи и защита не меняются. Работа идёт в четыре этапа, у каждого свой журнал. Прежние настройки сохраняются и возвращаются одной кнопкой.
      </p>
    </>
  );
  if (error) return (
    <section className="card" data-protocol-switch aria-label="Смена протокола">
      {intro}
      <p role="status"><StatusBadge tone="warn">Нет связи с панелью</StatusBadge> {error}</p>
      <p className="muted">Профили и inbound берутся из панели Remnawave. Подключите магазин к панели, затем нажмите «Повторить».</p>
      <button type="button" className="secondary" onClick={load}>Повторить</button>
    </section>
  );
  if (!profiles) return <p className="muted card">Загрузка…</p>;
  const online = job ? job.nodes.filter((r) => r.online).length : 0;
  const expected = job ? job.nodes.filter((r) => !r.disabled).length : 0;

  return (
    <div className="network-intel" data-protocol-switch>
      <section className="card" aria-label="Смена протокола">
        {intro}
        <label>Профиль
          <select value={profile} disabled={busy} onChange={(e) => { setProfile(e.target.value); setTag(""); setTarget(""); }}>
            <option value="">— выберите профиль —</option>
            {profiles.map((p) => <option key={p.uuid} value={p.uuid}>{p.name}</option>)}
          </select>
        </label>
        {chosenProfile && (
          <label>Inbound
            <select value={tag} disabled={busy} onChange={(e) => { setTag(e.target.value); setTarget(""); }}>
              <option value="">— выберите inbound —</option>
              {chosenProfile.inbounds.map((i) => <option key={i.tag} value={i.tag} disabled={!i.switchable}>{i.tag} — {i.protocol} · {transports[i.network] || i.network} · {i.security}{i.switchable ? "" : " (здесь не переключается)"}</option>)}
            </select>
          </label>
        )}
        {chosen && (
          <>
            <p data-current><strong>Сейчас:</strong> {transports[chosen.network] || chosen.network}, порт {chosen.port}. Hosts: {chosen.hosts}. Нод: {chosen.nodes}, на связи {chosen.nodes_online}.</p>
            <label>Новый транспорт
              <select value={target} disabled={busy} onChange={(e) => setTarget(e.target.value)}>
                <option value="">— выберите транспорт —</option>
                {Object.entries(transports).filter(([key]) => key !== chosen.network).map(([key, title]) => <option key={key} value={key}>{title}</option>)}
              </select>
            </label>
            <p><button type="button" disabled={busy || !target} onClick={start}>{busy ? "Выполняется…" : "Сменить протокол"}</button></p>
          </>
        )}
      </section>

      {job && (
        <section className="card" aria-label="Ход смены протокола" data-job={job.status}>
          <h3>{job.inbound_tag}: {transports[job.from] || job.from || "?"} <ArrowRight aria-hidden="true" /> {transports[job.to] || job.to}</h3>
          <p role="status"><StatusBadge tone={(JOB[job.status] || ["", "idle"])[1]}>{(JOB[job.status] || [job.status])[0]}</StatusBadge> {job.summary}</p>
          <ol className="stage-list">
            {job.stages.map((s) => (
              <li key={s.key} data-stage={s.key} data-status={s.status}>
                <details open={s.status === "failed" || s.status === "running" || s.status === "partial"}>
                  <summary><StatusBadge tone={(STAGE[s.status] || ["", "idle"])[1]}>{(STAGE[s.status] || [s.status])[0]}</StatusBadge> {s.title} <small className="muted">{time(s.started_at)}{s.finished_at ? ` – ${time(s.finished_at)}` : ""}</small></summary>
                  {s.log.length ? <pre className="stage-log">{s.log.join("\n")}</pre> : <p className="muted">Записей пока нет.</p>}
                </details>
              </li>
            ))}
          </ol>
          {job.hosts_updated > 0 && <p>Обновлено hosts: {job.hosts_updated}.</p>}
          {job.restored.length > 0 && <p><strong>Восстановлено:</strong> {job.restored.join("; ")}.</p>}
          {job.nodes.length > 0 && (
            <>
              <h4 data-reconnect>Ноды на связи: {online} из {expected}</h4>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>№</th><th>Нода</th><th>Состояние</th><th>Транспорт</th><th>Причина</th><th>Проверено</th></tr></thead>
                  <tbody>
                    {job.nodes.map((r) => (
                      <tr key={r.uuid} data-node={r.name}>
                        <td>{r.n}</td>
                        <td>{flag(r.country)} {r.name}</td>
                        <td>{r.disabled ? <StatusBadge tone="idle">выключена</StatusBadge> : <StatusBadge tone={r.online ? "ok" : "danger"}>{r.online ? "на связи" : "не на связи"}</StatusBadge>}</td>
                        <td>{transports[r.transport] || r.transport}</td>
                        <td>{r.error || "—"}</td>
                        <td>{time(r.checked_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p>
            {["checking", "partial", "succeeded"].includes(job.status) && <button type="button" className="secondary" disabled={busy} onClick={recheck}>Проверить ещё раз</button>}{" "}
            {["checking", "partial", "succeeded", "failed_inconsistent"].includes(job.status) && <button type="button" className="danger" disabled={busy && !watching} onClick={rollback}><RotateCcw aria-hidden="true" /> Вернуть прежний транспорт</button>}
          </p>
          <p><button type="button" className="secondary" disabled={busy && !watching} onClick={() => { window.clearTimeout(timer.current); setWatching(false); setBusy(false); setJob(null); load(); }}>К списку</button></p>
          {job.status === "partial" && <p className="muted">Что делать: подождите минуту и нажмите «Проверить ещё раз». Если нода не возвращается, откройте «Монитор нод» и посмотрите её журнал; если не возвращается большинство — верните прежний транспорт.</p>}
        </section>
      )}

      {jobs.length > 0 && (
        <section className="card" aria-label="Прошлые запуски">
          <h3>Прошлые запуски</h3>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Когда</th><th>Inbound</th><th>Смена</th><th>Итог</th><th></th></tr></thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td>{new Date(j.created_at).toLocaleString("ru-RU")}</td>
                    <td>{j.profile_name} · {j.inbound_tag}</td>
                    <td>{transports[j.from] || j.from || "?"} → {transports[j.to] || j.to}</td>
                    <td><StatusBadge tone={(JOB[j.status] || ["", "idle"])[1]}>{(JOB[j.status] || [j.status])[0]}</StatusBadge></td>
                    <td><button type="button" className="secondary" disabled={busy} onClick={() => setJob(j)}>Открыть</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
