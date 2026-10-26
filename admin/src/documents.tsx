import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Lang = "ru" | "en" | "uk";
type Faq = {question: string; answer: string};
type Translation = {title: string; body: string; items: Faq[]};
type Page = {kind: string; default_title: string; command: string; enabled: boolean; version: number; updated_at?: string; updated_by?: string} & Record<Lang, Translation>;

const LANGS: [Lang, string][] = [["ru", "Русский"], ["en", "English"], ["uk", "Українська"]];
const HINT = "## Заголовок — отдельной строкой; «- » в начале строки — пункт списка; **жирный текст**; пустая строка — новый абзац.";
const blank = (): Translation => ({title: "", body: "", items: []});

/** «Бот и кабинет → Документы»: FAQ, rules, privacy policy and public offer for the Mini App, cabinet and bot. */
export function Documents({request, toast}: {request: Request; toast: (m: string) => void}) {
  const [pages, setPages] = useState<Page[]>([]);
  const [canEdit, setCanEdit] = useState(false);
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
      setPages(rows); setCanEdit(!!r.can_edit);
      setDraft(rows.find((p) => p.kind === keep) || rows[0] || null);
    } catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);

  function pick(next: string) { setKind(next); setDraft(pages.find((p) => p.kind === next) || null); setLang("ru"); }
  function edit(patch: Partial<Translation>) {
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

  if (!draft) return <div className="card">{error ? <div role="alert" className="error">{error}</div> : <p className="muted">Загрузка…</p>}</div>;
  const t = draft[lang];
  const filled = (p: Page) => !!(p.ru.body || p.ru.items.length);
  return <div className="documents">
    <div className="card">
      <p className="muted">Тексты показываются в разделе «Информация» Mini App и личного кабинета и в боте: команды /faq, /rules, /privacy, /offer, /info и кнопка типа «Документ» в дереве кнопок. Над каждым документом — свой баннер с корги Люси («Баннеры бота»). {canEdit ? "" : "Изменять документы может только администратор."}</p>
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
