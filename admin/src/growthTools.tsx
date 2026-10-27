import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

/** «Рефералы → Бонус днями»: приведи друга — получи +N дней к подписке. */
export function ReferralBonus({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [cfg, setCfg] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/referrals/bonus").then(setCfg).catch(e => setError(e.message)); }, [request]);
  async function save() {
    try {
      const out = await request("/api/admin/referrals/bonus", {method: "PUT", body: JSON.stringify({enabled: cfg.enabled, days: Number(cfg.days), first_payment_only: cfg.first_payment_only})});
      setCfg({...cfg, ...out});
      toast("Бонус за друга сохранён");
    } catch (e: any) { setError(e.message); }
  }
  if (!cfg) return <div className="card"><h3>Бонус днями за друга</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  return (
    <div className="card">
      <h3>Бонус днями за друга</h3>
      {error ? <p className="error">{error}</p> : null}
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={e => setCfg({...cfg, enabled: e.target.checked})}/> Начислять дни пригласившему</label>
      <label>Дней за друга<input type="number" min={1} max={365} value={cfg.days} onChange={e => setCfg({...cfg, days: e.target.value})}/></label>
      <label className="check"><input type="checkbox" checked={cfg.first_payment_only} onChange={e => setCfg({...cfg, first_payment_only: e.target.checked})}/> Только за первую оплату друга</label>
      <p className="muted">Подписка пригласившего продлевается на панели автоматически; без подписки — он получает подарочный код. Начислено: {cfg.granted ?? 0}.</p>
      <button className="primary" onClick={save}>Сохранить</button>
    </div>
  );
}

/** «Маркетинг → Генератор промокодов»: пачка одноразовых кодов с одинаковыми условиями и выгрузка в CSV. */
export function PromoGenerator({request, toast, reload}: {request: Request; toast: (text: string) => void; reload?: () => void}) {
  const [form, setForm] = useState({count: 50, prefix: "", kind: "percent", value: 20, usage_limit: 1, ends_at: ""});
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const set = (patch: any) => setForm({...form, ...patch});
  async function generate() {
    setError("");
    try {
      const out = await request("/api/admin/promo-codes/generate", {method: "POST", body: JSON.stringify({
        count: Number(form.count), prefix: form.prefix, kind: form.kind, value: Number(form.value), usage_limit: Number(form.usage_limit),
        ends_at: form.ends_at ? new Date(form.ends_at).toISOString() : null})});
      setCodes(out.codes);
      toast(`Создано кодов: ${out.count}`);
      reload?.();
    } catch (e: any) { setError(e.message); }
  }
  function download() {
    const blob = new Blob(["code\n" + codes.join("\n")], {type: "text/csv"});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `promo-${form.prefix || "codes"}.csv`;
    link.click();
  }
  return (
    <div className="card">
      <h3>Генератор промокодов</h3>
      {error ? <p className="error">{error}</p> : null}
      <div className="inline">
        <label className="field">Количество<input type="number" min={1} max={1000} value={form.count} onChange={e => set({count: e.target.value})}/></label>
        <label className="field">Префикс<input placeholder="BLACKFRIDAY" value={form.prefix} onChange={e => set({prefix: e.target.value.toUpperCase()})}/></label>
      </div>
      <div className="inline">
        <label className="field">Тип<select value={form.kind} onChange={e => set({kind: e.target.value})}><option value="percent">Процент</option><option value="fixed">Сумма, ₽</option></select></label>
        <label className="field">Скидка<input type="number" value={form.value} onChange={e => set({value: e.target.value})}/></label>
        <label className="field">Использований на код<input type="number" min={1} value={form.usage_limit} onChange={e => set({usage_limit: e.target.value})}/></label>
        <label className="field">Действует до<input type="date" value={form.ends_at} onChange={e => set({ends_at: e.target.value})}/></label>
      </div>
      <button className="primary" onClick={generate}>Сгенерировать</button>
      {codes.length ? <>
        <p className="muted">Коды созданы и уже работают. Каждый — на {form.usage_limit} использование(й), один раз на клиента.</p>
        <textarea readOnly rows={6} value={codes.join("\n")}/>
        <button onClick={download}>Скачать CSV</button>
      </> : null}
    </div>
  );
}

/** «Резервные копии → Копия базы в Telegram»: ежедневный зашифрованный дамп в личный чат владельца. */
export function TelegramBackup({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [cfg, setCfg] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { request("/api/admin/backups/telegram").then(setCfg).catch(e => setError(e.message)); }, [request]);
  async function save() {
    try {
      setCfg({...cfg, ...(await request("/api/admin/backups/telegram", {method: "PUT", body: JSON.stringify({enabled: cfg.enabled, chat_id: cfg.chat_id, time: cfg.time})}))});
      toast("Расписание копий в Telegram сохранено");
    } catch (e: any) { setError(e.message); }
  }
  async function sendNow() {
    setBusy(true);
    try {
      const out = await request("/api/admin/backups/telegram/send-now", {method: "POST"});
      toast(`Копия отправлена: ${out.parts} файл(ов)`);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  if (!cfg) return <div className="card"><h3>Копия базы в Telegram</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  return (
    <div className="card">
      <h3>Копия базы в Telegram</h3>
      {error ? <p className="error">{error}</p> : null}
      {!cfg.password_configured ? <div className="alert">Сначала задайте пароль шифрования копий выше: база отправляется только зашифрованной.</div> : null}
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={e => setCfg({...cfg, enabled: e.target.checked})}/> Отправлять каждый день</label>
      <label>ID закрытого чата или канала<input placeholder="-1001234567890" value={cfg.chat_id} onChange={e => setCfg({...cfg, chat_id: e.target.value.trim()})}/></label>
      <label>Время (МСК)<input type="time" value={cfg.time} onChange={e => setCfg({...cfg, time: e.target.value})}/></label>
      {cfg.last_result ? <p className="muted">Последняя: {cfg.last_result}</p> : null}
      <div className="toolbar"><button className="primary" onClick={save}>Сохранить</button><button disabled={busy} onClick={sendNow}>Отправить сейчас</button></div>
      <p className="muted">Бот должен быть участником чата. Файлы больше 45 МБ делятся на части; восстановление — docs/ru/modules/30-backups-recovery.md.</p>
    </div>
  );
}

/** «Фрод → Анти-шеринг»: подписка на большем числе устройств, чем разрешает тариф. */
export function AntiSharing({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [cfg, setCfg] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/anti-sharing").then(setCfg).catch(e => setError(e.message)); }, [request]);
  async function save() {
    try {
      setCfg({...cfg, ...(await request("/api/admin/anti-sharing", {method: "PUT", body: JSON.stringify({enabled: cfg.enabled, action: cfg.action, tolerance: Number(cfg.tolerance)})}))});
      toast("Анти-шеринг сохранён");
    } catch (e: any) { setError(e.message); }
  }
  if (!cfg) return <div className="card"><h3>Анти-шеринг</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  return (
    <div className="card">
      <h3>Анти-шеринг: лимит устройств</h3>
      {error ? <p className="error">{error}</p> : null}
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={e => setCfg({...cfg, enabled: e.target.checked})}/> Проверять каждые 15 минут</label>
      <label>При превышении<select value={cfg.action} onChange={e => setCfg({...cfg, action: e.target.value})}>
        <option value="reset">Сбросить устройства и предупредить клиента</option>
        <option value="block">Отключить конфиг до проверки оператором</option>
      </select></label>
      <label>Допуск сверх лимита<input type="number" min={0} max={5} value={cfg.tolerance} onChange={e => setCfg({...cfg, tolerance: e.target.value})}/></label>
      <button className="primary" onClick={save}>Сохранить</button>
      <p className="muted">Устройства берутся из Remnawave (HWID). Включите в панели HWID_DEVICE_LIMIT_ENABLED — тогда лишние устройства не подключатся вовсе. Снять блокировку: «Платформа → Нарушения».</p>
      {cfg.recent?.length ? <ul>{cfg.recent.map((v: any) => <li key={v.id}>{new Date(v.created_at).toLocaleString("ru-RU")} — {v.summary} ({v.status})</li>)}</ul> : null}
    </div>
  );
}

/** «Поддержка → База знаний ИИ-ассистента»: вопросы и ответы, по которым готовятся черновики. */
export function SupportKnowledge({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [items, setItems] = useState<{question: string; answer: string}[]>([]);
  const [info, setInfo] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { request("/api/admin/support/ai").then(d => { setItems(d.items || []); setInfo(d); }).catch(e => setError(e.message)); }, [request]);
  const change = (index: number, patch: any) => setItems(items.map((x, i) => (i === index ? {...x, ...patch} : x)));
  async function save() {
    try {
      await request("/api/admin/support/ai", {method: "PUT", body: JSON.stringify({items: items.filter(x => x.question.trim() && x.answer.trim())})});
      toast("База знаний сохранена");
    } catch (e: any) { setError(e.message); }
  }
  return (
    <details className="card">
      <summary><b>База знаний ИИ-ассистента</b> · {info?.llm_configured ? `модель ${info.model}` : "модель не подключена — черновики из базы знаний"}</summary>
      {error ? <p className="error">{error}</p> : null}
      {items.map((item, i) => (
        <div className="grid2" key={i}>
          <label>Вопрос<input value={item.question} onChange={e => change(i, {question: e.target.value})}/></label>
          <label>Ответ<textarea rows={2} value={item.answer} onChange={e => change(i, {answer: e.target.value})}/></label>
          <button onClick={() => setItems(items.filter((_, j) => j !== i))}>Удалить</button>
        </div>
      ))}
      <div className="toolbar"><button onClick={() => setItems([...items, {question: "", answer: ""}])}>Добавить вопрос</button><button className="primary" onClick={save}>Сохранить</button></div>
      <p className="muted">Подключение модели: «Настройки без перезапуска → Поддержка» (адрес API, ключ, модель). Страница FAQ тоже используется.</p>
    </details>
  );
}

/** «Мобильные приложения → Резервные адреса»: ротация домена API и сайты в обход VPN. */
export function MobileMirrors({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [cfg, setCfg] = useState<any>(null);
  const [text, setText] = useState({mirrors: "", bootstrap: "", direct: "", token: ""});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lines = (value: string) => value.split(/[\s,]+/).map(x => x.trim()).filter(Boolean);
  function show(next: any) {
    setCfg(next);
    setText({mirrors: (next.mirrors || []).join("\n"), bootstrap: (next.bootstrap || []).join("\n"), direct: (next.direct_domains || []).join("\n"), token: ""});
  }
  useEffect(() => { request("/api/admin/mobile/mirrors").then(show).catch(e => setError(e.message)); }, [request]);
  async function save() {
    setError("");
    try {
      const body: any = {mirrors: lines(text.mirrors), bootstrap: lines(text.bootstrap), direct_domains: lines(text.direct), gist_id: (cfg.gist_id || "").trim()};
      if (text.token) body.gist_token = text.token;
      show(await request("/api/admin/mobile/mirrors", {method: "PUT", body: JSON.stringify(body)}));
      toast("Резервные адреса сохранены и подписаны");
    } catch (e: any) { setError(e.message); }
  }
  async function publish() {
    setBusy(true); setError("");
    try { await request("/api/admin/mobile/mirrors/publish", {method: "POST"}); show(await request("/api/admin/mobile/mirrors")); toast("Список опубликован в Gist"); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  if (!cfg) return <div className="card"><h3>Резервные адреса API</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  return (
    <div className="card">
      <h3>Резервные адреса API и сайты напрямую</h3>
      <p className="muted">Если основной домен заблокируют, приложения сами перейдут на резервный адрес. Список подписан ключом магазина: подменить его через Gist или DNS нельзя.</p>
      {error ? <p className="error">{error}</p> : null}
      {cfg.publish_error ? <div className="alert">{cfg.publish_error}</div> : null}
      <label>Резервные адреса API (по одному в строке, https)<textarea rows={3} value={text.mirrors} onChange={e => setText({...text, mirrors: e.target.value})} placeholder="https://api2.example.com"/></label>
      <label>Источники списка вне магазина (Gist raw, Firebase Hosting…)<textarea rows={2} value={text.bootstrap} onChange={e => setText({...text, bootstrap: e.target.value})}/></label>
      <label>ID GitHub Gist для автопубликации<input value={cfg.gist_id || ""} onChange={e => setCfg({...cfg, gist_id: e.target.value.trim()})}/></label>
      <label>Токен GitHub (только gist){cfg.gist_token_set ? " — сохранён" : ""}<input type="password" value={text.token} onChange={e => setText({...text, token: e.target.value})} placeholder={cfg.gist_token_set ? "оставьте пустым, чтобы не менять" : "ghp_…"}/></label>
      <label>Дополнительные сайты в обход VPN (режим «Российские сайты напрямую»)<textarea rows={3} value={text.direct} onChange={e => setText({...text, direct: e.target.value})} placeholder="online.sberbank.com"/></label>
      {cfg.published_at ? <p className="muted">Gist обновлён: {new Date(cfg.published_at).toLocaleString("ru-RU")}</p> : null}
      <div className="toolbar"><button className="primary" onClick={save}>Сохранить</button><button disabled={busy || !cfg.gist_id} onClick={publish}>Опубликовать сейчас</button></div>
      <p className="muted">Ключ подписи (приложения запоминают его при первом входе): <code>{String(cfg.public_key || "").slice(0, 32)}…</code></p>
    </div>
  );
}
