import React, {useEffect, useState} from "react";
import {LoadState} from "./components/ui/state";

/** v28.73 «Юридические документы» (вкладка «Документы»): реквизиты продавца и проекты оферты, политики и правил. */
type Request = (path: string, options?: RequestInit) => Promise<any>;
const KIND: Record<string, string> = {offer: "Публичная оферта", privacy: "Политика конфиденциальности", rules: "Правила пользования"};

export function LegalDocs({request, toast}: {request: Request; toast: (t: string) => void}) {
  const [d, setD] = useState<any>(null);
  const [s, setS] = useState<any>(null);
  const [show, setShow] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => { setError(""); request("/api/admin/legal").then(x => { setD(x); setS(x.seller); }).catch(e => setError(e.message)); };
  useEffect(() => { load(); }, [request]);
  if (!d || !s) return <LoadState error={error} onRetry={load} label="Загрузка юридических документов…"/>;
  const field = (k: string, label: string, hint = "") => <label className="field">{label}<input value={s[k] || ""} placeholder={hint} onChange={e => setS({...s, [k]: e.target.value})}/></label>;
  async function save() {
    setBusy(true); setError("");
    try { const r = await request("/api/admin/legal", {method: "PUT", body: JSON.stringify(s)}); setD({...d, ...r}); toast("Реквизиты сохранены"); load(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function apply(overwrite: boolean) {
    if (overwrite && !confirm("Перезаписать документы, изменённые вручную, проектами из шаблона?")) return;
    setBusy(true); setError("");
    try { const r = await request("/api/admin/legal/apply", {method: "POST", body: JSON.stringify({kinds: ["offer", "privacy", "rules"], overwrite})});
      toast(r.written.length ? `Записано: ${r.written.map((k: string) => KIND[k]).join(", ")}` : "Документы, изменённые вручную, сохранены без изменений"); load(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="card">
      <h3>Юридические документы</h3>
      <p className="muted">Проекты публичной оферты, политики конфиденциальности и правил пользования по законодательству РФ (ГК РФ, закон «О защите прав потребителей», 152-ФЗ, 149-ФЗ, 54-ФЗ) с вашими реквизитами, на русском, английском и украинском. {d.disclaimer}</p>
      {error ? <p className="error">{error}</p> : null}
      <div className="form-grid">
        <label className="field">Форма<select value={s.form} onChange={e => setS({...s, form: e.target.value})}>{Object.entries(d.forms).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        {field("name", "ФИО или название")}{field("inn", "ИНН", "10 или 12 цифр")}
        {s.form !== "self_employed" && field("ogrn", s.form === "company" ? "ОГРН" : "ОГРНИП")}
        {field("address", "Адрес")}{field("email", "E-mail для обращений")}{field("site", "Сайт или кабинет", "https://…")}
        {field("rkn_number", "Номер в реестре операторов ПДн", "если есть")}
        <label className="check-field"><input type="checkbox" checked={!!s.receipts} onChange={e => setS({...s, receipts: e.target.checked})}/> Чеки выдаются при каждой оплате</label>
      </div>
      <div className="inline"><button className="primary" disabled={busy} onClick={save}>Сохранить реквизиты</button></div>
      {d.missing.length ? <p role="status">⚠️ Не заполнено: {d.missing.join(", ")}. В текстах на этих местах останется «[укажите …]».</p> : null}
      <h4>Документы</h4>
      <table className="table"><thead><tr><th>Документ</th><th>В «Документах»</th><th/></tr></thead><tbody>
        {Object.keys(KIND).map(k => <tr key={k}><td>{KIND[k]}</td>
          <td>{!d.pages[k].exists ? "нет" : `${d.pages[k].enabled ? "опубликован" : "выключен"}${d.pages[k].generated ? " · из шаблона" : " · изменён вручную"}`}</td>
          <td><button onClick={() => setShow(show === k ? "" : k)}>{show === k ? "Скрыть" : "Предпросмотр"}</button></td></tr>)}
      </tbody></table>
      {show && <pre className="legal-preview">{d.preview[show]}</pre>}
      <div className="inline">
        <button className="primary" disabled={busy} onClick={() => apply(false)}>Заполнить документы</button>
        <button disabled={busy} onClick={() => apply(true)}>Перезаписать изменённые вручную</button>
      </div>
      <p className="muted">Документы записываются выключенными. Прочитайте их, дайте проверить юристу и включите каждый документ выше — тогда он появится в кабинете, Mini App, боте и приложениях.</p>
    </div>
  );
}
