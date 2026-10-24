import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Field = {key: string; label: string; kind?: "text" | "select" | "list" | "datetime" | "textarea"; options?: string[]; placeholder?: string};

const PROVIDERS = ["yookassa", "platega", "rollypay", "sandbox", "telegram_stars"];
const YK_METHODS = ["", "bank_card", "sbp", "yoo_money", "sberbank", "tinkoff_bank"];
const INFO_KINDS = ["faq", "rules", "privacy", "offer", "other"];
const COLORS: [string, string][] = [["accent", "Акцент (неоновый)"], ["accent_2", "Второй акцент"], ["background", "Фон"], ["surface", "Карточки"], ["text", "Текст"], ["muted", "Второстепенный текст"], ["danger", "Ошибки"]];

/** Editor for an array of small objects (promo cards, payment methods, categories, buttons, pages). */
function Rows({title, rows, fields, blank, onChange, max}: {title: string; rows: any[]; fields: Field[]; blank: any; onChange: (rows: any[]) => void; max: number}) {
  const set = (i: number, key: string, value: any) => onChange(rows.map((r, j) => (j === i ? {...r, [key]: value} : r)));
  return <div className="config-rows">
    <h4>{title}</h4>
    {rows.length === 0 && <p className="muted">Пусто — используются значения по умолчанию.</p>}
    {rows.map((row, i) => <div className="config-row card" key={i} data-row={`${title}-${i}`}>
      {fields.map((f) => {
        const label = `${title}: ${f.label} ${i + 1}`;
        if (f.kind === "select") return <label className="field" key={f.key}>{label}<select value={row[f.key] ?? ""} onChange={(e) => set(i, f.key, e.target.value)}>{(f.options || []).map((o) => <option key={o} value={o}>{o || "—"}</option>)}</select></label>;
        if (f.kind === "list") return <label className="field" key={f.key}>{label}<input placeholder={f.placeholder} value={(row[f.key] || []).join(", ")} onChange={(e) => set(i, f.key, e.target.value.split(",").map((x) => x.trim()).filter(Boolean))}/></label>;
        if (f.kind === "datetime") return <label className="field" key={f.key}>{label}<input type="datetime-local" value={row[f.key] ? String(row[f.key]).slice(0, 16) : ""} onChange={(e) => set(i, f.key, e.target.value ? new Date(e.target.value).toISOString() : null)}/></label>;
        if (f.kind === "textarea") return <label className="field" key={f.key}>{label}<textarea rows={2} value={row[f.key] ?? ""} onChange={(e) => set(i, f.key, e.target.value)}/></label>;
        return <label className="field" key={f.key}>{label}<input placeholder={f.placeholder} value={row[f.key] ?? ""} onChange={(e) => set(i, f.key, e.target.value)}/></label>;
      })}
      <button type="button" className="danger" onClick={() => onChange(rows.filter((_, j) => j !== i))}>{`Удалить: ${title} ${i + 1}`}</button>
    </div>)}
    {rows.length < max && <button type="button" onClick={() => onChange([...rows, {...blank}])}>{`Добавить: ${title}`}</button>}
  </div>;
}

