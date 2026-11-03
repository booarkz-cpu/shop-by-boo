import React, {useEffect, useState} from "react";
import {EmptyState, LoadState} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Props = {request: Request; toast: (text: string) => void};
const API = "/api/admin/telegram";
const json = (method: string, data?: unknown): RequestInit => ({method, body: data === undefined ? undefined : JSON.stringify(data)});
const when = (v?: string | null) => v ? new Date(v).toLocaleString() : "—";
const LANG_NAMES: Record<string, string> = {ru: "Русский (по умолчанию)", en: "English", uk: "Українська"};
const STATE: Record<string, string> = {running: "работает", idle: "ждёт токен", error: "ошибка", unknown: "нет данных"};

/** «Бот и кабинет → Telegram-бот» (v28.71.0, stage 13): whether the bot talks to Telegram, its token without restart,
 *  the command menu on three languages, a test message, statistics and the bot's errors. */
export function TelegramBot({request, toast}: Props) {
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => { setError(""); request(`${API}/status`).then(setD).catch((e: any) => setError(e.message)); };
  useEffect(load, []);
  if (!d) return <LoadState error={error} onRetry={load} label="Загрузка состояния бота…"/>;
  return <div data-telegram-bot>
    <BotStatus d={d} request={request} toast={toast} reload={load}/>
    <Commands request={request} toast={toast} disabled={!d.token_set}/>
    <TestMessage request={request} toast={toast} disabled={!d.token_set}/>
    <BotErrors request={request}/>
  </div>;
}

function BotStatus({d, request, toast, reload}: any) {
  const [live, setLive] = useState<any>(null);
  const [error, setError] = useState("");
  async function check() {
    setError("");
    try { setLive(await request(`${API}/check`, json("POST"))); } catch (e: any) { setError(e.message); }
  }
  async function dropWebhook() {
    setError("");
    try { await request(`${API}/webhook/delete`, json("POST")); toast("Webhook удалён: обновления снова получает бот магазина"); await check(); }
    catch (e: any) { setError(e.message); }
  }
  const level = d.check.status;
  return <section className="card" data-bot-status data-level={level}>
    <h3>Связь с Telegram</h3>
    <p className={level === "ok" ? "success" : level === "off" ? "muted" : "error"} data-bot-check>{d.check.detail}</p>
    {!d.token_set && <EmptyState title="Токен не задан" hint="Получите токен у @BotFather и введите его в «Настройки без перезапуска → Telegram → Токен Telegram-бота». Бот подключится сам за 15 секунд."/>}
    {error && <div role="alert" className="error">{error}</div>}
    <dl className="grid-form" data-bot-facts>
      <div><dt>Бот</dt><dd>{d.username ? `@${d.username}` : "—"}{d.first_name ? ` (${d.first_name})` : ""}</dd></div>
      <div><dt>Состояние процесса</dt><dd>{STATE[d.state] || d.state}</dd></div>
      <div><dt>Последний ответ Telegram</dt><dd>{when(d.last_ok_at)}</dd></div>
      <div><dt>Последнее сообщение от клиента</dt><dd>{when(d.last_update_at)}</dd></div>
      <div><dt>Обновлений получено</dt><dd>{d.updates_total ?? 0}</dd></div>
      <div><dt>Клиентов из Telegram</dt><dd>{d.stats.telegram_users} (за сутки +{d.stats.new_last_day})</dd></div>
      <div><dt>Отпечаток токена</dt><dd><code>{d.token_fingerprint_settings || "—"}</code>{d.token_fingerprint && d.token_fingerprint !== d.token_fingerprint_settings ? " (бот ещё работает со старым токеном)" : ""}</dd></div>
      {d.last_error && <div className="wide"><dt>Последняя ошибка</dt><dd className="error">{d.last_error} · {when(d.last_error_at)}</dd></div>}
    </dl>
    <div className="toolbar">
      <button onClick={reload}>Обновить</button>
      <button className="primary" onClick={check} disabled={!d.token_set}>Проверить сейчас</button>
    </div>
    {live && <div data-bot-live>
      <p>Telegram подтвердил: @{live.username} (id {live.bot_id}). Режим: {live.mode === "webhook" ? `webhook ${live.webhook_url}` : "long polling"}{live.pending_updates ? `, в очереди ${live.pending_updates}` : ""}.</p>
      {live.username_mismatch && <p className="error">Username в настройках ({d.bot_username_setting}) не совпадает с ботом токена (@{live.username}): ссылки на бота поведут не туда.</p>}
      {live.webhook_error && <p className="error">Ошибка webhook: {live.webhook_error}</p>}
      {live.mode === "webhook" && <><p className="muted">Бот магазина получает обновления опросом (long polling). Webhook другого сервера забирает их себе.</p>
        <button className="danger" onClick={dropWebhook}>Удалить webhook</button></>}
    </div>}
  </section>;
}

