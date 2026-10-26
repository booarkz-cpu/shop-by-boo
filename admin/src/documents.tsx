import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Lang = "ru" | "en" | "uk";
type Faq = {question: string; answer: string};
type Translation = {title: string; body: string; items: Faq[]};
type Banner = {url: string; source: string; hidden: boolean; custom: boolean; default_url: string};
type Page = {kind: string; default_title: string; command: string; enabled: boolean; version: number; updated_at?: string; updated_by?: string; banner?: Banner} & Record<Lang, Translation>;

const LANGS: [Lang, string][] = [["ru", "Русский"], ["en", "English"], ["uk", "Українська"]];
const HINT = "## Заголовок — отдельной строкой; «- » в начале строки — пункт списка; **жирный текст**; пустая строка — новый абзац.";
const blank = (): Translation => ({title: "", body: "", items: []});

/** «Бот и кабинет → Документы»: FAQ, rules, privacy policy and public offer for the Mini App, cabinet and bot. */
export function Documents({request, toast, assetBase = ""}: {request: Request; toast: (m: string) => void; assetBase?: string}) {
  const [pages, setPages] = useState<Page[]>([]);
  const [canEdit, setCanEdit] = useState(false);
  const [canEditBanners, setCanEditBanners] = useState(false);
  const [kind, setKind] = useState("faq");
  const [lang, setLang] = useState<Lang>("ru");
  const [draft, setDraft] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(keep = kind) {
    setError("");
    try {
      const r = await request("/api/admin/info-pages");
      const rows: Page[] = r.pages.map((p: any) => ({...p, ru: {...blank(), ...p.ru}, en: {...blank(), ...p.en}, uk: {...blank(), ...p.uk}}));
      setPages(rows); setCanEdit(!!r.can_edit); setCanEditBanners(!!r.can_edit_banners);
      setDraft(rows.find((p) => p.kind === keep) || rows[0] || null);
    } catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);

  function pick(next: string) { setKind(next); setDraft(pages.find((p) => p.kind === next) || null); setLang("ru"); }
  function edit(patch: Partial<Translation>) {
    // The banner of the document: the same key as in «Баннеры бота», so the picture changes in the bot,
  // the Mini App, the cabinet and the Android/iOS apps at once.
  async function banner(action: "upload" | "reset" | "hide" | "show", file?: File) {
    if (!draft || busy) return;
    setBusy(true); setError("");
    try {
      if (action === "upload" && file) {
        const fd = new FormData(); fd.append("file", file);
        await request(`/api/admin/bot/banners/${draft.kind}`, {method: "POST", body: fd});
      } else if (action === "reset") {
        await request(`/api/admin/bot/banners/${draft.kind}`, {method: "DELETE"});
      } else {
        await request(`/api/admin/bot/banners/${draft.kind}/visibility`, {method: "PUT", body: JSON.stringify({hidden: action === "hide"})});
      }
      toast(action === "upload" ? "Баннер документа загружен" : action === "reset" ? "Возвращён стандартный баннер" : action === "hide" ? "Баннер скрыт" : "Баннер показывается");
      await load(draft.kind);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  if (!draft) return;
    setDraft({...draft, [lang]: {...draft[lang], ...patch}});
  }
  async function save() {
    if (!draft || busy) return;
    setBusy(true); setError("");
    try {
      const body = {enabled: draft.enabled, ru: draft.ru, en: draft.en, uk: draft.uk};
      await request(`/api/admin/info-pages/${draft.kind}`, {method: "PUT", body: JSON.stringify(body)});
      toast("Документ сохранён — клиенты уже видят новую версию");
      await load(draft.kind);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  // The banner of the document: the same key as in «Баннеры бота», so the picture changes in the bot,
  // the Mini App, the cabinet and the Android/iOS apps at once.
  async function banner(action: "upload" | "reset" | "hide" | "show", file?: File) {
    if (!draft || busy) return;
    setBusy(true); setError("");
    try {
      if (action === "upload" && file) {
        const fd = new FormData(); fd.append("file", file);
        await request(`/api/admin/bot/banners/${draft.kind}`, {method: "POST", body: fd});
      } else if (action === "reset") {
        await request(`/api/admin/bot/banners/${draft.kind}`, {method: "DELETE"});
      } else {
        await request(`/api/admin/bot/banners/${draft.kind}/visibility`, {method: "PUT", body: JSON.stringify({hidden: action === "hide"})});
      }
      toast(action === "upload" ? "Баннер документа загружен" : action === "reset" ? "Возвращён стандартный баннер" : action === "hide" ? "Баннер скрыт" : "Баннер показывается");
      await load(draft.kind);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  if (!draft) return <div className="card">{error ? <div role="alert" className="error">{error}</div> : <p className="muted">Загрузка…</p>}</div>;
  const t = draft[lang];
  const filled = (p: Page) => !!(p.ru.body || p.ru.items.length);
  return <div className="documents">
    <div className="card">
      <p className="muted">Тексты и баннеры обновляются везде сразу после сохранения: раздел «Информация» Mini App, личного кабинета и приложений Android и iOS, кнопки «Открыть документ» в приложениях и бот (команды /faq, /rules, /privacy, /offer, /info и кнопка типа «Документ» в дереве кнопок). Над каждым документом — свой баннер: стандартный с корги Люси или ваш. {canEdit ? "" : "Изменять документы может только администратор."}</p>
      <div className="doc-tabs" role="tablist">
        {pages.map((p) => <button key={p.kind} role="tab" aria-selected={p.kind === kind} className={p.kind === kind ? "primary" : ""} onClick={() => pick(p.kind)}>
          {p.default_title}<span className="muted"> · {filled(p) ? (p.enabled ? `версия ${p.version}` : "выключен") : "не заполнен"}</span>
        </button>)}
      </div>
    </div>
    <div className="card">
      <h3>{draft.default_title} <span className="muted">{draft.command}</span></h3>
      {draft.updated_at && <p className="muted">Версия {draft.version}, изменён {draft.updated_at.replace("T", " ")} · {draft.updated_by}</p>}
      {error && <div role="alert" className="error">{error}</div>}
      <label className="inline"><input type="checkbox" disabled={!canEdit} checked={draft.enabled} onChange={(e) => setDraft({...draft, enabled: e.target.checked})}/> Показывать клиентам</label>
      {draft.banner && <fieldset className="doc-banner" data-doc-banner={draft.kind}>
        <legend>Баннер документа</legend>
        {(draft.banner.url || draft.banner.default_url)
          ? <img src={assetBase + (draft.banner.url || draft.banner.default_url)} alt={`Баннер: ${draft.default_title}`} style={{maxWidth: 420, width: "100%", borderRadius: 10, opacity: draft.banner.hidden ? .35 : 1}}/>
          : <p className="muted">Без баннера</p>}
        <p className="muted">{draft.banner.hidden ? "Скрыт" : draft.banner.custom ? "Своё изображение" : "Стандартный с корги Люси"} · один баннер для бота, Mini App, кабинета и приложений. PNG, JPG или WEBP до 8 МБ, лучше 1280×640.</p>
        {canEditBanners && <div className="btn-row">
          <label className="field">Загрузить своё изображение<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) banner("upload", f); }}/></label>
          {draft.banner.custom && <button disabled={busy} onClick={() => banner("reset")}>Вернуть стандартный</button>}
          <button disabled={busy} onClick={() => banner(draft.banner!.hidden ? "show" : "hide")}>{draft.banner.hidden ? "Показывать баннер" : "Скрыть баннер"}</button>
        </div>}
      </fieldset>}
      <div className="doc-tabs" role="tablist" aria-label="Язык">
        {LANGS.map(([code, name]) => <button key={code} role="tab" aria-selected={code === lang} className={code === lang ? "primary" : ""} onClick={() => setLang(code)}>
          {name}{code !== "ru" && !(draft[code].body || draft[code].items.length) ? <span className="muted"> · как на русском</span> : null}</button>)}
      </div>
      <label>Заголовок<input disabled={!canEdit} value={t.title} placeholder={draft.default_title} maxLength={120} onChange={(e) => edit({title: e.target.value})}/></label>
      <label>Текст<textarea disabled={!canEdit} rows={draft.kind === "faq" ? 5 : 16} value={t.body} maxLength={30000} placeholder={HINT} onChange={(e) => edit({body: e.target.value})}/></label>
      <p className="muted">{HINT} Ссылки https://… вставляются как есть.</p>
      {draft.kind === "faq" && <>
        <h4>Вопросы и ответы</h4>
        {t.items.map((item, i) => <div className="doc-faq" key={i}>
          <label>Вопрос {i + 1}<input disabled={!canEdit} value={item.question} maxLength={300} onChange={(e) => edit({items: t.items.map((x, j) => j === i ? {...x, question: e.target.value} : x)})}/></label>
          <label>Ответ<textarea disabled={!canEdit} rows={3} value={item.answer} maxLength={3000} onChange={(e) => edit({items: t.items.map((x, j) => j === i ? {...x, answer: e.target.value} : x)})}/></label>
          {canEdit && <div className="btn-row">
            <button disabled={i === 0} onClick={() => { const items = [...t.items]; [items[i - 1], items[i]] = [items[i], items[i - 1]]; edit({items}); }}>Выше</button>
            <button onClick={() => edit({items: t.items.filter((_, j) => j !== i)})}>Удалить</button>
          </div>}
        </div>)}
        {canEdit && t.items.length < 60 && <button onClick={() => edit({items: [...t.items, {question: "", answer: ""}]})}>Добавить вопрос</button>}
      </>}
      {canEdit && <div className="btn-row"><button className="primary" disabled={busy} onClick={save}>{busy ? "Сохранение…" : "Сохранить"}</button><button disabled={busy} onClick={() => load(draft.kind)}>Отменить изменения</button></div>}
    </div>
  </div>;
}
