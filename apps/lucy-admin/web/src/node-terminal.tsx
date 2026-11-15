import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {Plus, Power, ScrollText, SquareTerminal, Trash2, X} from "lucide-react";
import {StatusBadge, type Tone} from "./components/ui/status";
import {Screen, keyToInput, type Cell} from "./terminal-screen";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Agent = {id: number; name: string; enabled: boolean; terminal_ready: boolean; online: boolean; last_seen_at: string | null};
type Session = {id: string; node: string; admin: string; reason: string; status: "requested" | "active" | "closed"; close_reason: string | null; created_at: string; closed_at: string | null; expires_at: string; bytes_in: number; bytes_out: number; exit_code: number | null};
type Snippet = {id: number; name: string; command: string};
type View = {
  enabled: boolean;
  mfa_enabled: boolean;
  can_audit: boolean;
  limits: {max_minutes: number; idle_minutes: number; transcript_days: number; per_node: number; per_admin: number; total: number};
  agents: Agent[];
  sessions: Session[];
  snippets: Snippet[];
};

const STATUS: Record<string, [Tone, string]> = {requested: ["warn", "ждёт узел"], active: ["ok", "открыта"], closed: ["idle", "закрыта"]};
const when = (value: string | null) => (value ? new Date(value + (value.endsWith("Z") ? "" : "Z")).toLocaleString("ru-RU", {dateStyle: "short", timeStyle: "medium"}) : "—");
/** Transcript text without terminal control sequences (colors, cursor moves, titles). */
export function readable(text: string): string {
  return text
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b\[[0-?]*[ -\/]*[@-~]/g, "")
    .replace(/\x1b[()*+][A-Za-z0-9]/g, "")
    .replace(/\x1b[=>78DEMc]/g, "")
    .replace(/\r\n/g, "\n")
    .replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
}
const CELL_W = 8.43;
const CELL_H = 18;

