import React from "react";

/**
 * Page and card states of the admin panel (v28.61.0, stage 7; docs/ru/new/UI_UX_GUIDE.md).
 *
 * Every block that loads data shows one of: loading, error with the reason and «Повторить», empty with what
 * to do next, or the content. A block is never left blank (a black screen) and never shows an endless
 * spinner after a failure.
 */
export function LoadState({error, onRetry, label = "Загрузка…"}: {error?: string; onRetry?: () => void; label?: string}) {
  if (error) return <div className="card state-card" data-state="error">
    <div role="alert" className="error">{error}</div>
    {onRetry && <button className="primary" onClick={onRetry}>Повторить</button>}
  </div>;
  return <div className="card state-card" data-state="loading" aria-busy="true"><p className="muted">{label}</p></div>;
}

export function EmptyState({title, hint, action}: {title: string; hint?: string; action?: React.ReactNode}) {
  return <div className="empty-state" data-state="empty">
    <b>{title}</b>
    {hint && <p className="muted">{hint}</p>}
    {action}
  </div>;
}

export function SuccessNote({children}: {children: React.ReactNode}) {
  return <div role="status" className="success" data-state="success">{children}</div>;
}
