"use client";
import {useEffect} from "react";

/**
 * Root error boundary of the cabinet and the Telegram Mini App.
 *
 * Without this file a throw during render unmounts the whole React tree and the
 * customer sees a black page with no way out. Next.js renders this screen instead:
 * it names the failure, keeps the rest of the app reachable and offers a retry.
 */
export default function CabinetError({error, reset}: {error: Error & {digest?: string}; reset: () => void}) {
  useEffect(() => {
    // The browser console is the only place a customer can copy the reason from.
    console.error("cabinet render failed", error);
  }, [error]);
  return (
    <main className="boot" role="alert" aria-label="Ошибка кабинета">
      <div className="boot-body">
        <div className="form-card">
          <h2>Кабинет не открылся</h2>
          <p className="muted">
            Люси уже поймала ошибку: остальные разделы работают, а подписка и платежи не затронуты.
            Попробуйте открыть экран ещё раз.
          </p>
          <p className="error">{error.message || "Неизвестная ошибка интерфейса"}</p>
          <div className="btn-row">
            <button type="button" className="btn-primary" onClick={() => reset()}>Попробовать снова</button>
            <button type="button" className="btn-ghost" onClick={() => window.location.reload()}>Перезагрузить кабинет</button>
          </div>
        </div>
      </div>
    </main>
  );
}
