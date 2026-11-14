import React, {useEffect, useMemo, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Label = {ru: string; en: string; uk: string};
type Button = {id: string; label: Label; action: string; target: string; style: string; icon: string; visible: boolean; audience: string};
type Section = {id: string; kind: string; enabled: boolean; tab: boolean; title: Label; subtitle: Label; body: Label; icon: string;
  banner: {enabled: boolean; key: string; link: string}; buttons: Button[]};

const LANGS: [keyof Label, string][] = [["ru", "RU"], ["en", "EN"], ["uk", "UK"]];
const STYLES: [string, string][] = [["primary", "Главная"], ["accent", "Акцент"], ["secondary", "Обычная"], ["ghost", "Тихая"], ["danger", "Опасная"]];
const AUDIENCES: [string, string][] = [["any", "Всем"], ["subscribed", "С подпиской"], ["unsubscribed", "Без подписки"]];
const COLORS: [string, string][] = [["accent", "Акцент бренда"], ["accent_2", "Второй акцент"], ["background", "Фон"], ["surface", "Карточки"],
  ["surface_2", "Карточки 2"], ["text", "Текст"], ["muted", "Второстепенный текст"], ["success", "Подключено"], ["danger", "Ошибки"]];
const KIND_TITLES: Record<string, string> = {vpn: "Главный экран VPN", locations: "Локации", premium: "Тарифы", subscription: "Подписка", support: "Поддержка",
  settings: "Настройки", devices: "Устройства", family: "Семья", referral: "Рефералы", wallet: "Баланс", gifts: "Подарки", giveaways: "Розыгрыши", notifications: "Уведомления",
  status: "Состояние сервиса", security: "Безопасность", info: "Документы", custom: "Своя страница"};
const blankLabel = (ru = ""): Label => ({ru, en: "", uk: ""});

function LabelFields({name, value, onChange, max = 60, area = false}: {name: string; value: Label; onChange: (v: Label) => void; max?: number; area?: boolean}) {
  return <div className="ml-label">{LANGS.map(([lang, short]) => <label className="field" key={lang}>{`${name} (${short})`}
    {area ? <textarea rows={2} maxLength={max} value={value[lang] || ""} onChange={(e) => onChange({...value, [lang]: e.target.value})}/>
      : <input maxLength={max} value={value[lang] || ""} placeholder={lang === "ru" ? "" : "как по-русски"} onChange={(e) => onChange({...value, [lang]: e.target.value})}/>}
  </label>)}</div>;
}

const move = <T,>(rows: T[], i: number, d: number): T[] => {
  const j = i + d; if (j < 0 || j >= rows.length) return rows;
  const out = [...rows]; [out[i], out[j]] = [out[j], out[i]]; return out;
};

/** «Бот и кабинет → Приложения Android и iOS»: разделы, кнопки, баннеры, тексты и цвета приложений. */
export function MobileLayoutEditor({data, request, reload, toast, assetBase}: {data: any; request: Request; reload: () => void; toast: (m: string) => void; assetBase: string}) {
  const [layout, setLayout] = useState<any>(null);
  const [open, setOpen] = useState<string>("vpn");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [json, setJson] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => { if (data?.layout) { setLayout(data.layout); setJson(JSON.stringify(data.layout, null, 2)); } }, [data?.layout]);
  const sectionIds = useMemo(() => (layout?.sections || []).map((s: Section) => s.id), [layout]);
  if (!layout) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const actions: Record<string, string> = data.actions || {};
  const icons: string[] = data.icons || [];
  const bannerKeys: Record<string, string> = data.banner_keys || {};
  const texts: Record<string, Label> = data.texts || {};
  const sections: Section[] = layout.sections;
  const tabs = sections.filter((s) => s.tab && s.enabled);

  const setSections = (next: Section[]) => setLayout({...layout, sections: next});
  const setSection = (i: number, patch: Partial<Section>) => setSections(sections.map((s, j) => (j === i ? {...s, ...patch} : s)));
  const setButton = (si: number, bi: number, patch: Partial<Button>) =>
    setSection(si, {buttons: sections[si].buttons.map((b, j) => (j === bi ? {...b, ...patch} : b))});

  async function save(value: any) {
    if (busy) return; setBusy(true); setError("");
    try { await request("/api/admin/mobile-layout", {method: "PUT", body: JSON.stringify(value)}); toast("Макет приложений сохранён — приложения обновят экраны при следующем открытии"); reload(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function reset() {
    if (busy || !window.confirm("Вернуть разделы, кнопки и тексты приложений к стандартным?")) return;
    setBusy(true); setError("");
    try { await request("/api/admin/mobile-layout", {method: "DELETE"}); toast("Возвращён стандартный макет"); reload(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  function addSection() {
    let n = 1; while (sectionIds.includes(`page${n}`)) n += 1;
    const id = `page${n}`;
    setSections([...sections, {id, kind: "custom", enabled: true, tab: false, title: blankLabel("Новая страница"), subtitle: blankLabel(), body: blankLabel(),
      icon: "info", banner: {enabled: false, key: "", link: ""}, buttons: []}]);
    setOpen(id);
  }
  function addButton(si: number) {
    const used = sections[si].buttons.map((b) => b.id);
    let n = 1; while (used.includes(`button${n}`)) n += 1;
    setSection(si, {buttons: [...sections[si].buttons, {id: `button${n}`, label: blankLabel("Новая кнопка"), action: "open", target: "support",
      style: "secondary", icon: "", visible: true, audience: "any"}]});
  }
  const bannerUrl = (s: Section) => {
    if (!layout.banners_enabled || !s.banner.enabled || !s.banner.key) return "";
    const saved = (data.preview?.ru?.sections || []).find((x: any) => x.id === s.id)?.banner?.url;
    return assetBase + (saved && saved.includes(s.banner.key) ? saved : `/api/bot/banners/default/${s.banner.key}.jpg`);
  };
  const current = sections.find((s) => s.id === open) || tabs[0];
  const t = layout.theme;

  return <div className="mobile-layout-editor">
    <div className="card">
      <h3>Приложения Android и iOS</h3>
      <p className="muted">Приложения рисуют все экраны по этому макету (<code>GET /api/mobile/layout</code>): нижнюю панель, порядок и названия разделов, каждую кнопку, баннеры, тексты и цвета. Изменения появляются у клиентов при следующем открытии приложения, без обновления в сторе. Картинки баннеров загружаются в «Баннерах бота» (ключи <code>app-…</code>), здесь выбирается, какой баннер у раздела.</p>
      {error && <div role="alert" className="error">{error}</div>}
      <div className="inline">
        <button className="primary" disabled={busy} onClick={() => save(layout)}>Сохранить</button>
        <button disabled={busy} onClick={reset}>Вернуть стандартный макет</button>
        <span className="muted">В нижней панели: {tabs.length} из 2–5 разделов</span>
      </div>
    </div>

    <div className="ml-grid">
      <div>
        <div className="card">
          <h4>Разделы</h4>
          <p className="muted">«В нижней панели» — вкладка внизу экрана; остальные разделы открываются кнопками. VPN выключить нельзя.</p>
          {sections.map((s, i) => <div key={s.id} className={`ml-section ${open === s.id ? "is-open" : ""}`} data-section={s.id}>
            <div className="ml-section-head">
              <button type="button" className="ml-title" onClick={() => setOpen(open === s.id ? "" : s.id)} aria-expanded={open === s.id}>
                <b>{s.title.ru}</b> <span className="muted">{KIND_TITLES[s.kind] || s.kind} · {s.buttons.length} кн.{s.tab ? " · в панели" : ""}{s.enabled ? "" : " · выключен"}</span>
              </button>
              <button type="button" aria-label={`Выше: ${s.title.ru}`} onClick={() => setSections(move(sections, i, -1))}>↑</button>
              <button type="button" aria-label={`Ниже: ${s.title.ru}`} onClick={() => setSections(move(sections, i, 1))}>↓</button>
            </div>
            {open === s.id && <div className="ml-section-body">
              <div className="inline">
                <label className="inline"><input type="checkbox" checked={s.enabled} disabled={s.kind === "vpn"} onChange={(e) => setSection(i, {enabled: e.target.checked})}/>Раздел включён</label>
                <label className="inline"><input type="checkbox" checked={s.tab} onChange={(e) => setSection(i, {tab: e.target.checked})}/>В нижней панели</label>
                <label className="field">Иконка<select value={s.icon} onChange={(e) => setSection(i, {icon: e.target.value})}>{icons.map((x) => <option key={x}>{x}</option>)}</select></label>
              </div>
              <LabelFields name="Название" value={s.title} onChange={(title) => setSection(i, {title})}/>
              <LabelFields name="Подзаголовок" value={s.subtitle} max={2000} area onChange={(subtitle) => setSection(i, {subtitle})}/>
              {s.kind === "custom" && <LabelFields name="Текст страницы" value={s.body} max={2000} area onChange={(body) => setSection(i, {body})}/>}
              <fieldset className="ml-banner"><legend>Баннер раздела</legend>
                <label className="inline"><input type="checkbox" checked={s.banner.enabled} onChange={(e) => setSection(i, {banner: {...s.banner, enabled: e.target.checked}})}/>Показывать баннер</label>
                <label className="field">Баннер<select value={s.banner.key} onChange={(e) => setSection(i, {banner: {...s.banner, key: e.target.value}})}>
                  <option value="">— без баннера —</option>
                  {Object.entries(bannerKeys).map(([key, title]) => <option key={key} value={key}>{title} ({key})</option>)}
                </select></label>
                <label className="field">Ссылка при нажатии на баннер<input placeholder="https://… или пусто" value={s.banner.link} onChange={(e) => setSection(i, {banner: {...s.banner, link: e.target.value}})}/></label>
                {bannerUrl(s) && <img className="ml-banner-img" src={bannerUrl(s)} alt={`Баннер раздела ${s.title.ru}`}/>}
              </fieldset>

              <h5>Кнопки раздела</h5>
              {s.buttons.length === 0 && <p className="muted">Кнопок нет.</p>}
              {s.buttons.map((b, bi) => <div className="ml-button card" key={bi} data-button={`${s.id}/${b.id}`}>
                <div className="inline">
                  <label className="field">ID<input value={b.id} onChange={(e) => setButton(i, bi, {id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "")})}/></label>
                  <label className="inline"><input type="checkbox" checked={b.visible} onChange={(e) => setButton(i, bi, {visible: e.target.checked})}/>Показывать</label>
                  <button type="button" aria-label={`Кнопка выше: ${b.label.ru}`} onClick={() => setSection(i, {buttons: move(s.buttons, bi, -1)})}>↑</button>
                  <button type="button" aria-label={`Кнопка ниже: ${b.label.ru}`} onClick={() => setSection(i, {buttons: move(s.buttons, bi, 1)})}>↓</button>
                  <button type="button" className="danger" onClick={() => setSection(i, {buttons: s.buttons.filter((_, j) => j !== bi)})}>Удалить кнопку</button>
                </div>
                <LabelFields name="Текст кнопки" value={b.label} onChange={(label) => setButton(i, bi, {label})}/>
                <div className="inline">
                  <label className="field">Действие<select value={b.action} onChange={(e) => {
                    const action = e.target.value;
                    setButton(i, bi, {action, target: action === "open" ? (sectionIds[0] || "") : action === "import_app" ? "happ" : action === "document" ? "faq" : action === "url" ? "https://" : ""});
                  }}>{Object.entries(actions).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>
                  {b.action === "open" && <label className="field">Открывает раздел<select value={b.target} onChange={(e) => setButton(i, bi, {target: e.target.value})}>
                    {sections.map((x) => <option key={x.id} value={x.id}>{x.title.ru}</option>)}</select></label>}
                  {b.action === "import_app" && <label className="field">Приложение<select value={b.target} onChange={(e) => setButton(i, bi, {target: e.target.value})}>
                    {(data.import_apps || []).map((x: string) => <option key={x}>{x}</option>)}</select></label>}
                  {b.action === "document" && <label className="field">Документ<select value={b.target} onChange={(e) => setButton(i, bi, {target: e.target.value})}>
                    {Object.entries(data.documents || {}).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}</select></label>}
                  {b.action === "url" && <label className="field">Ссылка<input value={b.target} placeholder="https://… или tg://…" onChange={(e) => setButton(i, bi, {target: e.target.value})}/></label>}
                  <label className="field">Вид<select value={b.style} onChange={(e) => setButton(i, bi, {style: e.target.value})}>{STYLES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                  <label className="field">Иконка<select value={b.icon} onChange={(e) => setButton(i, bi, {icon: e.target.value})}><option value="">—</option>{icons.map((x) => <option key={x}>{x}</option>)}</select></label>
                  <label className="field">Кому<select value={b.audience} onChange={(e) => setButton(i, bi, {audience: e.target.value})}>{AUDIENCES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                </div>
              </div>)}
              <div className="inline">
                {s.buttons.length < 24 && <button type="button" onClick={() => addButton(i)}>Добавить кнопку</button>}
                {s.kind === "custom" && <button type="button" className="danger" onClick={() => setSections(sections.filter((_, j) => j !== i))}>Удалить страницу</button>}
              </div>
            </div>}
          </div>)}
          {sections.length < 40 && <button type="button" onClick={addSection}>Добавить свою страницу</button>}
        </div>

        <div className="card">
          <h4>Цвета, ссылки и баннеры</h4>
          <div className="ml-colors">{COLORS.map(([key, label]) => <label className="field" key={key}>{label}<input type="color" value={t[key]} onChange={(e) => setLayout({...layout, theme: {...t, [key]: e.target.value}})}/></label>)}</div>
          <label className="field">Скругление карточек, px<input type="number" min={0} max={40} value={t.radius} onChange={(e) => setLayout({...layout, theme: {...t, radius: Number(e.target.value)}})}/></label>
          <label className="inline"><input type="checkbox" checked={!!layout.banners_enabled} onChange={(e) => setLayout({...layout, banners_enabled: e.target.checked})}/>Показывать баннеры разделов</label>
          <label className="field">Личный кабинет (кнопки «Перейти в личный кабинет»)<input placeholder="https://lk.example.com" value={layout.cabinet_url} onChange={(e) => setLayout({...layout, cabinet_url: e.target.value})}/></label>
          <label className="field">Telegram-канал (кнопки «Telegram-канал»)<input placeholder="https://t.me/…" value={layout.telegram_channel} onChange={(e) => setLayout({...layout, telegram_channel: e.target.value})}/></label>
          <p className="muted">Пока ссылка не задана, кнопки с ней в приложениях не показываются.</p>
        </div>

        <div className="card">
          <h4>Тексты интерфейса</h4>
          <p className="muted">Пустое поле — стандартный текст. В «осталось {"{n}"} дн.» число подставляется вместо {"{n}"}.</p>
          {Object.entries(texts).map(([key, def]) => <LabelFields key={key} name={def.ru} value={layout.texts[key] || blankLabel()}
            onChange={(v) => {
              const next = {...layout.texts};
              if (v.ru.trim() || v.en.trim() || v.uk.trim()) next[key] = {...v, ru: v.ru.trim() ? v.ru : def.ru}; else delete next[key];
              setLayout({...layout, texts: next});
            }}/>)}
        </div>

        <div className="card" data-features>
          <h4>Блоки экранов</h4>
          <p className="muted">Что показывать на главном экране, экране входа и в настройках.</p>
          {Object.entries(data.features || {}).map(([key, title]) => <label className="inline" key={key}>
            <input type="checkbox" checked={layout.features?.[key] !== false} onChange={(e) => setLayout({...layout, features: {...(layout.features || {}), [key]: e.target.checked}})}/>{String(title)}
          </label>)}
        </div>

        <div className="card" data-strings>
          <h4>Строки приложения</h4>
          <p className="muted">Любая надпись приложения: экран входа, диалоги, уведомления, ошибки. Найдите строку по тексту или ключу и впишите свой вариант; пустое поле — текст приложения. Изменено строк: {Object.keys(layout.strings || {}).length}.</p>
          <label className="field">Поиск строки<input value={query} placeholder="например: Войти, оплата, sign_in" onChange={(e) => setQuery(e.target.value)}/></label>
          {Object.entries(data.strings || {} as Record<string, Label>)
            .filter(([key, def]: [string, any]) => {
              const q = query.trim().toLowerCase();
              if (!q) return !!layout.strings?.[key];
              return key.includes(q) || Object.values(def).some((v: any) => String(v).toLowerCase().includes(q));
            })
            .slice(0, 40)
            .map(([key, def]: [string, any]) => <div className="ml-string" key={key} data-string={key}>
              <b>{def.ru}</b> <span className="muted"><code>{key}</code></span>
              <LabelFields name={`Строка ${key}`} max={300} value={{ru: "", en: "", uk: "", ...(layout.strings?.[key] || {})}} onChange={(v) => {
                const next = {...(layout.strings || {})};
                if (v.ru.trim() || v.en.trim() || v.uk.trim()) next[key] = v; else delete next[key];
                setLayout({...layout, strings: next});
              }}/>
            </div>)}
          {!query.trim() && !Object.keys(layout.strings || {}).length && <p className="muted">Начните вводить в поиске, чтобы найти строку.</p>}
        </div>

        <details className="card"><summary>Макет в JSON (для переноса между магазинами)</summary>
          <textarea rows={14} value={json} onChange={(e) => setJson(e.target.value)} aria-label="Макет приложений в JSON"/>
          <button type="button" disabled={busy} onClick={() => { try { save(JSON.parse(json)); } catch { setError("JSON с ошибкой: проверьте скобки и кавычки"); } }}>Сохранить JSON</button>
        </details>
      </div>

      <aside className="ml-phone-wrap" aria-label="Предпросмотр приложения">
        <div className="ml-phone" style={{background: t.background, color: t.text, ["--ml-accent" as any]: t.accent, ["--ml-surface" as any]: t.surface, ["--ml-radius" as any]: `${t.radius}px`}}>
          {current && <>
            <div className="ml-phone-title">{current.title.ru}</div>
            {bannerUrl(current) && <img className="ml-phone-banner" src={bannerUrl(current)} alt=""/>}
            {current.kind === "vpn" && <div className="ml-phone-power" style={{borderColor: t.accent}}>⏻</div>}
            {current.subtitle.ru && <p className="ml-phone-sub" style={{color: t.muted}}>{current.subtitle.ru}</p>}
            {current.body.ru && <p className="ml-phone-sub">{current.body.ru}</p>}
            {current.buttons.filter((b) => b.visible).map((b) => <div key={b.id} className={`ml-phone-btn is-${b.style}`}
              style={b.style === "primary" ? {background: t.accent, color: "#1a0f05"} : b.style === "accent" ? {background: t.accent_2, color: "#1a0f05"} : b.style === "danger" ? {color: t.danger, background: t.surface} : {background: t.surface}}>
              {b.label.ru}{b.audience !== "any" && <small> · {AUDIENCES.find(([k]) => k === b.audience)?.[1]}</small>}
            </div>)}
          </>}
          <nav className="ml-phone-tabs" style={{background: t.surface}}>
            {tabs.map((s) => <button type="button" key={s.id} onClick={() => setOpen(s.id)} style={{color: s.id === current?.id ? t.accent : t.muted}}>{s.title.ru}</button>)}
          </nav>
        </div>
        <p className="muted">Предпросмотр на русском. Нажмите вкладку внизу, чтобы открыть раздел.</p>
      </aside>
    </div>
  </div>;
}