function fromBase64(value: string): Uint8Array {
  const raw = atob(value);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

function spans(line: Cell[], cursorX: number | null) {
  const out: React.ReactNode[] = [];
  let start = 0;
  const key = (c: Cell, x: number) => `${c.fg}|${c.bg}|${c.bold}|${c.dim}|${c.underline}|${c.inverse}|${x === cursorX}`;
  for (let x = 1; x <= line.length; x += 1) {
    if (x < line.length && key(line[x], x) === key(line[start], start)) continue;
    const c = line[start];
    const fg = c.inverse ? c.bg || "var(--term-bg)" : c.fg || undefined;
    const bg = c.inverse ? c.fg || "var(--term-fg)" : c.bg || undefined;
    out.push(
      <span key={start} className={start === cursorX ? "term-cursor" : undefined}
        style={{color: fg, background: bg, fontWeight: c.bold ? 700 : undefined, opacity: c.dim ? 0.7 : undefined, textDecoration: c.underline ? "underline" : undefined}}>
        {line.slice(start, x).map((cell) => cell.ch).join("")}
      </span>,
    );
    start = x;
  }
  return out;
}

/** One live session: long-polls output, batches keystrokes, keeps the screen size in sync. */
function TerminalWindow({session, request, snippets, onClosed}: {session: Session; request: RequestFn; snippets: Snippet[]; onClosed: (reason: string) => void}) {
  const screen = useMemo(() => new Screen(120, 32), [session.id]);
  const [, setFrame] = useState(0);
  const [status, setStatus] = useState(session.status);
  const [reason, setReason] = useState("");
  const [focused, setFocused] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const queue = useRef("");
  const timer = useRef<number | null>(null);
  const alive = useRef(true);
  const stick = useRef(true);

  const post = useCallback(async (body: Record<string, unknown>) => {
    seq.current += 1;
    const payload = JSON.stringify({seq: seq.current, ...body});
    for (let attempt = 0; attempt < 4; attempt += 1) {
      try {
        await request(`/api/admin/terminal/sessions/${session.id}/input`, {method: "POST", body: payload});
        return;
      } catch (e: any) {
        if (e.status === 410 || e.status === 409 || e.status === 404) return;
        await new Promise((r) => setTimeout(r, 400 * (attempt + 1))); // same seq: the server ignores repeats
      }
    }
  }, [request, session.id]);

  const send = useCallback((data: string) => {
    queue.current += data;
    if (timer.current !== null) return;
    timer.current = window.setTimeout(() => {
      const chunk = queue.current;
      queue.current = "";
      timer.current = null;
      if (chunk) void post({data: chunk});
    }, 25);
  }, [post]);

  useEffect(() => {
    screen.onReply = (data) => send(data);
  }, [screen, send]);

  useEffect(() => {
    alive.current = true;
    const decoder = new TextDecoder("utf-8");
    let cursor = "";
    let raf = 0;
    const redraw = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        setFrame((n) => n + 1);
        if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight;
      });
    };
    (async () => {
      while (alive.current) {
        try {
          const result = await request(`/api/admin/terminal/sessions/${session.id}/output?cursor=${encodeURIComponent(cursor)}&wait=20`);
          cursor = result.cursor;
          for (const chunk of result.chunks || []) {
            if (chunk.k === "data") screen.write(decoder.decode(fromBase64(chunk.d), {stream: true}));
            if (chunk.k === "opened") setStatus("active");
          }
          if (result.chunks?.length) redraw();
          setStatus(result.status);
          if (result.status === "closed" && !result.chunks?.length) {
            setReason(result.close_reason || "");
            onClosed(result.close_reason || "Сессия закрыта");
            return;
          }
        } catch (e: any) {
          if (e.status === 404 || e.status === 403 || e.status === 401) {
            setStatus("closed");
            setReason(e.message);
            return;
          }
          await new Promise((r) => setTimeout(r, 1500));
        }
      }
    })();
    return () => {
      alive.current = false;
      cancelAnimationFrame(raf);
    };
  }, [request, screen, session.id, onClosed]);

  // Fit the screen to the window and tell the node.
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    let last = "";
    const fit = () => {
      const cols = Math.max(20, Math.min(400, Math.floor((element.clientWidth - 16) / CELL_W)));
      const rows = Math.max(5, Math.min(200, Math.floor((element.clientHeight - 12) / CELL_H)));
      const size = `${cols}x${rows}`;
      if (size === last) return;
      last = size;
      screen.resize(cols, rows);
      setFrame((n) => n + 1);
      if (status === "active") void post({cols, rows});
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    return () => observer.disconnect();
  }, [screen, post, status]);

  function onKey(event: React.KeyboardEvent) {
    if (status !== "active") return;
    const data = keyToInput(event.nativeEvent, screen.appCursor);
    if (data === null) return;
    event.preventDefault();
    stick.current = true;
    send(data);
  }

  function onPaste(event: React.ClipboardEvent) {
    if (status !== "active") return;
    event.preventDefault();
    const text = event.clipboardData.getData("text").replace(/\r?\n/g, "\r");
    send(screen.bracketedPaste ? `\x1b[200~${text}\x1b[201~` : text);
  }

  const rows = screen.altScreen ? screen.lines : [...screen.scrollback, ...screen.lines];
  const offset = rows.length - screen.lines.length;
  return (
    <section className="card term-window" aria-label={`Терминал узла ${session.node}`}>
      <header className="term-head">
        <div>
          <h3>
            <SquareTerminal aria-hidden="true" /> {session.node}
          </h3>
          <span className="muted">
            {screen.title || session.reason} · до {when(session.expires_at)}
          </span>
        </div>
        <StatusBadge tone={STATUS[status][0]}>{status === "requested" ? "ждём подключения узла…" : STATUS[status][1]}</StatusBadge>
        {snippets.length > 0 && status === "active" && (
          <label className="term-snippet">
            <span>Сниппет</span>
            <select value="" onChange={(e) => { const s = snippets.find((x) => String(x.id) === e.target.value); if (s) { send(s.command); box.current?.focus(); } }}>
              <option value="">Вставить…</option>
              {snippets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {status !== "closed" && (
          <button type="button" className="danger" onClick={() => request(`/api/admin/terminal/sessions/${session.id}/close`, {method: "POST"}).catch(() => undefined)}>
            <Power aria-hidden="true" /> Закрыть сессию
          </button>
        )}
      </header>
      <div
        ref={box}
        className="term-screen"
        role="textbox"
        aria-label="Экран терминала. Нажмите, чтобы вводить команды."
        aria-multiline="true"
        tabIndex={0}
        onKeyDown={onKey}
        onPaste={onPaste}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 4; }}
      >
        {rows.map((line, i) => (
          <div key={i} className="term-line">
            {spans(line, focused && screen.cursorVisible && status === "active" && i - offset === screen.y ? screen.x : null)}
          </div>
        ))}
      </div>
      {status === "closed" && <p className="muted">Сессия закрыта{reason ? `: ${reason}` : ""}.</p>}
    </section>
  );
}

