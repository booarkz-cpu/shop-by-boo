import React, {useState} from "react";
import world from "./worldMap.json";

/** v28.42: vector map of countries for «География клиентов». Natural Earth 1:110m (public domain), equirectangular. */
type Shape = {n: string; d: string};
const MAP = world as unknown as {w: number; h: number; countries: Record<string, Shape>};
const COUNTRIES = MAP.countries;

export function WorldMap({values, label = "клиентов"}: {values: Record<string, number>; label?: string}) {
  const [hover, setHover] = useState<string>("");
  const max = Math.max(1, ...Object.values(values));
  const shade = (n: number) => (n > 0 ? 0.25 + 0.75 * Math.sqrt(n / max) : 0);
  const name = (cc: string) => COUNTRIES[cc]?.n || cc;
  const unknown = Object.keys(values).filter((cc) => !COUNTRIES[cc] && values[cc] > 0);
  return (
    <div className="world-map">
      <svg viewBox={`0 0 ${MAP.w} ${MAP.h}`} role="img" aria-label="Карта стран" style={{width: "100%", height: "auto", display: "block"}}>
        {Object.entries(COUNTRIES).map(([cc, c]) => {
          const n = values[cc] || 0;
          return (
            <path key={cc} d={c.d} data-cc={cc} onMouseEnter={() => setHover(cc)} onMouseLeave={() => setHover("")}
              style={{fill: n ? "var(--accent, #f97316)" : "var(--surface-2, #2a2a33)", fillOpacity: n ? shade(n) : 1,
                stroke: "var(--border, #444)", strokeWidth: hover === cc ? 1.2 : 0.4, cursor: n ? "pointer" : "default"}}>
              <title>{`${name(cc)}: ${n} ${label}`}</title>
            </path>
          );
        })}
      </svg>
      <div className="muted" style={{minHeight: 20, fontSize: 13}}>
        {hover ? `${name(hover)} — ${values[hover] || 0} ${label}` : "Наведите на страну, чтобы увидеть число."}
        {unknown.length ? ` Без страны на карте: ${unknown.map((cc) => `${cc} ${values[cc]}`).join(", ")}.` : ""}
      </div>
    </div>
  );
}
