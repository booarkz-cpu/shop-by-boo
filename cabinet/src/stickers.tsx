"use client";
/**
 * Corgi Lusi sticker screens: the after-payment result, maintenance, "section not found" and
 * render errors. Stickers are bundled in public/assets/stickers (scripts/bot-banners/render.py --assets).
 */
import React, {useEffect, useRef, useState} from "react";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH || "";
type Request = (path: string, options?: RequestInit) => Promise<any>;
export type StickerName = "waiting" | "success" | "error404" | "bugs" | "maintenance" | "goodbye" | "holiday" | "gift" | "vip" | "payment" | "delivery";

export const stickerUrl = (name: StickerName) => `${BASE}/assets/stickers/${name}.webp`;

export function StickerState({sticker, title, text, children, tone = "info"}: {sticker: StickerName; title: string; text?: string; children?: React.ReactNode; tone?: "info" | "ok" | "warn" | "error"}) {
  return (
    <div className="sticker-state" data-sticker={sticker} data-tone={tone} role={tone === "error" ? "alert" : "status"}>
      <img src={stickerUrl(sticker)} alt="" width={220} height={220} loading="lazy" />
      <h2>{title}</h2>
      {text && <p>{text}</p>}
      {children && <div className="btn-row">{children}</div>}
    </div>
  );
}

/** Order number from the payment page return address (?order=…). */
export function orderFromUrl(search = typeof location === "undefined" ? "" : location.search): string {
  const raw = new URLSearchParams(search).get("order") || "";
  return /^[A-Za-z0-9:_-]{6,128}$/.test(raw) ? raw : "";
}

export function clearOrderFromUrl() {
  const url = new URL(location.href);
  url.searchParams.delete("order");
  history.replaceState(null, "", url.pathname + url.search + url.hash);
}

const POLL_MS = 3000;
const POLL_LIMIT = 60; // three minutes, then the customer is told the payment may take longer

/** After returning from the payment page: waits for the shop to confirm the order, then says how it went. */
export function PaymentResult({order, request, onDone, go}: {order: string; request: Request; onDone: () => void; go: (kind: string) => void}) {
  const [state, setState] = useState<any>({state: "pending"});
  const [tries, setTries] = useState(0);
  const stop = useRef(false);
  useEffect(() => {
    stop.current = false;
    let timer: any;
    async function poll(n: number) {
      try {
        const r = await request(`/api/me/payments/order/${encodeURIComponent(order)}`);
        if (stop.current) return;
        setState(r);
        if (r.state === "paid" || r.state === "failed" || r.state === "refunded") return;
      } catch (e: any) {
        if (stop.current) return;
        if (e?.status === 404) { setState({state: "missing"}); return; }
      }
      setTries(n + 1);
      if (n + 1 < POLL_LIMIT) timer = setTimeout(() => poll(n + 1), POLL_MS);
    }
    poll(0);
    return () => { stop.current = true; clearTimeout(timer); };
  }, [order]);
  const close = () => { clearOrderFromUrl(); onDone(); };
  const topup = state.purpose === "topup";
  if (state.state === "paid") {
    return <StickerState sticker="success" tone="ok" title="Оплата прошла!" text={topup ? `Баланс пополнен на ${state.amount} ${state.currency}.` : "Подписка уже работает. Осталось подключить устройство."}>
      {!topup && <button className="btn-primary" onClick={() => { close(); go("connection"); }}>Подключить</button>}
      <button className="btn-ghost" onClick={close}>Готово</button>
    </StickerState>;
  }
  if (state.state === "failed" || state.state === "missing" || state.state === "refunded") {
    return <StickerState sticker="error404" tone="error" title={state.state === "refunded" ? "Платёж возвращён" : "Оплата не прошла"}
      text={state.state === "missing" ? "Мы не нашли этот платёж в вашем аккаунте." : state.state === "refunded" ? "Деньги вернутся тем же способом оплаты." : "Деньги не списаны. Попробуйте ещё раз или выберите другой способ оплаты."}>
      <button className="btn-primary" onClick={() => { close(); go(topup ? "wallet" : "plans"); }}>Попробовать снова</button>
      <button className="btn-ghost" onClick={close}>Закрыть</button>
    </StickerState>;
  }
  const long = tries >= POLL_LIMIT;
  return <StickerState sticker="waiting" title={state.state === "processing" ? "Оплата получена, подключаем…" : "Ждём подтверждения оплаты"}
    text={long ? "Платёжная система отвечает дольше обычного. Как только оплата подтвердится, подписка появится сама — эту страницу можно закрыть." : "Обычно это занимает несколько секунд."}>
    <button className="btn-ghost" onClick={close}>{long ? "Закрыть" : "Скрыть"}</button>
  </StickerState>;
}

/** Shown while the API answers 503 «maintenance»: retries by itself every 30 seconds. */
export function MaintenanceScreen({onRetry}: {onRetry: () => void}) {
  useEffect(() => { const t = setInterval(onRetry, 30000); return () => clearInterval(t); }, [onRetry]);
  return <StickerState sticker="maintenance" tone="warn" title="Идут технические работы" text="Магазин скоро вернётся. Подписки работают как обычно — VPN не отключается.">
    <button className="btn-primary" onClick={onRetry}>Проверить снова</button>
  </StickerState>;
}

export const MAINTENANCE_EVENT = "lusi:maintenance";
/** True for the API answer that means the shop is in maintenance mode. */
export const isMaintenance = (status: number, detail: unknown) => status === 503 && /maintenance|технич/i.test(String(detail || ""));