/** Interactive shell on a node through its agent: confirmation, live terminal, snippets, transcripts. */
export function NodeTerminal({data, request, toast}: {data: View; request: RequestFn; toast: (m: string) => void}) {
  const [view, setView] = useState<View>(data);
  const [target, setTarget] = useState<Agent | null>(null);
  const [form, setForm] = useState({reason: "", password: "", code: ""});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Session | null>(null);
  const [transcript, setTranscript] = useState<any>(null);
  const [snippet, setSnippet] = useState({name: "", command: ""});
  useEffect(() => setView(data), [data]);
  const reload = useCallback(async () => setView(await request("/api/admin/terminal")), [request]);
  const closed = useCallback((reason: string) => {
    toast(`Сессия закрыта: ${reason}`);
    void reload();
  }, [toast, reload]);
  if (!view?.limits) return <p className="muted card">Загрузка терминала…</p>;

  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (!target) return;
    setBusy(true);
    setError("");
    try {
      const session = await request("/api/admin/terminal/sessions", {method: "POST", body: JSON.stringify({agent_id: target.id, ...form, cols: 120, rows: 32})});
      setOpen(session);
      setTarget(null);
      setForm({reason: "", password: "", code: ""});
      void reload();
    } catch (e: any) {
      setError(e.message || "Сессия не открылась");
    } finally {
      setBusy(false);
    }
  }

  async function addSnippet(event: React.FormEvent) {
    event.preventDefault();
    try {
      await request("/api/admin/terminal/snippets", {method: "POST", body: JSON.stringify(snippet)});
      setSnippet({name: "", command: ""});
      toast("Сниппет сохранён");
      void reload();
    } catch (e: any) {
      setError(e.message);
    }
  }

  const ready = view.enabled && view.mfa_enabled;
  return (
    <div className="network-intel node-terminal">
      <section className="card" aria-label="Терминал узлов">
        <h2>
          <SquareTerminal aria-hidden="true" /> Терминал узлов
        </h2>
        <p className="muted">
          Полная командная оболочка на VPN-сервере через агент узла. Магазин не подключается к узлу: агент сам забирает ввод и отправляет вывод. Каждая сессия подтверждается паролем и кодом двухфакторного входа, весь ввод и вывод записываются в зашифрованный журнал; ввод при выключенном эхо (пароли) не сохраняется.
        </p>
        <ul className="intel-warnings">
          <li>
            <StatusBadge tone={view.enabled ? "ok" : "idle"}>{view.enabled ? "Включён" : "Выключен"}</StatusBadge>{" "}
            {view.enabled ? "TERMINAL_ENABLED=true на сервере магазина." : "Включается только в .env сервера: TERMINAL_ENABLED=true и перезапуск backend."}
          </li>
          <li>
            <StatusBadge tone={view.mfa_enabled ? "ok" : "warn"}>{view.mfa_enabled ? "2FA включён" : "Нужен 2FA"}</StatusBadge>{" "}
            {view.mfa_enabled ? "Сессию подтверждают пароль и код из приложения." : "Включите двухфакторный вход в разделе «Защита и 2FA»."}
          </li>
          <li className="muted">
            Сессия длится до {view.limits.max_minutes} мин и закрывается после {view.limits.idle_minutes} мин без ввода. Одновременно: {view.limits.per_node} на узел, {view.limits.per_admin} у администратора, {view.limits.total} всего. Журналы хранятся {view.limits.transcript_days} дн.
          </li>
        </ul>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {open && <TerminalWindow key={open.id} session={open} request={request} snippets={view.snippets} onClosed={closed} />}

      <section className="card" aria-label="Узлы">
        <h3>Узлы</h3>
        <p className="muted">Терминал доступен на узлах, где агент запущен с AGENT_TERMINAL=1. Агенты создаются в разделе «Антиабуз и агенты».</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Узел</th>
                <th>Агент</th>
                <th>Терминал на узле</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {view.agents.map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td>
                    <StatusBadge tone={!a.enabled ? "idle" : a.online ? "ok" : "warn"}>{!a.enabled ? "отключён" : a.online ? "на связи" : "нет связи"}</StatusBadge>
                  </td>
                  <td>{a.terminal_ready ? "разрешён" : "не включён (AGENT_TERMINAL=1)"}</td>
                  <td>
                    <button type="button" disabled={!ready || !a.enabled || !a.online || !a.terminal_ready} onClick={() => { setTarget(a); setError(""); }}>
                      Открыть терминал
                    </button>
                  </td>
                </tr>
              ))}
              {view.agents.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    Агентов пока нет.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {target && (
          <form className="term-confirm" onSubmit={start} aria-label={`Подтверждение сессии на ${target.name}`}>
            <h4>Открыть терминал на {target.name}</h4>
            <label>
              <span>Зачем нужен доступ (попадёт в журнал)</span>
              <input required minLength={3} maxLength={255} value={form.reason} onChange={(e) => setForm({...form, reason: e.target.value})} placeholder="например, проверить журнал xray" />
            </label>
            <div className="grid2">
              <label>
                <span>Пароль администратора</span>
                <input required type="password" autoComplete="current-password" value={form.password} onChange={(e) => setForm({...form, password: e.target.value})} />
              </label>
              <label>
                <span>Код из приложения 2FA</span>
                <input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,8}" maxLength={8} value={form.code} onChange={(e) => setForm({...form, code: e.target.value})} />
              </label>
            </div>
            <div className="term-actions">
              <button type="submit" disabled={busy}>
                <SquareTerminal aria-hidden="true" /> Подтвердить и открыть
              </button>
              <button type="button" className="secondary" onClick={() => setTarget(null)}>
                Отмена
              </button>
            </div>
          </form>
        )}
      </section>

      <section className="card" aria-label="Сниппеты">
        <h3>Сниппеты</h3>
        <p className="muted">Сохранённые команды вставляются в открытую сессию без нажатия Enter, чтобы их можно было проверить. Вставка попадает в журнал как обычный ввод.</p>
        {view.snippets.length > 0 && (
          <ul className="intel-warnings">
            {view.snippets.map((s) => (
              <li key={s.id} className="term-snippet-row">
                <strong>{s.name}</strong> <code>{s.command}</code>
                <button type="button" className="secondary" aria-label={`Удалить сниппет ${s.name}`} onClick={() => request(`/api/admin/terminal/snippets/${s.id}/delete`, {method: "POST"}).then(reload).catch((e: any) => setError(e.message))}>
                  <Trash2 aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <form className="mail-check-form" onSubmit={addSnippet}>
          <label>
            <span>Название</span>
            <input required maxLength={80} value={snippet.name} onChange={(e) => setSnippet({...snippet, name: e.target.value})} placeholder="Статус xray" />
          </label>
          <label>
            <span>Команда</span>
            <input required maxLength={2000} value={snippet.command} onChange={(e) => setSnippet({...snippet, command: e.target.value})} placeholder="systemctl status xray --no-pager" />
          </label>
          <button type="submit">
            <Plus aria-hidden="true" /> Сохранить
          </button>
        </form>
      </section>

      <section className="card" aria-label="Журнал сессий">
        <h3>Журнал сессий</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Узел</th>
                <th>Администратор</th>
                <th>Причина</th>
                <th>Начало</th>
                <th>Состояние</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {view.sessions.map((s) => (
                <tr key={s.id}>
                  <td>{s.node}</td>
                  <td>{s.admin}</td>
                  <td>{s.reason}</td>
                  <td>{when(s.created_at)}</td>
                  <td>
                    <StatusBadge tone={STATUS[s.status][0]}>{STATUS[s.status][1]}</StatusBadge> {s.close_reason && <span className="muted">{s.close_reason}</span>}
                  </td>
                  <td className="term-actions">
                    {s.status !== "closed" && !open && (
                      <button type="button" className="secondary" onClick={() => setOpen(s)}>
                        Вернуться
                      </button>
                    )}
                    {view.can_audit && (
                      <button type="button" className="secondary" onClick={() => request(`/api/admin/terminal/sessions/${s.id}/transcript`).then(setTranscript).catch((e: any) => setError(e.message))}>
                        <ScrollText aria-hidden="true" /> Журнал
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {view.sessions.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    Сессий ещё не было.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {transcript && (
          <div className="mail-opened">
            <h4>
              {transcript.node}: {transcript.reason} ({transcript.admin}) <button type="button" className="secondary" aria-label="Закрыть журнал" onClick={() => setTranscript(null)}><X aria-hidden="true" /></button>
            </h4>
            <pre className="term-transcript">
              {transcript.chunks.map((c: any, i: number) => (
                <span key={i} className={`term-t-${c.direction}`}>
                  {c.direction === "event" ? `\n[${when(c.at)}] ${c.text}\n` : readable(c.text)}
                </span>
              ))}
            </pre>
            <p className="muted">Ввод выделен цветом; скрытый ввод записан только как длина. Просмотр журнала записан в журнал действий.</p>
          </div>
        )}
      </section>
    </div>
  );
}
