"use client";
import {useEffect} from "react";

/**
 * Root error boundary of the admin panel.
 *
 * A throw during render used to unmount the whole tree, leaving the operator with a
 * black page. Next.js renders this screen instead: the reason, a retry that keeps the
 * session, and a reload as the last resort. Data is never touched by a render failure.
 */
export default function AdminError({error, reset}: {error: Error & {digest?: string}; reset: () => void}) {
  useEffect(() => {
    console.error("admin panel render failed", error);
  }, [error]);
  return (
    <div className="loading-screen" role="alert" aria-label="Ошибка панели управления">
      <div className="card" style={{maxWidth: 720, width: "calc(100% - 32px)"}}>
        <h2>Панель не открылась</h2>
        <p className="muted">
          Ошибка интерфейса: данные не были изменены. Проверьте доступ к API и откройте раздел заново.
        </p>
        <p className="error">{error.message || "Неизвестная ошибка интерфейса"}</p>
        {error.digest && <p className="muted"><code>digest: {error.digest}</code></p>}
        <div className="btn-row">
          <button type="button" className="primary" onClick={() => reset()}>Попробовать снова</button>
          <button type="button" className="btn-ghost" onClick={() => window.location.reload()}>Перезагрузить панель</button>
        </div>
      </div>
    </div>
  );
}
