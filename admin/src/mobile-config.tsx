import React, {useEffect, useMemo, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Lang = "ru" | "en" | "uk";
type Text = {ru: string; en: string; uk: string};

const LANGS: [Lang, string][] = [["ru", "RU"], ["en", "EN"], ["uk", "UK"]];
const TAB_NAMES: Record<string, string> = {home: "VPN (главная)", plans: "Тарифы", profile: "Профиль", support: "Поддержка", servers: "Локации",
  info: "Информация", wallet: "Кошелёк", family: "Семья", status: "Статус сервиса", devices: "Устройства", referral: "Друзья"};
const BLOCK_NAMES: Record<string, string> = {notice: "Строка-объявление", connect: "Кнопка «Подключить» и статус", usage: "Трафик и срок",
  server: "Выбор сервера", promo: "Акции", buttons: "Свои кнопки", trial: "Пробный период"};
const LOGIN_NAMES: Record<string, string> = {telegram: "Telegram", yandex: "Яндекс ID", vk: "VK ID", google: "Google", email: "Почта и пароль", passkey: "Ключ доступа"};
const PROFILE_NAMES: Record<string, string> = {email: "Почта", telegram: "Telegram", id: "ID аккаунта", subscription: "Подписка", devices: "Устройства",
  family: "Семья", referral: "Пригласить друга", wallet: "Кошелёк", language: "Язык", documents: "Документы", logout: "Выйти"};
const ACTIONS: Record<string, string> = {link: "Ссылка", section: "Раздел приложения", telegram_bot: "Бот магазина", telegram_channel: "Telegram-канал",
  support: "Поддержка в боте", connect: "Подключить", plans: "Тарифы"};
const ICONS = ["send", "message", "help", "mail", "phone", "globe", "gift", "users", "star", "heart", "shield", "zap", "server", "wallet", "info", "file",
  "lock", "list", "trophy", "smartphone", "plug", "bell", "key", "sparkles", "rocket", "clock", "home", "flag", "card"];
const CLIENTS = ["auto", "happ", "v2rayng", "hiddify", "streisand", "v2raytun"];

const blankText = (): Text => ({ru: "", en: "", uk: ""});
const pick = (t: Text | undefined, lang: Lang) => ((t && (t[lang] || t.ru)) || "").trim();

function TextField({label, value, lang, onChange, area, max = 300}: {label: string; value: Text; lang: Lang; onChange: (t: Text) => void; area?: boolean; max?: number}) {
  const v = value || blankText();
  const props = {value: v[lang] || "", maxLength: max, placeholder: lang === "ru" ? "" : `Пусто — как на русском: ${v.ru || "—"}`,
    onChange: (e: any) => onChange({...v, [lang]: e.target.value})};
  return <label className="field">{label} <span className="muted">({lang.toUpperCase()})</span>{area ? <textarea rows={2} {...props}/> : <input {...props}/>}</label>;
}

function move<T>(list: T[], i: number, d: number): T[] {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const out = [...list];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

/** «Бот и кабинет → Приложения Android и iOS»: everything the customer apps show (GET /api/mobile/config). */
export function MobileConfigEditor({request, toast}: {request: Request; toast: (m: string) => void}) {
  const [cfg, setCfg] = useState<any>(null);
  const [defaults, setDefaults] = useState<any>(null);
  const [providers, setProviders] = useState<string[]>([]);
  const [lang, setLang] = useState<Lang>("ru");
  const [screen, setScreen] = useState("home");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setError("");
    try {
      const r = await request("/api/admin/mobile-config");
      setCfg(r.config); setDefaults(r.defaults); setProviders(r.providers || []);
    } catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);
  const up = (section: string, patch: any) => setCfg({...cfg, [section]: {...cfg[section], ...patch}});

  async function save() {
    if (busy) return; setBusy(true); setError("");
    try { await request("/api/admin/mobile-config", {method: "PUT", body: JSON.stringify(cfg)}); toast("Приложения обновятся при следующем запуске"); await load(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function reset() {
    if (busy || !confirm("Вернуть все настройки приложений по умолчанию?")) return;
    setBusy(true); setError("");
    try { await request("/api/admin/mobile-config", {method: "DELETE"}); toast("Возвращены настройки по умолчанию"); await load(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  const enabledTabs = useMemo(() => (cfg?.tabs || []).filter((t: any) => t.enabled), [cfg]);
  if (!cfg) return <div className="card">{error ? <div role="alert" className="error">{error}</div> : <p className="muted">Загрузка…</p>}</div>;
  const look = cfg.look;

  return <div className="mobile-config">
    <div className="mobile-config-main">
      <div className="card">
        <p className="muted">Всё, что видит клиент в приложениях Android и iOS: оформление, вкладки, главный экран, кнопки, вход, тарифы, поддержка и профиль. Приложения получают настройки при запуске и обновлении экрана; без сети показывают последние сохранённые.</p>
        {error && <div role="alert" className="error">{error}</div>}
        <div className="doc-tabs" role="tablist" aria-label="Язык текстов">
          {LANGS.map(([code, name]) => <button key={code} role="tab" aria-selected={code === lang} className={code === lang ? "primary" : ""} onClick={() => setLang(code)}>{name}</button>)}
        </div>
        <div className="btn-row"><button className="primary" disabled={busy} onClick={save}>{busy ? "Сохранение…" : "Сохранить"}</button><button disabled={busy} onClick={load}>Отменить изменения</button><button className="danger" disabled={busy} onClick={reset}>Сбросить всё</button></div>
      </div>

      <section className="card" aria-label="Оформление">
        <h3>Оформление</h3>
        <label className="field">Название в приложении<input value={look.app_name} maxLength={40} placeholder="Пусто — название магазина" onChange={(e) => up("look", {app_name: e.target.value})}/></label>
        <label className="field">Логотип (https://… или /media/…)<input value={look.logo_url} onChange={(e) => up("look", {logo_url: e.target.value})}/></label>
        <label className="field">Тема<select value={look.mode} onChange={(e) => up("look", {mode: e.target.value})}><option value="dark">Тёмная</option><option value="light">Светлая</option><option value="system">Как в системе</option></select></label>
        <label className="inline"><input type="checkbox" checked={look.use_miniapp_colors} onChange={(e) => up("look", {use_miniapp_colors: e.target.checked})}/> Цвета как в Mini App</label>
        {!look.use_miniapp_colors && <div className="color-grid">
          {[["accent", "Акцент"], ["accent_2", "Второй акцент"], ["background", "Фон"], ["surface", "Карточки"], ["text", "Текст"], ["muted", "Второстепенный текст"]].map(([k, name]) =>
            <label className="field" key={k}>{name}<input type="color" value={look[k]} onChange={(e) => up("look", {[k]: e.target.value})}/></label>)}
        </div>}
        <label className="field">Скругление карточек, px<input type="number" min={0} max={40} value={look.radius} onChange={(e) => up("look", {radius: Number(e.target.value)})}/></label>
      </section>

      <section className="card" aria-label="Нижняя панель">
        <h3>Нижняя панель</h3>
        <p className="muted">От двух до пяти вкладок; «VPN» обязательна. Порядок — как в списке.</p>
        {cfg.tabs.map((t: any, i: number) => <div className="mc-row" key={t.id} data-tab={t.id}>
          <label className="inline"><input type="checkbox" checked={t.enabled} onChange={(e) => setCfg({...cfg, tabs: cfg.tabs.map((x: any, j: number) => j === i ? {...x, enabled: e.target.checked} : x)})}/> {TAB_NAMES[t.id]}</label>
          <input aria-label={`Название вкладки ${TAB_NAMES[t.id]}`} value={t.title?.[lang] || ""} placeholder="Название по умолчанию" maxLength={300}
                 onChange={(e) => setCfg({...cfg, tabs: cfg.tabs.map((x: any, j: number) => j === i ? {...x, title: {...(x.title || blankText()), [lang]: e.target.value}} : x)})}/>
          <button aria-label="Выше" disabled={i === 0} onClick={() => setCfg({...cfg, tabs: move(cfg.tabs, i, -1)})}>↑</button>
          <button aria-label="Ниже" disabled={i === cfg.tabs.length - 1} onClick={() => setCfg({...cfg, tabs: move(cfg.tabs, i, 1)})}>↓</button>
        </div>)}
      </section>

      <section className="card" aria-label="Главный экран">
        <h3>Главный экран</h3>
        {cfg.home.blocks.map((b: any, i: number) => <div className="mc-row" key={b.kind}>
          <label className="inline"><input type="checkbox" checked={b.enabled} onChange={(e) => up("home", {blocks: cfg.home.blocks.map((x: any, j: number) => j === i ? {...x, enabled: e.target.checked} : x)})}/> {BLOCK_NAMES[b.kind]}</label>
          <button aria-label="Выше" disabled={i === 0} onClick={() => up("home", {blocks: move(cfg.home.blocks, i, -1)})}>↑</button>
          <button aria-label="Ниже" disabled={i === cfg.home.blocks.length - 1} onClick={() => up("home", {blocks: move(cfg.home.blocks, i, 1)})}>↓</button>
        </div>)}
        <TextField label="Объявление (пусто — не показывать)" value={cfg.home.notice} lang={lang} onChange={(v) => up("home", {notice: v})}/>
        <label className="field">Ссылка объявления<input value={cfg.home.notice_link} placeholder="https://t.me/… или пусто" onChange={(e) => up("home", {notice_link: e.target.value})}/></label>
        <TextField label="Кнопка подключения" value={cfg.home.connect_title} lang={lang} onChange={(v) => up("home", {connect_title: v})}/>
        <TextField label="Статус: подписка активна" value={cfg.home.connected_title} lang={lang} onChange={(v) => up("home", {connected_title: v})}/>
        <TextField label="Статус: подписки нет" value={cfg.home.disconnected_title} lang={lang} onChange={(v) => up("home", {disconnected_title: v})}/>
        <TextField label="Подсказка под кнопкой" value={cfg.home.connect_hint} lang={lang} area onChange={(v) => up("home", {connect_hint: v})}/>
        <label className="field">Приложение VPN для кнопки «Подключить»<select value={cfg.home.preferred_client} onChange={(e) => up("home", {preferred_client: e.target.value})}>{CLIENTS.map((c) => <option key={c} value={c}>{c === "auto" ? "Выбрать автоматически" : c}</option>)}</select></label>
      </section>

      <section className="card" aria-label="Свои кнопки">
        <h3>Свои кнопки</h3>
        <p className="muted">Кнопки на главном экране, в профиле или в поддержке: ссылка, раздел приложения, бот, канал, поддержка.</p>
        {cfg.buttons.map((b: any, i: number) => {
          const set = (patch: any) => setCfg({...cfg, buttons: cfg.buttons.map((x: any, j: number) => j === i ? {...x, ...patch} : x)});
          return <div className="config-row card" key={i} data-button={b.id}>
            <label className="inline"><input type="checkbox" checked={b.enabled} onChange={(e) => set({enabled: e.target.checked})}/> Показывать</label>
            <label className="field">ID<input value={b.id} maxLength={32} onChange={(e) => set({id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "")})}/></label>
            <TextField label="Название" value={b.title} lang={lang} onChange={(v) => set({title: v})}/>
            <TextField label="Подпись" value={b.subtitle} lang={lang} onChange={(v) => set({subtitle: v})}/>
            <label className="field">Действие<select value={b.action} onChange={(e) => set({action: e.target.value})}>{Object.entries(ACTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            {["link", "section", "telegram_channel"].includes(b.action) && <label className="field">{b.action === "section" ? "Раздел" : b.action === "telegram_channel" ? "Канал (@имя)" : "Ссылка"}
              {b.action === "section" ? <select value={b.target} onChange={(e) => set({target: e.target.value})}><option value="">—</option>{Object.entries(TAB_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                : <input value={b.target} onChange={(e) => set({target: e.target.value})}/>}</label>}
            <label className="field">Иконка<select value={b.icon} onChange={(e) => set({icon: e.target.value})}>{ICONS.map((x) => <option key={x}>{x}</option>)}</select></label>
            <label className="field">Стиль<select value={b.style} onChange={(e) => set({style: e.target.value})}><option value="secondary">Обычная</option><option value="primary">Основная</option><option value="accent">Акцентная</option></select></label>
            <label className="field">Где показывать<select value={b.placement} onChange={(e) => set({placement: e.target.value})}><option value="home">Главный экран</option><option value="profile">Профиль</option><option value="support">Поддержка</option></select></label>
            <div className="btn-row">
              <button disabled={i === 0} onClick={() => setCfg({...cfg, buttons: move(cfg.buttons, i, -1)})}>Выше</button>
              <button className="danger" onClick={() => setCfg({...cfg, buttons: cfg.buttons.filter((_: any, j: number) => j !== i)})}>Удалить</button>
            </div>
          </div>;
        })}
        {cfg.buttons.length < 12 && <button onClick={() => setCfg({...cfg, buttons: [...cfg.buttons, {id: `button-${cfg.buttons.length + 1}`, enabled: true, title: {ru: "Новая кнопка", en: "", uk: ""}, subtitle: blankText(), icon: "send", action: "telegram_bot", target: "", style: "secondary", placement: "home"}]})}>Добавить кнопку</button>}
      </section>

      <section className="card" aria-label="Экран входа">
        <h3>Экран входа</h3>
        <TextField label="Заголовок" value={cfg.login.title} lang={lang} onChange={(v) => up("login", {title: v})}/>
        <TextField label="Подзаголовок" value={cfg.login.subtitle} lang={lang} onChange={(v) => up("login", {subtitle: v})}/>
        <p className="muted">Способы входа и порядок. Telegram, Яндекс, VK и Google показываются, только если в .env заданы их ключи (сейчас настроены: {providers.length ? providers.map((p) => LOGIN_NAMES[p]).join(", ") : "только почта и ключ доступа"}).</p>
        {Object.keys(LOGIN_NAMES).map((m) => {
          const on = cfg.login.methods.includes(m);
          const i = cfg.login.methods.indexOf(m);
          return <div className="mc-row" key={m}>
            <label className="inline"><input type="checkbox" checked={on} onChange={(e) => up("login", {methods: e.target.checked ? [...cfg.login.methods, m] : cfg.login.methods.filter((x: string) => x !== m)})}/> {LOGIN_NAMES[m]}{!["email", "passkey"].includes(m) && !providers.includes(m) && <span className="muted"> · не настроен</span>}</label>
            {on && <><button aria-label="Выше" disabled={i === 0} onClick={() => up("login", {methods: move(cfg.login.methods, i, -1)})}>↑</button><button aria-label="Ниже" disabled={i === cfg.login.methods.length - 1} onClick={() => up("login", {methods: move(cfg.login.methods, i, 1)})}>↓</button></>}
          </div>;
        })}
        <label className="inline"><input type="checkbox" checked={cfg.login.show_legal} onChange={(e) => up("login", {show_legal: e.target.checked})}/> Ссылки на политику и оферту</label>
        <TextField label="Текст о согласии" value={cfg.login.legal_text} lang={lang} area onChange={(v) => up("login", {legal_text: v})}/>
      </section>

      <section className="card" aria-label="Тарифы">
        <h3>Тарифы</h3>
        <TextField label="Заголовок" value={cfg.plans.title} lang={lang} onChange={(v) => up("plans", {title: v})}/>
        <TextField label="Подзаголовок" value={cfg.plans.subtitle} lang={lang} onChange={(v) => up("plans", {subtitle: v})}/>
        <TextField label="Колонка «пробный»" value={cfg.plans.trial_label} lang={lang} onChange={(v) => up("plans", {trial_label: v})}/>
        <TextField label="Колонка «платный»" value={cfg.plans.paid_label} lang={lang} onChange={(v) => up("plans", {paid_label: v})}/>
        <h4>Сравнение</h4>
        {cfg.plans.compare.map((r: any, i: number) => {
          const set = (patch: any) => up("plans", {compare: cfg.plans.compare.map((x: any, j: number) => j === i ? {...x, ...patch} : x)});
          return <div className="mc-row" key={i}>
            <input aria-label={`Строка ${i + 1}`} placeholder="Трафик" value={r.label?.[lang] || ""} onChange={(e) => set({label: {...r.label, [lang]: e.target.value}})}/>
            <input aria-label={`Пробный ${i + 1}`} placeholder="5 ГБ" value={r.trial} maxLength={40} onChange={(e) => set({trial: e.target.value})}/>
            <input aria-label={`Платный ${i + 1}`} placeholder="Безлимит" value={r.paid} maxLength={40} onChange={(e) => set({paid: e.target.value})}/>
            <button className="danger" aria-label="Удалить строку" onClick={() => up("plans", {compare: cfg.plans.compare.filter((_: any, j: number) => j !== i)})}>×</button>
          </div>;
        })}
        {cfg.plans.compare.length < 10 && <button onClick={() => up("plans", {compare: [...cfg.plans.compare, {label: blankText(), trial: "", paid: ""}]})}>Добавить строку</button>}
        <TextField label="Подпись под оплатой" value={cfg.plans.footnote} lang={lang} area onChange={(v) => up("plans", {footnote: v})}/>
        <label className="field">ID тарифа с отметкой «выгодно» (пусто — нет)<input type="number" min={1} value={cfg.plans.highlight_plan_id ?? ""} onChange={(e) => up("plans", {highlight_plan_id: e.target.value ? Number(e.target.value) : null})}/></label>
      </section>

      <section className="card" aria-label="Поддержка и профиль">
        <h3>Поддержка</h3>
        <TextField label="Заголовок" value={cfg.support.title} lang={lang} onChange={(v) => up("support", {title: v})}/>
        <label className="inline"><input type="checkbox" checked={cfg.support.show_faq} onChange={(e) => up("support", {show_faq: e.target.checked})}/> Частые вопросы из «Документов»</label>
        <label className="inline"><input type="checkbox" checked={cfg.support.ticket_form} onChange={(e) => up("support", {ticket_form: e.target.checked})}/> Форма обращения в приложении</label>
        <TextField label="Чат: заголовок" value={cfg.support.chat_title} lang={lang} onChange={(v) => up("support", {chat_title: v})}/>
        <TextField label="Чат: подпись" value={cfg.support.chat_text} lang={lang} onChange={(v) => up("support", {chat_text: v})}/>
        <h3>Профиль</h3>
        {Object.keys(PROFILE_NAMES).map((k) => <label className="inline" key={k}><input type="checkbox" checked={cfg.profile.items.includes(k)}
          onChange={(e) => up("profile", {items: e.target.checked ? [...cfg.profile.items, k] : cfg.profile.items.filter((x: string) => x !== k)})}/> {PROFILE_NAMES[k]}</label>)}
        <TextField label="Приглашение: заголовок" value={cfg.profile.referral_title} lang={lang} onChange={(v) => up("profile", {referral_title: v})}/>
        <TextField label="Приглашение: текст" value={cfg.profile.referral_text} lang={lang} area onChange={(v) => up("profile", {referral_text: v})}/>
        <h3>Акции</h3>
        <label className="field">Источник<select value={cfg.promos.source} onChange={(e) => up("promos", {source: e.target.value})}><option value="miniapp">Как в Mini App</option><option value="off">Не показывать</option><option value="own">Свои для приложений (JSON ниже)</option></select></label>
        {cfg.promos.source === "own" && <PromoJson value={cfg.promos.cards} onChange={(cards) => up("promos", {cards})}/>}
      </section>
    </div>

    <aside className="mobile-preview" aria-label="Предпросмотр приложения">
      <div className="doc-tabs" role="tablist" aria-label="Экран предпросмотра">
        {[["home", "Главная"], ["login", "Вход"], ["plans", "Тарифы"], ["support", "Поддержка"]].map(([k, v]) =>
          <button key={k} role="tab" aria-selected={screen === k} className={screen === k ? "primary" : ""} onClick={() => setScreen(k)}>{v}</button>)}
      </div>
      <Phone cfg={cfg} lang={lang} screen={screen} tabs={enabledTabs} providers={providers}/>
      {defaults && <p className="muted">Предпросмотр приблизительный: шрифты и отступы на телефоне свои.</p>}
    </aside>
  </div>;
}

function PromoJson({value, onChange}: {value: any[]; onChange: (v: any[]) => void}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [bad, setBad] = useState(false);
  return <label className="field">Карточки акций (JSON: id, title, text, discount, ends_at, button_text, link, sticker)
    <textarea rows={6} value={text} onChange={(e) => { setText(e.target.value); try { onChange(JSON.parse(e.target.value)); setBad(false); } catch { setBad(true); } }}/>
    {bad && <span className="error">JSON с ошибкой</span>}
  </label>;
}

function Phone({cfg, lang, screen, tabs, providers}: {cfg: any; lang: Lang; screen: string; tabs: any[]; providers: string[]}) {
  const c = cfg.look.use_miniapp_colors ? {accent: "#39ff88", accent_2: "#22d3ee", background: "#070b12", surface: "#0e1522", text: "#e8f1ff", muted: "#8a99b3"} : cfg.look;
  const style = {"--p-accent": c.accent, "--p-accent2": c.accent_2, "--p-bg": c.background, "--p-surface": c.surface, "--p-text": c.text, "--p-muted": c.muted,
    "--p-radius": `${cfg.look.radius}px`} as React.CSSProperties;
  const blocks = cfg.home.blocks.filter((b: any) => b.enabled).map((b: any) => b.kind);
  const homeButtons = cfg.buttons.filter((b: any) => b.enabled && b.placement === "home");
  const ready = (m: string) => ["email", "passkey"].includes(m) || providers.includes(m);
  return <div className="phone" style={style} data-screen={screen}>
    <div className="phone-head"><b>{cfg.look.app_name || "Корги Люси"}</b></div>
    <div className="phone-body">
      {screen === "home" && blocks.map((k: string) => {
        if (k === "notice") return pick(cfg.home.notice, lang) ? <div key={k} className="p-notice">{pick(cfg.home.notice, lang)}</div> : null;
        if (k === "connect") return <div key={k} className="p-connect"><div className="p-orb">⏻</div><b>{pick(cfg.home.connect_title, lang)}</b><span>{pick(cfg.home.connected_title, lang)}</span></div>;
        if (k === "usage") return <div key={k} className="p-card"><span>Трафик</span><b>38 из 100 ГБ</b><i className="p-bar"/></div>;
        if (k === "server") return <div key={k} className="p-card">🇳🇱 Амстердам <span className="p-ok">●●●●</span></div>;
        if (k === "promo") return cfg.promos.source === "off" ? null : <div key={k} className="p-card p-promo">Акция −25%</div>;
        if (k === "trial") return <div key={k} className="p-card">Пробный период</div>;
        if (k === "buttons") return homeButtons.length ? <div key={k} className="p-buttons">{homeButtons.map((b: any) => <span key={b.id} className={`p-btn ${b.style}`}>{pick(b.title, lang)}</span>)}</div> : null;
        return null;
      })}
      {screen === "login" && <div className="p-login">
        <h4>{pick(cfg.login.title, lang)}</h4><p>{pick(cfg.login.subtitle, lang)}</p>
        {cfg.login.methods.filter(ready).map((m: string) => <span key={m} className="p-btn secondary">{LOGIN_NAMES[m]}</span>)}
        {cfg.login.show_legal && <small>{pick(cfg.login.legal_text, lang)}</small>}
      </div>}
      {screen === "plans" && <div className="p-plans">
        <h4>{pick(cfg.plans.title, lang)}</h4>
        <table><thead><tr><th/><th>{pick(cfg.plans.trial_label, lang)}</th><th>{pick(cfg.plans.paid_label, lang)}</th></tr></thead>
          <tbody>{cfg.plans.compare.map((r: any, i: number) => <tr key={i}><td>{pick(r.label, lang)}</td><td>{r.trial}</td><td>{r.paid}</td></tr>)}</tbody></table>
        <span className="p-btn primary">1 месяц · 199 ₽</span><small>{pick(cfg.plans.footnote, lang)}</small>
      </div>}
      {screen === "support" && <div className="p-support">
        <h4>{pick(cfg.support.title, lang)}</h4>
        {cfg.support.show_faq && <><div className="p-card">Частые вопросы ▾</div><div className="p-card">Как подключиться? ▾</div></>}
        <div className="p-card"><b>{pick(cfg.support.chat_title, lang)}</b><span>{pick(cfg.support.chat_text, lang)}</span></div>
        {cfg.buttons.filter((b: any) => b.enabled && b.placement === "support").map((b: any) => <span key={b.id} className={`p-btn ${b.style}`}>{pick(b.title, lang)}</span>)}
      </div>}
    </div>
    <nav className="phone-tabs">{tabs.map((t: any) => <span key={t.id} className={t.id === "home" ? "on" : ""}>{pick(t.title, lang) || TAB_NAMES[t.id].split(" ")[0]}</span>)}</nav>
  </div>;
}
