import React, {useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

const SOURCE: Record<string, string> = {default: "стандартный", custom: "свой", hidden: "скрыт", none: "нет"};

/** Banners of bot sections and menu buttons: preview, own upload, reset to default, hide. */
export function BotBanners({data, request, reload, toast, assetBase}: {data: any; request: Request; reload: () => void; toast: (m: string) => void; assetBase: string}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  if (!data?.sections) return <div className="card"><p className="muted">Загрузка…</p></div>;

  async function run(key: string, action: () => Promise<any>, done: string) {
    if (busy) return; setBusy(key); setError("");
    try { await action(); toast(done); reload(); } catch (err: any) { setError(err.message); } finally { setBusy(""); }
  }
  const upload = (key: string, file: File | undefined) => file && run(key, () => {
    const fd = new FormData(); fd.append("file", file);
    return request(`/api/admin/bot/banners/${key}`, {method: "POST", body: fd});
  }, "Баннер загружен");
  const reset = (key: string) => run(key, () => request(`/api/admin/bot/banners/${key}`, {method: "DELETE"}), "Баннер сброшен");
  const hide = (key: string, hidden: boolean) => run(key, () => request(`/api/admin/bot/banners/${key}/visibility`, {method: "PUT", body: JSON.stringify({hidden})}), hidden ? "Баннер скрыт" : "Баннер показывается");
  const toggleAll = (enabled: boolean) => run("all", () => request("/api/admin/bot/banners-enabled", {method: "PUT", body: JSON.stringify({enabled})}), enabled ? "Баннеры включены" : "Баннеры выключены");

  const card = (b: any) => <div className="banner-card card" key={b.key} data-banner={b.key}>
    <div className="banner-preview">
      {b.url ? <img src={assetBase + b.url} alt={`Баннер: ${b.title}`} style={{opacity: b.source === "hidden" ? .35 : 1}}/> : <div className="banner-empty muted">Без баннера</div>}
    </div>
    <div className="banner-meta"><b>{b.title}</b><span className="muted">{b.where} · {SOURCE[b.source] || b.source}</span></div>
    <label className="field">Своё изображение<input type="file" accept="image/png,image/jpeg,image/webp" disabled={!!busy} onChange={e => upload(b.key, e.target.files?.[0])}/></label>
    <div className="inline">
      {(b.custom || b.hidden) && <button disabled={!!busy} onClick={() => reset(b.key)}>{b.has_default ? "Вернуть стандартный" : "Убрать своё изображение"}</button>}
      <label className="inline"><input type="checkbox" checked={!b.hidden} disabled={!!busy} onChange={e => hide(b.key, !e.target.checked)}/>Показывать</label>
    </div>
  </div>;

  return <div>
    <div className="card">
      <h3>Баннеры бота</h3>
      <p className="muted">Баннер — картинка над текстом раздела в Telegram, как шапка экрана. Для каждого раздела есть стандартный баннер с корги Люси; загрузите своё изображение (PNG, JPG или WEBP до 8 МБ, лучше 1280×640), чтобы заменить его. Магазин пересохраняет файл в JPEG. При переходе по кнопкам-папкам бот меняет картинку и текст в том же сообщении. Если текст раздела длиннее {data.caption_limit} символов, бот отправит баннер и текст отдельными сообщениями.</p>
      {error && <div role="alert" className="error">{error}</div>}
      <label className="inline"><input type="checkbox" checked={!!data.enabled} disabled={!!busy} onChange={e => toggleAll(e.target.checked)}/>Показывать баннеры в боте</label>
    </div>
    <h3>Разделы и команды</h3>
    <div className="banner-grid">{data.sections.map(card)}</div>
    <h3>Кнопки меню</h3>
    {data.menu.length === 0
      ? <p className="muted">Кнопок-папок и кнопок-полей пока нет. Их можно добавить в «Дереве кнопок»; папки без своего баннера показывают баннер «Меню».</p>
      : <div className="banner-grid">{data.menu.map(card)}</div>}
  </div>;
}
