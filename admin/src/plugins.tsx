import React, {useEffect, useState} from "react";
import {Copy, KeyRound, Puzzle, RotateCcw, ShieldCheck, Upload} from "lucide-react";
import {SelectField} from "./components/select-field";
import {StatusBadge, type Tone} from "./components/ui/status";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Setting = {key: string; type: "string" | "secret" | "bool" | "int"; label: string; required: boolean; value: any; configured: boolean};
type Version = {version: string; publisher: string; publisher_fingerprint: string; capabilities: string[]; events: string[]; description: string; sha256: string; uploaded_at: string};
type Plugin = {
  id: string;
  name: string;
  state: "installed" | "enabled" | "disabled" | "failing";
  active_version: string | null;
  approved_capabilities: string[];
  approved_events: string[];
  credentials_issued: boolean;
  consecutive_failures: number;
  last_error: string | null;
  disabled_reason: string | null;
  endpoint: string | null;
  settings: Setting[];
  pending_upgrade: {version: string; new_capabilities: string[]; new_events: string[]} | null;
  deliveries_24h: Record<string, number>;
  versions: Version[];
  credentials?: {api_token: string; signing_secret: string};
};
type Data = {plugins: Plugin[]; publishers: {id: number; name: string; fingerprint: string; public_key: string; revoked: boolean}[]; capabilities: Record<string, string>; events: Record<string, string>; api_versions: number[]};

const STATE: Record<Plugin["state"], [Tone, string]> = {
  installed: ["idle", "Загружен, не включён"],
  enabled: ["ok", "Включён"],
  disabled: ["warn", "Выключен"],
  failing: ["danger", "Остановлен из-за ошибок"],
};
const EVENT_LABEL: Record<string, string> = {"user.registered": "Новый клиент", "payment.succeeded": "Успешный платёж", "subscription.activated": "Подписка активирована"};
const DELIVERY: Record<string, string> = {sent: "доставлено", queued: "в очереди", sending: "отправляется", failed: "ошибка", skipped: "пропущено"};

