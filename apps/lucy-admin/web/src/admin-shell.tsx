import React, {useEffect, useRef, useState} from "react";
import {ChevronRight, LayoutGrid, LogOut, Menu, PanelLeftClose, PanelLeftOpen, PawPrint, RefreshCw, Search, ShieldCheck, X} from "lucide-react";
import {matchesSection, sectionInfo, type SectionGroup, type SectionItem} from "./sections";
import {PreferencesMenu} from "./components/preferences-menu";
import {Skeleton} from "./components/ui/skeleton";
import {StatusDot} from "./components/ui/status";


type ShellProps<T extends string> = {
  groups: SectionGroup<T>[];
  tab: T;
  onNavigate: (tab: T) => void;
  icon: (tab: T) => React.ReactNode;
  brandName: string;
  logoUrl?: string;
  theme: "dark" | "light";
  onThemeChange: (theme: "dark" | "light") => void;
  loading: boolean;
  onRefresh: () => void;
  onLogout: () => void;
  children: React.ReactNode;
};

const COLLAPSE_KEY = "rw_sidebar_collapsed";

const normalize = (text: string | null | undefined) => (text || "").replace(/\s+/g, " ").trim().toLowerCase();

/**
 * Sections were written as standalone pages and often start with a heading
 * that repeats the page title, or put a table titled like the card around it.
 * The page header already shows the title, so such repeats are hidden.
 */
function hideRepeatedHeadings(root: HTMLElement, title: string) {
  const headings = Array.from(root.querySelectorAll<HTMLElement>("h2, h3"));
  const first = headings[0];
  headings.forEach((heading, index) => {
    const text = normalize(heading.textContent);
    const previous = index > 0 ? normalize(headings[index - 1].textContent) : "";
    const repeatsTitle = heading === first && text === normalize(title);
    const repeatsPrevious = text !== "" && text === previous && !headings[index - 1].hasAttribute("data-repeated-heading");
    if (repeatsTitle || repeatsPrevious) {
      if (!heading.hasAttribute("data-repeated-heading")) {
        heading.setAttribute("data-repeated-heading", "true");
        heading.setAttribute("aria-hidden", "true");
      }
    } else if (heading.hasAttribute("data-repeated-heading")) {
      heading.removeAttribute("data-repeated-heading");
      heading.removeAttribute("aria-hidden");
    }
  });
}

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Admin chrome: fixed sidebar on desktop (collapsible to an icon rail) and a
 * slide-in drawer below 1050px opened from the hamburger in the top-left corner.
 */
