import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const SECTIONS = ["vpn", "premium", "subscription", "locations", "settings", "support", "devices", "family", "referral", "wallet", "gifts", "giveaways", "notifications", "status", "security", "info"];
const BANNERS = ["", "app-vpn", "app-premium", "app-subscription", "app-giveaways", "app-gifts", "app-referral", "app-support", "app-wallet", "app-notifications", "app-status"];

function fill(t: string, v: Record<string, string>) { return t.replace(/\{(title|body|brand)\}/g, (_, k) => v[k]); }

/** «Приложения: стиль push-уведомлений»: colour, icon, pictures, texts, buttons and channels of every push. */
export function PushStyleEditor({d, request, reload, toast, assetBase}: {d: any; request: Request; reload: () => void; toast: (m: string) => void; assetBase: string}) {
  const [style, setStyle] = useState<any>(null);
  const [kind, setKind] = useState("subscription_expiring");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (d?.style) setStyle(JSON.parse(JSON.stringify(d.style))); }, [d]);
  if (!d?.style || !style) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const k = style.kinds[kind];
  const setTop = (key: string, value: any) => setStyle((s: any) => ({...s, [key]: value}));
  const setKindField = (key: string, value: any) => setStyle((s: any) => ({...s, kinds: {...s.kinds, [kind]: {...s.kinds[kind], [key]: value}}}));
  const setButton = (i: number, key: string, value: string) => setKindField("buttons", k.buttons.map((b: any, j: number) => j === i ? {...b, [key]: value} : b));
  const sample = d.preview?.[kind] || {};
  const values = {title: "Подписка заканчивается", body: "VPN работает до 30.10.2026 — осталось 3 дн.", brand: style.brand};
  const title = (k.emoji ? k.emoji + " " : "") + fill(k.title, values);
  const body = fill(k.body, values);
  const image = !style.images || !k.image ? "" : k.image.startsWith("https://") ? k.image : `${assetBase}/api/bot/banners/default/${k.image}.jpg`;
  async function save() {
    setBusy(true);
    try { await request("/api/admin/push-style", {method: "PUT", body: JSON.stringify(style)}); toast("Стиль push-уведомлений сохранён"); reload(); }
    catch (err: any) { toast(err?.message || "Не удалось сохранить"); }
    finally { setBusy(false); }
  }
  async function reset() {
    if (!window.confirm("Вернуть стандартный стиль push-уведомлений?")) return;
    await request("/api/admin/push-style", {method: "DELETE"}); toast("Стандартный стиль восстановлен"); reload();
  }
  return <div className="push-style-editor grid2" data-push-style>
    <div className="stack">
      <div className="card stack">
        <h3>Все уведомления</h3>
        <p className="muted">Так выглядят push-уведомления приложений Android и iOS. Изменения применяются к следующему уведомлению, обновлять приложение не нужно.</p>
        <label>Цвет акцента<input type="color" aria-label="Цвет акцента" value={style.accent} onChange={(e) => setTop("accent", e.target.value.toUpperCase())}/></label>
        <label>Название в уведомлениях<input value={style.brand} maxLength={40} onChange={(e) => setTop("brand", e.target.value)}/></label>
        <label className="check"><input type="checkbox" checked={style.large_icon} onChange={(e) => setTop("large_icon", e.target.checked)}/> Логотип магазина рядом с текстом</label>
        <label className="check"><input type="checkbox" checked={style.images} onChange={(e) => setTop("images", e.target.checked)}/> Картинки-баннеры</label>
        <label className="check"><input type="checkbox" checked={style.group} onChange={(e) => setTop("group", e.target.checked)}/> Группировать уведомления одного типа</label>
      </div>
      <div className="card stack">
        <h3>Тип уведомления</h3>
        <div className="chips" role="tablist">{Object.entries(d.kinds).map(([id, name]: any) =>
          <button key={id} role="tab" aria-selected={kind === id} className={kind === id ? "chip active" : "chip"} onClick={() => setKind(id)}>{name}</button>)}</div>
        <p className="muted">Для событий магазина: {(d.shop_kinds?.[kind] || []).join(", ") || "все остальные"}.</p>
        <label className="check"><input type="checkbox" checked={k.enabled} onChange={(e) => setKindField("enabled", e.target.checked)}/> Отправлять push</label>
        <label>Эмодзи перед заголовком<input value={k.emoji} maxLength={4} onChange={(e) => setKindField("emoji", e.target.value)}/></label>
        <label>Заголовок<input value={k.title} maxLength={120} onChange={(e) => setKindField("title", e.target.value)}/></label>
        <label>Текст<textarea rows={3} value={k.body} maxLength={300} onChange={(e) => setKindField("body", e.target.value)}/></label>
        <p className="muted">Подстановки: {"{title}"} и {"{body}"} — текст уведомления магазина, {"{brand}"} — название.</p>
        <label>Картинка<select aria-label="Картинка" value={BANNERS.includes(k.image) ? k.image : "url"} onChange={(e) => setKindField("image", e.target.value === "url" ? "https://" : e.target.value)}>
          {BANNERS.map((b) => <option key={b} value={b}>{b || "Без картинки"}</option>)}<option value="url">Своя ссылка https://</option></select></label>
        {!BANNERS.includes(k.image) && <label>Ссылка на картинку<input value={k.image} onChange={(e) => setKindField("image", e.target.value)}/></label>}
        <label>Открыть по нажатию<select aria-label="Открыть по нажатию" value={k.section} onChange={(e) => setKindField("section", e.target.value)}>
          {SECTIONS.map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
        <label>Группа уведомлений Android<select aria-label="Группа" value={k.channel} onChange={(e) => setKindField("channel", e.target.value)}>
          {Object.entries(d.channels).map(([id, name]: any) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label className="check"><input type="checkbox" checked={k.sound} onChange={(e) => setKindField("sound", e.target.checked)}/> Звук</label>
        <h4>Кнопки (до двух)</h4>
        {k.buttons.map((b: any, i: number) => <div className="row" key={i} data-push-button={i}>
          <input aria-label={`Кнопка ${i + 1}`} value={b.label} maxLength={24} onChange={(e) => setButton(i, "label", e.target.value)}/>
          <select aria-label={`Раздел кнопки ${i + 1}`} value={b.section} onChange={(e) => setButton(i, "section", e.target.value)}>{SECTIONS.map((s) => <option key={s}>{s}</option>)}</select>
          <button type="button" className="btn-ghost" onClick={() => setKindField("buttons", k.buttons.filter((_: any, j: number) => j !== i))}>Убрать</button></div>)}
        {k.buttons.length < 2 && <button type="button" onClick={() => setKindField("buttons", [...k.buttons, {label: "Открыть", section: k.section || "vpn"}])}>Добавить кнопку</button>}
      </div>
      <div className="row"><button className="primary" disabled={busy} onClick={save}>{busy ? "Сохраняем…" : "Сохранить"}</button><button className="btn-ghost" onClick={reset}>Стандартный стиль</button></div>
    </div>
    <div className="card push-preview" aria-label="Предпросмотр уведомления">
      <h3>Предпросмотр</h3>
      <div className="push-card" style={{borderLeft: `4px solid ${style.accent}`}} data-push-preview>
        <div className="push-head"><span className="push-dot" style={{background: style.accent}}/>{style.brand} · сейчас</div>
        <div className="push-body">
          <div><b>{title}</b><p>{body}</p></div>
          {style.large_icon && <span className="push-logo" style={{background: style.accent}}>🐶</span>}
        </div>
        {image && <img src={image} alt="" className="push-image"/>}
        {k.buttons.length > 0 && <div className="push-actions">{k.buttons.map((b: any, i: number) => <span key={i} style={{color: style.accent}}>{b.label}</span>)}</div>}
      </div>
      {!k.enabled && <p className="muted">Push для этого типа выключен — уведомление останется только в приложении.</p>}
      {sample.title && <p className="muted">Пример с текущими сохранёнными настройками: «{sample.title}»</p>}
    </div>
  </div>;
}