/** Signed plugin packages: trusted publishers, capability approval, versions, settings and credentials. */
export function Plugins({data, request, reload, toast}: {data: Data; request: RequestFn; reload: () => void; toast: (m: string) => void}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [credentials, setCredentials] = useState<{id: string; api_token: string; signing_secret: string} | null>(null);
  const [publisher, setPublisher] = useState({name: "", public_key: ""});
  // The section refreshes itself: a global reload would remount it and lose one-time credentials.
  const [view, setView] = useState<Data>(data);
  useEffect(() => setView(data), [data]);
  const plugins = view?.plugins || [];
  const publishers = view?.publishers || [];
  const capabilities = view?.capabilities || {};

  async function act(fn: () => Promise<any>, message: string) {
    setBusy(true);
    setError("");
    try {
      const result = await fn();
      if (result?.credentials) setCredentials({id: result.id, ...result.credentials});
      toast(message);
      setView(await request("/api/admin/plugins"));
    } catch (e: any) {
      setError(e.status === 403 ? "Действие доступно администратору с правом управления безопасностью." : e.message || "Не удалось выполнить действие");
    } finally {
      setBusy(false);
    }
  }
  const post = (path: string, body?: any) => request(path, {method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});

  async function upload() {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    await act(() => request("/api/admin/plugins/upload", {method: "POST", body: form}), "Пакет проверен и загружен");
    setFile(null);
  }

  return (
    <div className="plugins">
      <section className="card plugins-intro" aria-label="Плагины">
        <h2>
          <Puzzle aria-hidden="true" /> Плагины
        </h2>
        <p className="muted">
          Плагин — внешний HTTPS-сервис. Магазин принимает только пакет с манифестом, подписанный доверенным ключом издателя: код плагина внутри магазина не выполняется. Плагин получает подписанные события и обращается к API только с подтверждёнными правами.
        </p>
        <div className="plugins-upload">
          <label>
            Пакет плагина (.zip до 256 КБ)
            <input type="file" accept=".zip,application/zip" aria-label="Пакет плагина" disabled={busy} onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <button type="button" className="primary" disabled={busy || !file} onClick={upload}>
            <Upload aria-hidden="true" /> Проверить и загрузить
          </button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {credentials && (
        <section className="card plugin-credentials" role="status" aria-label="Учётные данные плагина">
          <h3>
            <KeyRound aria-hidden="true" /> Учётные данные «{credentials.id}» — показываются один раз
          </h3>
          <p className="muted">Передайте их в настройки сервиса плагина. Магазин хранит только хеш токена и зашифрованный секрет подписи; при утере выпустите новые.</p>
          {(["api_token", "signing_secret"] as const).map((key) => (
            <div className="plugin-secret" key={key}>
              <span>{key === "api_token" ? "API-токен" : "Секрет подписи событий"}</span>
              <code>{credentials[key]}</code>
              <button type="button" className="ghost" aria-label={`Скопировать ${key === "api_token" ? "API-токен" : "секрет подписи"}`} onClick={() => navigator.clipboard?.writeText(credentials[key])}>
                <Copy aria-hidden="true" />
              </button>
            </div>
          ))}
          <button type="button" onClick={() => setCredentials(null)}>Я сохранил данные</button>
        </section>
      )}

      {plugins.length === 0 && <p className="muted card">Плагины ещё не загружены.</p>}
      {plugins.map((plugin) => (
        <PluginCard key={plugin.id} plugin={plugin} capabilities={capabilities} busy={busy} act={act} post={post} request={request} />
      ))}

      <section className="card" aria-label="Доверенные издатели">
        <h3>
          <ShieldCheck aria-hidden="true" /> Доверенные издатели
        </h3>
        <p className="muted">Добавляйте только ключи, полученные от издателя по проверенному каналу. Отзыв ключа сразу выключает его плагины.</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Издатель</th>
                <th>Отпечаток</th>
                <th>Статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {publishers.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>
                    <code>{p.fingerprint}</code>
                  </td>
                  <td>{p.revoked ? <StatusBadge tone="danger">Отозван</StatusBadge> : <StatusBadge tone="ok">Активен</StatusBadge>}</td>
                  <td>{!p.revoked && <button type="button" className="ghost" disabled={busy} onClick={() => act(() => post(`/api/admin/plugins/publishers/${p.id}/revoke`), "Ключ отозван")}>Отозвать</button>}</td>
                </tr>
              ))}
              {!publishers.length && (
                <tr>
                  <td colSpan={4} className="muted">Нет доверенных ключей — пакеты не установятся.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="plugins-publisher-form">
          <label>
            Название издателя
            <input value={publisher.name} maxLength={120} onChange={(e) => setPublisher({...publisher, name: e.target.value})} />
          </label>
          <label>
            Открытый ключ Ed25519 (base64)
            <input value={publisher.public_key} maxLength={64} className="mono" onChange={(e) => setPublisher({...publisher, public_key: e.target.value.trim()})} />
          </label>
          <button type="button" disabled={busy || !publisher.name || publisher.public_key.length < 40} onClick={() => act(() => post("/api/admin/plugins/publishers", publisher).then(() => setPublisher({name: "", public_key: ""})), "Ключ издателя добавлен")}>
            Добавить ключ
          </button>
        </div>
      </section>
    </div>
  );
}

