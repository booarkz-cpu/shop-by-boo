import React, {useEffect, useMemo, useRef, useState} from "react";
import {ChevronRight, CircleDollarSign, Search, Users, X, Zap, Activity} from "lucide-react";
import {SECTION_GROUPS, matchesSection, type SectionGroup} from "./sections";

const count = new Intl.NumberFormat("ru-RU");
const money = new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 0});
const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : Number(value) || 0);

function highlight(text: string, query: string) {
  const needle = query.trim().toLowerCase();
  const index = needle ? text.toLowerCase().indexOf(needle) : -1;
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + needle.length)}</mark>
      {text.slice(index + needle.length)}
    </>
  );
}

/**
 * Start page of the panel: key numbers in one row, then every function of
 * the panel grouped into cards. Each entry shows its name and what it is
 * for, so a new administrator can find the right page without guessing.
 */
export function AdminHub<T extends string>({d, navigate, icon}: {d: any; navigate: (tab: T) => void; icon: (tab: T) => React.ReactNode}) {
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const a = d?.analytics || {};
  const users = num(a?.users?.total || d?.remnawave_users?.response?.total);
  const stats = [
    {label: "Пользователи", value: count.format(users), hint: a?.users?.new_24h ? `+${count.format(num(a.users.new_24h))} за сутки` : "всего аккаунтов", icon: <Users aria-hidden="true" />, tone: "info"},
    {label: "Активные подписки", value: count.format(num(a?.subscriptions?.active)), hint: "действующий срок", icon: <Zap aria-hidden="true" />, tone: "ok"},
    {label: "Выручка за сутки", value: `${money.format(num(a?.revenue?.["24h"]))} ₽`, hint: `${money.format(num(a?.revenue?.["30d"]))} ₽ за 30 дней`, icon: <CircleDollarSign aria-hidden="true" />, tone: "info"},
    {label: "Версия API", value: d?.health?.version || d?.version || "—", hint: d?.role ? `ваша роль: ${d.role}` : "магазин работает", icon: <Activity aria-hidden="true" />, tone: "ok"},
  ];
  const groups = useMemo(
    () =>
      (SECTION_GROUPS as readonly SectionGroup[])
        .map((group) => ({...group, items: group.items.filter((item) => matchesSection(item, query))}))
        .filter((group) => group.items.length),
    [query],
  );
  const total = (SECTION_GROUPS as readonly SectionGroup[]).reduce((sum, group) => sum + group.items.length, 0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        event.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="hub">
      <div className="hub-stats" aria-label="Ключевые показатели">
        {stats.map((stat) => (
          <div className={`hub-stat tone-${stat.tone}`} key={stat.label}>
            <span className="hub-stat-icon">{stat.icon}</span>
            <div>
              <b>{stat.value}</b>
              <span>{stat.label}</span>
              <small>{stat.hint}</small>
            </div>
          </div>
        ))}
      </div>
      <div className="hub-toolbar">
        <div>
          <h2>Все функции панели</h2>
          <p>{total} разделов в {SECTION_GROUPS.length} группах. Откройте нужный или найдите его по названию или задаче.</p>
        </div>
        <label className="hub-search" data-no-field-help="">
          <span className="sr-only">Найти функцию</span>
          <Search aria-hidden="true" />
          <input ref={input} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Например: промокод, возврат, логотип" />
          {query && (
            <button type="button" aria-label="Очистить поиск" onClick={() => setQuery("")}>
              <X aria-hidden="true" />
            </button>
          )}
        </label>
      </div>
      {groups.length ? (
        <div className="hub-grid">
          {groups.map((group) => (
            <section className={`hub-card accent-${group.id}`} key={group.id} aria-labelledby={`hub-${group.id}`}>
              <header>
                <span className="hub-count" aria-hidden="true">
                  {group.items.length}
                </span>
                <div>
                  <h3 id={`hub-${group.id}`}>{group.title}</h3>
                  <p>{group.description}</p>
                </div>
              </header>
              <div className="hub-items">
                {group.items.map((item) => (
                  <a
                    className="hub-item"
                    key={item.tab}
                    href={`#${item.tab}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(item.tab as T);
                    }}
                  >
                    <span className="hub-item-icon">{icon(item.tab as T)}</span>
                    <span className="hub-item-copy">
                      <b>{highlight(item.label, query)}</b>
                      <small>{item.description}</small>
                    </span>
                    <ChevronRight className="hub-item-chevron" aria-hidden="true" />
                  </a>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="card empty-state" role="status">
          <h3>Ничего не найдено</h3>
          <p>Попробуйте другое слово: название раздела, действие или платёжную систему.</p>
        </div>
      )}
    </div>
  );
}
