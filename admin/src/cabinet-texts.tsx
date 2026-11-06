import React, {useEffect, useState} from "react";
import {LoadState} from "./components/ui/state";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const API = "/api/admin/cabinet-texts";
const LANGS: Record<string, string> = {ru: "Русский", en: "English", uk: "Українська"};
const PAGE = 60;

/** «Бот и кабинет → Личный кабинет → Тексты кабинета» (BACKLOG A4, v28.88.0): every text of the web cabinet on three
 *  languages; an empty field returns the cabinet's own text. Saved texts reach customers on their next page load. */
export function CabinetTexts({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [lang, setLang] = useState("ru");
  const [query, setQuery] = useState("");
  const [onlyOwn, setOnlyOwn] = useState(false);
  const [limit, setLimit] = useState(PAGE);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const load = () => request(API).then((x: any) => { setData(x); setDraft({}); }).catch((e: any) => setError(e.message));
  useEffect(() => { load(); }, []);
  if (!data) return <section className="card"><LoadState error={error} label="Загрузка текстов кабинета…"/></section>;
  const value = (item: any) => draft[item.key] ?? item.custom[lang] ?? item.default[lang];
  const q = query.trim().toLowerCase();
  const shown = data.texts.filter((item: any) => (!onlyOwn || item.custom[lang] || item.key in draft)
    && (!q || item.key.toLowerCase().includes(q) || value(item).toLowerCase().includes(q)));
  const changed = Object.keys(draft).length;
  const custom = data.texts.filter((item: any) => item.custom[lang]).length;
  async function save() {
    setError("");
    try {
      const out = await request(API, {method: "PUT", body: JSON.stringify({lang, texts: draft})});
      toast(`Тексты кабинета сохранены: своих ${out.custom}. Клиенты увидят их при следующем открытии кабинета.`);
      await load();
    } catch (e: any) { setError(e.message); }
  }
  return <section className="card" data-cabinet-texts>
    <h3>Тексты кабинета</h3>
    <p className="muted">Все надписи веб-кабинета на трёх языках: ключ — русский текст из кабинета. Пустое поле — стандартный текст. Только обычный текст, без HTML. Своих текстов на этом языке: {custom}.</p>
    {error && <div role="alert" className="error">{error}</div>}
    <div className="toolbar">
      <label>Язык<select value={lang} onChange={e => { setLang(e.target.value); setDraft({}); }}>
        {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label>Поиск<input value={query} onChange={e => { setQuery(e.target.value); setLimit(PAGE); }} placeholder="текст кабинета"/></label>
      <label className="inline"><input type="checkbox" checked={onlyOwn} onChange={e => setOnlyOwn(e.target.checked)}/> Только свои</label>
    </div>
    {shown.slice(0, limit).map((item: any) => <label key={item.key} className="wide" data-text={item.key}>
      <span>{item.key}{item.custom[lang] && !(item.key in draft) ? " · свой" : ""}</span>
      <input aria-label={item.key} value={value(item)} maxLength={500} onChange={e => setDraft({...draft, [item.key]: e.target.value})}/>
      {(item.custom[lang] || item.key in draft) && <button type="button" onClick={() => setDraft({...draft, [item.key]: ""})}>Стандартный текст</button>}
    </label>)}
    {shown.length > limit && <button type="button" onClick={() => setLimit(limit + PAGE)}>Показать ещё ({shown.length - limit})</button>}
    {shown.length === 0 && <p className="muted">Ничего не найдено.</p>}
    <div className="toolbar"><button className="primary" onClick={save} disabled={!changed}>Сохранить{changed ? ` (${changed})` : ""}</button>
      {changed > 0 && <button onClick={() => setDraft({})}>Отменить</button>}</div>
  </section>;
}