/** «Бот и кабинет → Конфигурация Mini App»: overrides for GET /api/app-config. */
export function AppConfigEditor({data, request, reload, toast}: {data: any; request: Request; reload: () => void; toast: (m: string) => void}) {
  const [o, setO] = useState<any>(null);
  const [json, setJson] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data?.overrides) { setO(data.overrides); setJson(JSON.stringify(data.overrides, null, 2)); } }, [data?.overrides]);
  if (!o) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const icons: string[] = data.icons || [];
  const texts: Record<string, string> = data.texts || {};
  const up = (section: string, patch: any) => setO({...o, [section]: {...o[section], ...patch}});

  async function save(value: any) {
    if (busy) return; setBusy(true); setError("");
    try { await request("/api/admin/app-config", {method: "PUT", body: JSON.stringify(value)}); toast("Конфигурация Mini App сохранена"); reload(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function reset() {
    if (busy) return; setBusy(true); setError("");
    try { await request("/api/admin/app-config", {method: "DELETE"}); toast("Возвращены значения по умолчанию"); reload(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  function saveJson() {
    try { save(JSON.parse(json)); } catch { setError("JSON с ошибкой: проверьте скобки и кавычки"); }
  }

  return <div className="app-config-editor">
    <div className="card">
      <h3>Конфигурация Mini App</h3>
      <p className="muted">Mini App и кабинет получают тему, навигацию, баннеры, акции, серверы, способы пополнения, условия рефералов, кнопки поддержки, документы и согласие с офертой из <code>GET /api/app-config</code>. Здесь задаются значения поверх данных магазина: тарифы, акции, меню кабинета и опубликованные страницы подставляются сами. Баннеры разделов меняются в «Баннерах бота».</p>
      {error && <div role="alert" className="error">{error}</div>}
      <div className="inline"><button className="primary" disabled={busy} onClick={() => save(o)}>Сохранить</button><button disabled={busy} onClick={reset}>Сбросить к значениям по умолчанию</button></div>
    </div>

    <div className="grid2">
      <div className="card">
        <h4>Тема</h4>
        {COLORS.map(([key, label]) => <label className="field" key={key}>{label}<input type="color" value={o.theme[key]} onChange={(e) => up("theme", {[key]: e.target.value})}/></label>)}
        <label className="field">Скругление углов, px<input type="number" min={0} max={32} value={o.theme.radius} onChange={(e) => up("theme", {radius: Number(e.target.value)})}/></label>
        <label className="inline"><input type="checkbox" checked={!!o.banners_enabled} onChange={(e) => setO({...o, banners_enabled: e.target.checked})}/>Показывать баннеры разделов</label>
      </div>
      <div className="card">
        <h4>Кошелёк</h4>
        <label className="field">Кнопки сумм (через запятую)<input value={(o.wallet.amounts || []).join(", ")} onChange={(e) => up("wallet", {amounts: e.target.value.split(",").map((x) => Number(x.trim())).filter((x) => Number.isFinite(x) && x > 0)})}/></label>
        <label className="inline"><input type="checkbox" checked={!!o.wallet.stars.enabled} onChange={(e) => up("wallet", {stars: {...o.wallet.stars, enabled: e.target.checked}})}/>Оплата Telegram Stars</label>
        <label className="field">Курс: сколько единиц валюты даёт 1 Star<input type="number" step="0.01" min="0.01" value={o.wallet.stars.rate} onChange={(e) => up("wallet", {stars: {...o.wallet.stars, rate: e.target.value}})}/></label>
        <label className="field">Минимум Stars за платёж<input type="number" min={1} value={o.wallet.stars.min_stars} onChange={(e) => up("wallet", {stars: {...o.wallet.stars, min_stars: Number(e.target.value)}})}/></label>
        <Rows title="Способ оплаты" max={8} rows={o.wallet.methods} onChange={(methods) => up("wallet", {methods})}
          blank={{id: "sbp", title: "СБП", icon: "sbp", provider: "yookassa", yookassa_method: "sbp"}}
          fields={[{key: "id", label: "ID"}, {key: "title", label: "Название"}, {key: "icon", label: "Иконка", kind: "select", options: icons},
            {key: "provider", label: "Платёжный агент", kind: "select", options: PROVIDERS}, {key: "yookassa_method", label: "Метод YooKassa", kind: "select", options: YK_METHODS}]}/>
      </div>
    </div>

    <div className="grid2">
      <div className="card">
        <Rows title="Акция" max={10} rows={o.promo_cards} onChange={(promo_cards) => setO({...o, promo_cards})}
          blank={{id: "promo", title: "", text: "", discount: "", ends_at: null, button_text: "Выбрать тариф", link: "#plans"}}
          fields={[{key: "id", label: "ID"}, {key: "title", label: "Заголовок"}, {key: "text", label: "Текст", kind: "textarea"}, {key: "discount", label: "Скидка", placeholder: "-30%"},
            {key: "ends_at", label: "Действует до", kind: "datetime"}, {key: "button_text", label: "Текст кнопки"}, {key: "link", label: "Ссылка", placeholder: "#plans или https://…"}]}/>
        <p className="muted">Активные акции на тарифы и рекламные блоки показываются автоматически.</p>
      </div>
      <div className="card">
        <Rows title="Категория серверов" max={12} rows={o.servers.categories} onChange={(categories) => up("servers", {categories})}
          blank={{id: "europe", title: "Европа", icon: "globe", countries: ["DE", "NL"], match: []}}
          fields={[{key: "id", label: "ID"}, {key: "title", label: "Название"}, {key: "icon", label: "Иконка", kind: "select", options: icons},
            {key: "countries", label: "Страны", kind: "list", placeholder: "DE, NL, FI"}, {key: "match", label: "Слова в имени узла", kind: "list", placeholder: "white, lte"}]}/>
        <label className="inline"><input type="checkbox" checked={!!o.servers.show_load} onChange={(e) => up("servers", {show_load: e.target.checked})}/>Показывать число клиентов онлайн</label>
      </div>
    </div>

    <div className="grid2">
      <div className="card">
        <h4>Рефералы</h4>
        <label className="field">Условия программы<textarea rows={4} maxLength={2000} value={o.referral.conditions} onChange={(e) => up("referral", {conditions: e.target.value})}/></label>
        <label className="inline"><input type="checkbox" checked={!!o.referral.withdraw_enabled} onChange={(e) => up("referral", {withdraw_enabled: e.target.checked})}/>Разрешить вывод средств</label>
        <Rows title="Кнопка поддержки" max={8} rows={o.support.buttons} onChange={(buttons) => up("support", {buttons})}
          blank={{title: "Написать в Telegram", icon: "send", link: "https://t.me/"}}
          fields={[{key: "title", label: "Текст"}, {key: "icon", label: "Иконка", kind: "select", options: icons}, {key: "link", label: "Ссылка", placeholder: "https://t.me/…, tg://… или #info"}]}/>
        <label className="inline"><input type="checkbox" checked={!!o.support.ticket_form} onChange={(e) => up("support", {ticket_form: e.target.checked})}/>Форма обращения в поддержку</label>
      </div>
      <div className="card">
        <h4>Документы и оферта</h4>
        <label className="inline"><input type="checkbox" checked={!!o.info.include_published_legal} onChange={(e) => up("info", {include_published_legal: e.target.checked})}/>Добавлять опубликованные юридические страницы</label>
        <Rows title="Документ" max={12} rows={o.info.pages} onChange={(pages) => up("info", {pages})}
          blank={{slug: "faq", title: "Частые вопросы", kind: "faq"}}
          fields={[{key: "slug", label: "Адрес страницы"}, {key: "title", label: "Название"}, {key: "kind", label: "Тип", kind: "select", options: INFO_KINDS}]}/>
        <label className="inline"><input type="checkbox" checked={!!o.consent.enabled} onChange={(e) => up("consent", {enabled: e.target.checked})}/>Спрашивать согласие с офертой</label>
        <label className="inline"><input type="checkbox" checked={!!o.consent.required_for_payment} onChange={(e) => up("consent", {required_for_payment: e.target.checked})}/>Без согласия не принимать оплату</label>
        <label className="field">Версия оферты<input value={o.consent.version} onChange={(e) => up("consent", {version: e.target.value})}/></label>
        <label className="field">Текст согласия<input maxLength={300} value={o.consent.text} onChange={(e) => up("consent", {text: e.target.value})}/></label>
        <label className="field">Страница оферты<input value={o.consent.page_slug} onChange={(e) => up("consent", {page_slug: e.target.value})}/></label>
        <p className="muted">Новая версия оферты снова спросит согласие у всех клиентов.</p>
      </div>
    </div>

    <div className="card">
      <h4>Тексты интерфейса</h4>
      <div className="form-grid">
        {Object.entries(texts).map(([key, value]) => <label className="field" key={key}>{`Текст «${key}»`}<input maxLength={300} placeholder={value} value={o.texts?.[key] ?? ""} onChange={(e) => setO({...o, texts: {...o.texts, [key]: e.target.value}})}/></label>)}
      </div>
    </div>

    <details className="card">
      <summary>Расширенный режим: JSON</summary>
      <label className="field">Конфигурация в JSON<textarea rows={16} spellCheck={false} value={json} onChange={(e) => setJson(e.target.value)} style={{fontFamily: "monospace"}}/></label>
      <button disabled={busy} onClick={saveJson}>Сохранить JSON</button>
      <h4>Что получит Mini App</h4>
      <pre style={{maxHeight: 320, overflow: "auto"}}>{JSON.stringify(data.preview, null, 2)}</pre>
    </details>
  </div>;
}
