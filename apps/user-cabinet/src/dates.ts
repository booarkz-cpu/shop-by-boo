/**
 * Times from the shop's API are UTC. Most of them come without a zone («2026-11-15T10:00:00»: naive datetimes of the
 * backend), and `new Date()` reads such a string as the browser's local time — in Moscow a subscription that ends
 * at 10:00 UTC would show 10:00 instead of 13:00, and the «days left» counter would be three hours off.
 * Every server time in the cabinet goes through these helpers (v28.159.0, REQ-SHOP-0022).
 */
const ZONE = /(Z|[+-]\d{2}:?\d{2})$/i;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/** Milliseconds of a server time; NaN for an empty or broken value. */
export function serverTime(value?: string | number | Date | null): number {
  if (value === null || value === undefined || value === "") return NaN;
  if (value instanceof Date) return value.getTime();
  if (typeof value === "number") return value;
  const text = String(value).trim();
  if (DATE_TIME.test(text) && !ZONE.test(text)) return Date.parse(text.replace(" ", "T") + "Z");
  return Date.parse(text);
}

export const serverDate = (value?: string | number | Date | null): Date => new Date(serverTime(value));
