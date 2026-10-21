import React, {useRef} from "react";

export type Tone = "ok" | "warn" | "danger" | "idle" | "info";

export function Skeleton({className = "", style}: {className?: string; style?: React.CSSProperties}) {
  return <div aria-hidden="true" className={`ui-skeleton ${className}`} style={style} />;
}

export function StatusDot({tone, pulse = false}: {tone: Tone; pulse?: boolean}) {
  return <span aria-hidden="true" className="ui-dot" data-tone={tone} data-pulse={pulse || undefined} />;
}

export function StatusBadge({tone, children}: {tone: Tone; children: React.ReactNode}) {
  return (
    <span className="ui-badge" data-tone={tone}>
      <StatusDot tone={tone} />
      {children}
    </span>
  );
}

/** Horizontal meter. `value` is 0..1; `null` renders an indeterminate (unknown) bar. */
export function Meter({value, tone = "info", label}: {value: number | null; tone?: Tone; label: string}) {
  const pct = value === null ? null : Math.max(0, Math.min(1, value));
  return (
    <div
      className="ui-meter"
      data-tone={tone}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct === null ? undefined : Math.round(pct * 100)}
    >
      <span style={{width: pct === null ? "100%" : `${pct * 100}%`}} data-unknown={pct === null || undefined} />
    </div>
  );
}

export function Segmented<T extends string>({value, options, onChange, label}: {value: T; options: {value: T; label: string}[]; onChange: (value: T) => void; label: string}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function move(index: number, delta: number) {
    const next = (index + delta + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }
  return (
    <div className="ui-segmented" role="radiogroup" aria-label={label}>
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            data-state={checked ? "on" : "off"}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                event.preventDefault();
                move(index, 1);
              } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault();
                move(index, -1);
              }
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

const GB = 1024 ** 3;
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(Number(bytes))) return "—";
  const value = Number(bytes);
  if (value >= GB * 1024) return `${(value / GB / 1024).toFixed(2)} ТБ`;
  if (value >= GB) return `${(value / GB).toFixed(value >= GB * 100 ? 0 : 1)} ГБ`;
  return `${Math.max(0, value / 1024 ** 2).toFixed(0)} МБ`;
}

export function daysLeft(expires?: string | null): number | null {
  if (!expires) return null;
  const end = new Date(expires).getTime();
  if (!Number.isFinite(end)) return null;
  return Math.ceil((end - Date.now()) / 86_400_000);
}

export function pluralDays(n: number): string {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return "дней";
  if (last === 1) return "день";
  if (last >= 2 && last <= 4) return "дня";
  return "дней";
}
