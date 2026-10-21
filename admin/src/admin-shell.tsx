import React, {useEffect, useRef, useState} from "react";
import {ChevronRight, LogOut, Menu, PanelLeftClose, PanelLeftOpen, PawPrint, RefreshCw, Search, ShieldCheck, X} from "lucide-react";
import {PreferencesMenu} from "./components/preferences-menu";
import {Skeleton} from "./components/ui/skeleton";
import {StatusDot} from "./components/ui/status";

export type NavEntry<T extends string> = [T, string, string];
export type NavGroup<T extends string> = {title: string; items: NavEntry<T>[]};

type ShellProps<T extends string> = {
  groups: NavGroup<T>[];
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
  const flat = groups.flatMap((group) => group.items);
  const current = flat.find((item) => item[0] === tab);
  const query = navQuery.trim().toLowerCase();
  const visibleGroups = groups
    .map((group) => ({...group, items: group.items.filter((item) => item[2].toLowerCase().includes(query))}))
    .filter((group) => group.items.length);
  const commandHits = flat.filter((item) => item[2].toLowerCase().includes(commandQuery.trim().toLowerCase())).slice(0, 12);

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
            <span>CONTROL CENTER</span>
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
          {visibleGroups.map((group) => (
            <section className="nav-group" key={group.title}>
              <div className="nav-group-title">{group.title}</div>
              {group.items.map((item) => (
                <button
                  type="button"
                  key={item[0]}
                  className={tab === item[0] ? "nav-item active" : "nav-item"}
                  aria-current={tab === item[0] ? "page" : undefined}
                  title={collapsed ? item[2] : undefined}
                  onClick={() => go(item[0])}
                >
                  <i>{icon(item[0])}</i>
                  <span>{item[2]}</span>
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
            <div className="breadcrumb">
              {brandName.toUpperCase()} <ChevronRight aria-hidden="true" /> {current?.[2]?.toUpperCase()}
            </div>
            <h1>{current?.[2] || "Обзор"}</h1>
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
        <div className="content-wrap">{children}</div>
      </main>
      {command && (
        <div className="command-overlay" onClick={() => setCommand(false)}>
          <div className="command-box" role="dialog" aria-modal="true" aria-label="Быстрый поиск" onClick={(event) => event.stopPropagation()}>
            <div className="command-search">
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
                    go(commandHits[commandIndex][0]);
                  }
                }}
                placeholder="Поиск раздела…"
              />
              <kbd>ESC</kbd>
            </div>
            <div className="command-results">
              {commandHits.map((item, index) => (
                <button type="button" key={item[0]} className={index === commandIndex ? "is-active" : ""} onMouseEnter={() => setCommandIndex(index)} onClick={() => go(item[0])}>
                  <span>{icon(item[0])}</span>
                  {item[2]}
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
