/**
 * Shapes the panel must survive whatever the server answers.
 *
 * Two historic crashes of the panel came from trusting the shape of an answer:
 * "(s || []).map is not a function" — a list arrived wrapped in an object;
 * "Cannot read properties of undefined (reading 'trim')" — a label arrived without one of its languages.
 */

/** Any answer as an array: a bare list, a list wrapped as items / results / data, or nothing. */
export const list = (v: any): any[] =>
  Array.isArray(v) ? v : Array.isArray(v?.items) ? v.items : Array.isArray(v?.results) ? v.results : Array.isArray(v?.data) ? v.data : [];

export type Label = {ru: string; en: string; uk: string};

/** A label with all three languages as strings, whatever was stored. */
export const label = (v: any): Label => {
  const text = (x: any) => (typeof x === "string" ? x : x == null ? "" : String(x));
  const src = v && typeof v === "object" && !Array.isArray(v) ? v : {ru: v};
  return {ru: text(src.ru), en: text(src.en), uk: text(src.uk)};
};

/** True when no language of the label has visible text. */
export const blank = (v: any): boolean => {
  const l = label(v);
  return !(l.ru.trim() || l.en.trim() || l.uk.trim());
};