export function AdminShell<T extends string>(props: ShellProps<T>) {
  const {groups, tab, onNavigate, icon, brandName, logoUrl, theme, onThemeChange, loading, onRefresh, onLogout, children} = props;
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [navQuery, setNavQuery] = useState("");
  const [command, setCommand] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [commandIndex, setCommandIndex] = useState(0);
  const menuButton = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const flat: SectionItem<T>[] = groups.flatMap((group) => group.items);
  const {item: current, group: currentGroup} = sectionInfo(tab);
  const visibleGroups = groups
    .map((group) => ({...group, items: group.items.filter((item) => matchesSection(item, navQuery))}))
    .filter((group) => group.items.length);
  const commandHits = flat.filter((item) => matchesSection(item, commandQuery)).slice(0, 12);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* Storage can be unavailable in private windows; the toggle still works for this page. */
    }
  }, [collapsed]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommand(true);
        setCommandQuery("");
        setCommandIndex(0);
      }
      if (event.key === "Escape") {
        setCommand(false);
        if (drawer) {
          setDrawer(false);
          menuButton.current?.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  useEffect(() => {
    // Lock page scroll behind the open drawer so mobile users cannot scroll two layers.
    document.body.classList.toggle("drawer-locked", drawer);
    return () => document.body.classList.remove("drawer-locked");
  }, [drawer]);

  const pageTitle = current?.label || "Все разделы";
  useEffect(() => {
    const root = content.current;
    if (!root) return;
    let frame = 0;
    const run = () => {
      frame = 0;
      hideRepeatedHeadings(root, pageTitle);
    };
    run();
    const observer = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(run);
    });
    observer.observe(root, {childList: true, subtree: true, characterData: true});
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [pageTitle]);

  function go(next: T) {
    onNavigate(next);
    setDrawer(false);
    setCommand(false);
  }

  return (
    <div className="app-shell" data-collapsed={collapsed ? "true" : "false"}>
      <div className={drawer ? "sidebar-backdrop open" : "sidebar-backdrop"} onClick={() => setDrawer(false)} aria-hidden="true" />
      <aside className={drawer ? "sidebar open" : "sidebar"} aria-label="Навигация панели">
        <div className="brand">
          <div className="brand-icon">{logoUrl ? <img src={logoUrl} alt="" /> : <PawPrint aria-hidden="true" />}</div>
          <div className="brand-copy">
            <strong>{brandName}</strong>
            <span>Панель управления</span>
          </div>
          <button type="button" className="sidebar-close" aria-label="Закрыть меню" onClick={() => setDrawer(false)}>
            <X aria-hidden="true" />
          </button>
        </div>
        <label className="nav-search">
          <Search aria-hidden="true" />
          <input aria-label="Найти раздел" placeholder="Найти раздел…" value={navQuery} onChange={(event) => setNavQuery(event.target.value)} />
          <kbd>⌘K</kbd>
        </label>
        <nav className="sidebar-scroll">
          <button
            type="button"
            className={tab === "panel" ? "nav-item nav-hub active" : "nav-item nav-hub"}
            aria-current={tab === "panel" ? "page" : undefined}
            title={collapsed ? "Все разделы" : undefined}
            onClick={() => go("panel" as T)}
          >
            <i>
              <LayoutGrid aria-hidden="true" />
            </i>
            <span>Все разделы</span>
          </button>
          {visibleGroups.map((group) => (
            <section className="nav-group" key={group.id}>
              <div className="nav-group-title">{group.title}</div>
              {group.items.map((item) => (
                <button
                  type="button"
                  key={item.tab}
                  className={tab === item.tab ? "nav-item active" : "nav-item"}
                  aria-current={tab === item.tab ? "page" : undefined}
                  title={collapsed ? item.label : item.description}
                  onClick={() => go(item.tab)}
                >
                  <i>{icon(item.tab)}</i>
                  <span>{item.label}</span>
                </button>
              ))}
            </section>
          ))}
          {!visibleGroups.length && <p className="nav-empty">Раздел не найден</p>}
        </nav>
        <div className="sidebar-foot">
          <div className="online">
            <StatusDot tone="ok" pulse />
            <span>Система работает штатно</span>
          </div>
          <button type="button" className="nav-item collapse-toggle" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"} aria-pressed={collapsed}>
            <i>{collapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}</i>
            <span>{collapsed ? "Развернуть меню" : "Свернуть меню"}</span>
          </button>
          <button type="button" className="nav-item" onClick={onLogout} title={collapsed ? "Выйти" : undefined}>
            <i>
              <LogOut aria-hidden="true" />
            </i>
            <span>Выйти</span>
          </button>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <button ref={menuButton} type="button" className="mobile-menu" aria-label="Открыть меню" aria-expanded={drawer} onClick={() => setDrawer(true)}>
            <Menu aria-hidden="true" />
          </button>
          <div className="page-heading">
            <nav className="breadcrumb" aria-label="Путь к разделу">
              <button type="button" onClick={() => go("panel" as T)}>
                Админ-панель
              </button>
              {currentGroup && (
                <>
                  <ChevronRight aria-hidden="true" />
                  <span>{currentGroup.title}</span>
                </>
              )}
            </nav>
            <h1>{current?.label || "Все разделы"}</h1>
          </div>
          <div className="topbar-actions">
            <button type="button" className="command-trigger" onClick={() => setCommand(true)}>
              <Search aria-hidden="true" />
              <span>Быстрый поиск</span>
              <kbd>⌘K</kbd>
            </button>
            <div className="secure">
              <ShieldCheck aria-hidden="true" />
              Защищено
            </div>
            <button type="button" className={loading ? "round-btn is-spinning" : "round-btn"} onClick={onRefresh} title="Обновить" aria-label="Обновить">
              <RefreshCw aria-hidden="true" />
            </button>
            <PreferencesMenu theme={theme} onThemeChange={onThemeChange} />
          </div>
        </header>
        <div className="content-wrap" ref={content}>
          {current && tab !== "panel" && <p className="page-description">{current.description}</p>}
          {children}
        </div>
      </main>
      {command && (
        <div className="command-overlay" onClick={() => setCommand(false)}>
          <div className="command-box" role="dialog" aria-modal="true" aria-label="Быстрый поиск" onClick={(event) => event.stopPropagation()}>
            <div className="command-search" data-no-field-help="">
              <Search aria-hidden="true" />
              <input
                autoFocus
                aria-label="Поиск раздела"
                value={commandQuery}
                onChange={(event) => {
                  setCommandQuery(event.target.value);
                  setCommandIndex(0);
                }}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setCommandIndex((index) => Math.min(index + 1, commandHits.length - 1));
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setCommandIndex((index) => Math.max(index - 1, 0));
                  } else if (event.key === "Enter" && commandHits[commandIndex]) {
                    event.preventDefault();
                    go(commandHits[commandIndex].tab);
                  }
                }}
                placeholder="Название раздела или задача…"
              />
              <kbd>ESC</kbd>
            </div>
            <div className="command-results">
              {commandHits.map((item, index) => (
                <button type="button" key={item.tab} className={index === commandIndex ? "is-active" : ""} onMouseEnter={() => setCommandIndex(index)} onClick={() => go(item.tab)}>
                  <span>{icon(item.tab)}</span>
                  <span className="command-copy">
                    <b>{item.label}</b>
                    <small>{item.description}</small>
                  </span>
                  <kbd>↵</kbd>
                </button>
              ))}
              {!commandHits.length && <p className="nav-empty">Раздел не найден</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Placeholder with the same footprint as the section it replaces. */
export function SectionSkeleton({dashboard}: {dashboard: boolean}) {
  if (dashboard) {
    return (
      <div className="dash" role="status" aria-label="Загрузка раздела">
        <Skeleton className="sk-banner" />
        <div className="dash-metrics">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton className="sk-metric" key={index} />
          ))}
        </div>
        <Skeleton className="sk-strip" />
        <div className="dash-columns">
          <Skeleton className="sk-panel" />
          <Skeleton className="sk-panel" />
        </div>
      </div>
    );
  }
  return (
    <div className="section-skeleton" role="status" aria-label="Загрузка раздела">
      <Skeleton className="sk-toolbar" />
      <div className="card sk-card">
        {[0, 1, 2, 3, 4, 5].map((index) => (
          <div className="sk-row" key={index}>
            <Skeleton className="sk-cell sk-cell-wide" />
            <Skeleton className="sk-cell" />
            <Skeleton className="sk-cell" />
            <Skeleton className="sk-cell sk-cell-narrow" />
          </div>
        ))}
      </div>
    </div>
  );
}
