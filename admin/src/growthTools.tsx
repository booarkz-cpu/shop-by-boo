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