function Commands({request, toast, disabled}: {request: Request; toast: (t: string) => void; disabled: boolean}) {
  const [data, setData] = useState<any>(null);
  const [lang, setLang] = useState("ru");
  const [error, setError] = useState("");
  useEffect(() => { request(`${API}/commands`).then(setData).catch((e: any) => setError(e.message)); }, []);
  if (!data) return <section className="card"><LoadState error={error} label="Загрузка команд…"/></section>;
  const rows: any[] = data.commands[lang] || [];
  const update = (next: any[]) => setData({...data, commands: {...data.commands, [lang]: next}});
  async function save() {
    setError("");
    try { const out = await request(`${API}/commands`, json("PUT", data.commands)); setData({...data, commands: out.commands, custom: true, applied_at: new Date().toISOString()}); toast("Меню команд обновлено в Telegram"); }
    catch (e: any) { setError(e.message); }
  }
  return <section className="card" data-bot-commands>
    <h3>Меню команд</h3>
    <p className="muted">Кнопка «Меню» в чате с ботом. Список на русском — для всех, у кого язык Telegram не английский и не украинский. Сохранение сразу применяет меню в Telegram (setMyCommands). {data.applied_at ? `Применено: ${when(data.applied_at)}.` : "Сейчас — стандартное меню магазина, ещё не применено."}</p>
    {error && <div role="alert" className="error">{error}</div>}
    <label>Язык<select value={lang} onChange={e => setLang(e.target.value)}>{Object.entries(LANG_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
    <div className="table-wrap"><table><thead><tr><th>Команда</th><th>Описание</th><th></th></tr></thead>
      <tbody>{rows.map((c, i) => <tr key={i} data-command={c.command}>
        <td><input aria-label={`Команда ${i + 1}`} value={c.command} onChange={e => update(rows.map((r, j) => j === i ? {...r, command: e.target.value} : r))}/></td>
        <td><input aria-label={`Описание ${i + 1}`} value={c.description} maxLength={256} onChange={e => update(rows.map((r, j) => j === i ? {...r, description: e.target.value} : r))}/></td>
        <td><button onClick={() => update(rows.filter((_, j) => j !== i))}>Убрать</button>
          {i > 0 && <button aria-label="Выше" onClick={() => { const n = [...rows]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; update(n); }}>↑</button>}</td></tr>)}</tbody></table></div>
    <div className="toolbar">
      <button onClick={() => update([...rows, {command: "", description: ""}])}>Добавить команду</button>
      <button className="primary" onClick={save} disabled={disabled}>Сохранить и применить</button>
    </div>
  </section>;
}

function TestMessage({request, toast, disabled}: {request: Request; toast: (t: string) => void; disabled: boolean}) {
  const [chat, setChat] = useState("");
  const [text, setText] = useState("Проверка связи: бот магазина работает.");
  const [error, setError] = useState("");
  async function send(e: React.FormEvent) {
    e.preventDefault(); setError("");
    try { await request(`${API}/test-message`, json("POST", {chat_id: chat ? Number(chat) : null, text})); toast("Сообщение отправлено"); }
    catch (err: any) { setError(err.message); }
  }
  return <section className="card" data-bot-test>
    <h3>Тестовое сообщение</h3>
    <p className="muted">Бот пишет владельцу («Telegram ID владельца» в настройках) или в указанный чат. Сначала напишите боту /start: Telegram не даёт боту писать первым.</p>
    {error && <div role="alert" className="error">{error}</div>}
    <form onSubmit={send} className="grid-form">
      <label>Chat ID<input value={chat} onChange={e => setChat(e.target.value)} placeholder="пусто — владельцу" inputMode="numeric" pattern="-?[0-9]{4,20}"/></label>
      <label className="wide">Текст<textarea rows={2} maxLength={1000} value={text} onChange={e => setText(e.target.value)}/></label>
      <div className="wide"><button className="primary" disabled={disabled}>Отправить</button></div>
    </form>
  </section>;
}

function BotErrors({request}: {request: Request}) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const load = () => request(`${API}/errors`).then((x: any) => setRows(x.errors)).catch((e: any) => setError(e.message));
  useEffect(() => { load(); }, []);
  return <section className="card" data-bot-errors>
    <h3>Ошибки бота</h3>
    {error && <div role="alert" className="error">{error}</div>}
    {rows && rows.length === 0 && <EmptyState title="Ошибок нет" hint="Ошибки процесса бота попадают сюда и в «Журнал ошибок»."/>}
    {rows && rows.length > 0 && <div className="table-wrap"><table><thead><tr><th>Когда</th><th>Уровень</th><th>Сообщение</th><th>Раз</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.id} data-resolved={r.resolved}><td>{when(r.last_seen)}</td><td>{r.level}</td><td>{r.message}</td><td>{r.count}</td></tr>)}</tbody></table></div>}
  </section>;
}