function PluginCard({plugin, capabilities, busy, act, post, request}: {plugin: Plugin; capabilities: Record<string, string>; busy: boolean; act: (fn: () => Promise<any>, m: string) => void; post: (p: string, b?: any) => Promise<any>; request: RequestFn}) {
  const latest = plugin.versions[0];
  const [version, setVersion] = useState(plugin.pending_upgrade?.version || plugin.active_version || latest?.version || "");
  const [approved, setApproved] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [values, setValues] = useState<Record<string, any>>({});
  useEffect(() => setApproved(false), [version]);
  const selected = plugin.versions.find((v) => v.version === version) || latest;
  const [tone, label] = STATE[plugin.state];
  const root = `/api/admin/plugins/${encodeURIComponent(plugin.id)}`;
  const isActive = plugin.state === "enabled" && selected?.version === plugin.active_version;

  return (
    <article className="card plugin-card" aria-label={`Плагин ${plugin.name}`}>
      <header className="plugin-head">
        <div>
          <h3>{plugin.name}</h3>
          <span className="muted mono">
            {plugin.id} · {plugin.active_version ? `версия ${plugin.active_version}` : "не включён"}
          </span>
        </div>
        <StatusBadge tone={tone}>{label}</StatusBadge>
      </header>
      {plugin.disabled_reason && plugin.state !== "enabled" && <p className="muted">{plugin.disabled_reason}</p>}
      {plugin.last_error && <p className="error">Последняя ошибка доставки: {plugin.last_error}</p>}
      <p className="muted">
        Адрес событий: <code>{plugin.endpoint}</code> · за 24 часа: {Object.entries(plugin.deliveries_24h).map(([k, v]) => `${DELIVERY[k] || k} ${v}`).join(", ") || "нет событий"}
      </p>
      {plugin.pending_upgrade && plugin.active_version && (
        <p className="plugin-upgrade" role="status">
          Доступна версия {plugin.pending_upgrade.version}.{" "}
          {plugin.pending_upgrade.new_capabilities.length ? `Она запрашивает новые права: ${plugin.pending_upgrade.new_capabilities.join(", ")} — до подтверждения работает прежняя версия.` : "Новых прав не требует."}
        </p>
      )}

      <div className="plugin-grid">
        <section aria-label="Права версии">
          <label>
            Версия
            <SelectField aria-label={`Версия плагина ${plugin.name}`} value={version} disabled={busy} onChange={(e) => setVersion(e.target.value)}>
              {plugin.versions.map((v) => (
                <option key={v.version} value={v.version}>
                  {v.version}
                  {v.version === plugin.active_version ? " (активна)" : ""}
                </option>
              ))}
            </SelectField>
          </label>
          {selected && (
            <>
              <p className="muted">
                Издатель {selected.publisher || "—"} · ключ <code>{selected.publisher_fingerprint}</code>
              </p>
              {selected.description && <p>{selected.description}</p>}
              <ul className="plugin-caps">
                {selected.capabilities.map((c) => (
                  <li key={c} data-new={!plugin.approved_capabilities.includes(c) || undefined}>
                    <b>{c}</b> — {capabilities[c] || c}
                  </li>
                ))}
                {selected.events.map((e) => (
                  <li key={e}>
                    событие <b>{EVENT_LABEL[e] || e}</b>
                  </li>
                ))}
                {!selected.capabilities.length && <li>Без доступа к данным</li>}
              </ul>
              {!isActive && (
                <>
                  <label className="check">
                    <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
                    Разрешаю плагину эти права и события
                  </label>
                  <div className="inline">
                    <button type="button" className="primary" disabled={busy || !approved} onClick={() => act(() => post(`${root}/enable`, {version: selected.version, capabilities: selected.capabilities, events: selected.events}), `Плагин включён: версия ${selected.version}`)}>
                      Включить версию {selected.version}
                    </button>
                    {plugin.active_version && selected.version !== plugin.active_version && (
                      <button type="button" disabled={busy} onClick={() => act(() => post(`${root}/rollback`, {version: selected.version}), `Активна версия ${selected.version}`)}>
                        <RotateCcw aria-hidden="true" /> Вернуть эту версию
                      </button>
                    )}
                  </div>
                </>
              )}
            </>
          )}
        </section>

        <section aria-label="Настройки плагина">
          <h4>Настройки</h4>
          {plugin.settings.length === 0 && <p className="muted">Плагин не требует настроек.</p>}
          {plugin.settings.map((s) => (
            <label key={s.key} className={s.type === "bool" ? "check" : undefined}>
              {s.type === "bool" ? (
                <input type="checkbox" checked={values[s.key] ?? Boolean(s.value)} onChange={(e) => setValues({...values, [s.key]: e.target.checked})} />
              ) : null}
              {s.label}
              {s.required ? " *" : ""}
              {s.type !== "bool" && (
                <input
                  type={s.type === "secret" ? "password" : s.type === "int" ? "number" : "text"}
                  autoComplete="off"
                  value={values[s.key] ?? (s.type === "secret" ? "" : s.value ?? "")}
                  placeholder={s.type === "secret" && s.configured ? "Задан — оставьте пустым, чтобы не менять" : ""}
                  onChange={(e) => setValues({...values, [s.key]: e.target.value})}
                />
              )}
            </label>
          ))}
          {plugin.settings.length > 0 && (
            <button type="button" disabled={busy || !Object.keys(values).length} onClick={() => act(() => post(`${root}/settings`, {values}).then((r) => (setValues({}), r)), "Настройки сохранены")}>
              Сохранить настройки
            </button>
          )}
        </section>
      </div>

      <footer className="inline plugin-actions">
        {plugin.state === "enabled" && (
          <button type="button" disabled={busy} onClick={() => act(() => post(`${root}/disable`), "Плагин выключен")}>
            Выключить
          </button>
        )}
        {plugin.credentials_issued && (
          <button type="button" disabled={busy} onClick={() => act(() => post(`${root}/rotate`), "Выпущены новые учётные данные")}>
            <KeyRound aria-hidden="true" /> Выпустить новые ключи
          </button>
        )}
        <label className="check">
          <input type="checkbox" checked={confirmRemove} onChange={(e) => setConfirmRemove(e.target.checked)} />
          Удалить плагин, его версии и журнал доставок
        </label>
        <button type="button" className="danger" disabled={busy || !confirmRemove} onClick={() => act(() => request(root, {method: "DELETE"}), "Плагин удалён")}>
          Удалить
        </button>
      </footer>
    </article>
  );
}
