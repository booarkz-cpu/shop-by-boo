// A compact VT100/xterm screen model for the node terminal: enough of the control
// sequences used by shells, less, top, htop and vim. Pure TypeScript with erasable
// syntax only, so it also runs under `node --experimental-strip-types` in tests.

export type Cell = {ch: string; fg: string | null; bg: string | null; bold: boolean; underline: boolean; inverse: boolean; dim: boolean};
type Style = Omit<Cell, "ch">;

const BASE16 = [
  "#1e1e2e", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de",
  "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#ffffff",
];

export function color256(n: number): string {
  if (n < 16) return BASE16[n];
  if (n < 232) {
    const v = n - 16;
    const level = (x: number) => (x === 0 ? 0 : 55 + x * 40);
    const r = level(Math.floor(v / 36)), g = level(Math.floor(v / 6) % 6), b = level(v % 6);
    return `rgb(${r},${g},${b})`;
  }
  const grey = 8 + (n - 232) * 10;
  return `rgb(${grey},${grey},${grey})`;
}

const plain = (): Style => ({fg: null, bg: null, bold: false, underline: false, inverse: false, dim: false});
const blank = (style: Style): Cell => ({ch: " ", ...style, underline: false, inverse: false, bold: false, dim: false, fg: null});

export class Screen {
  cols: number;
  rows: number;
  lines: Cell[][];
  scrollback: Cell[][] = [];
  x = 0;
  y = 0;
  style: Style = plain();
  cursorVisible = true;
  appCursor = false;
  bracketedPaste = false;
  autowrap = true;
  title = "";
  onReply: (data: string) => void = () => {};
  private wrapPending = false;
  private top = 0;
  private bottom: number;
  private saved = {x: 0, y: 0, style: plain()};
  private alt: {lines: Cell[][]; x: number; y: number} | null = null;
  private state: "ground" | "esc" | "csi" | "osc" | "charset" = "ground";
  private params = "";
  private osc = "";
  private maxScrollback: number;

  constructor(cols = 80, rows = 24, maxScrollback = 1000) {
    this.cols = cols;
    this.rows = rows;
    this.bottom = rows - 1;
    this.maxScrollback = maxScrollback;
    this.lines = Array.from({length: rows}, () => this.row());
  }

  private row(): Cell[] {
    return Array.from({length: this.cols}, () => blank(this.style));
  }

  get altScreen(): boolean {
    return this.alt !== null;
  }

  /** Text of one screen line without trailing spaces (tests, copy). */
  text(y: number): string {
    return this.lines[y].map((c) => c.ch).join("").replace(/\s+$/, "");
  }

  resize(cols: number, rows: number): void {
    cols = Math.max(2, Math.floor(cols));
    rows = Math.max(2, Math.floor(rows));
    const fit = (line: Cell[]) => (line.length >= cols ? line.slice(0, cols) : [...line, ...Array.from({length: cols - line.length}, () => blank(plain()))]);
    this.cols = cols;
    let lines = this.lines.map(fit);
    while (lines.length > rows) {
      const removed = lines.shift() as Cell[];
      if (!this.alt) this.pushScrollback(removed);
      this.y = Math.max(0, this.y - 1);
    }
    while (lines.length < rows) lines.push(this.row());
    this.lines = lines;
    this.rows = rows;
    this.top = 0;
    this.bottom = rows - 1;
    this.x = Math.min(this.x, cols - 1);
    this.y = Math.min(this.y, rows - 1);
    this.wrapPending = false;
  }

  private pushScrollback(line: Cell[]): void {
    this.scrollback.push(line);
    if (this.scrollback.length > this.maxScrollback) this.scrollback.shift();
  }

  private scrollUp(count = 1): void {
    for (let i = 0; i < count; i += 1) {
      const removed = this.lines.splice(this.top, 1)[0];
      if (this.top === 0 && !this.alt) this.pushScrollback(removed);
      this.lines.splice(this.bottom, 0, this.row());
    }
  }

  private scrollDown(count = 1): void {
    for (let i = 0; i < count; i += 1) {
      this.lines.splice(this.bottom, 1);
      this.lines.splice(this.top, 0, this.row());
    }
  }

  private lineFeed(): void {
    if (this.y === this.bottom) this.scrollUp();
    else if (this.y < this.rows - 1) this.y += 1;
  }

  private put(ch: string): void {
    if (this.wrapPending && this.autowrap) {
      this.x = 0;
      this.lineFeed();
    }
    this.wrapPending = false;
    this.lines[this.y][this.x] = {ch, ...this.style};
    if (this.x === this.cols - 1) this.wrapPending = true;
    else this.x += 1;
  }

  write(data: string): void {
    for (const ch of data) {
      const code = ch.codePointAt(0) as number;
      switch (this.state) {
        case "ground":
          if (code === 0x1b) this.state = "esc";
          else if (code === 0x0d) { this.x = 0; this.wrapPending = false; }
          else if (code === 0x0a || code === 0x0b || code === 0x0c) { this.lineFeed(); this.wrapPending = false; }
          else if (code === 0x08) { this.x = Math.max(0, this.x - 1); this.wrapPending = false; }
          else if (code === 0x09) { this.x = Math.min(this.cols - 1, (Math.floor(this.x / 8) + 1) * 8); this.wrapPending = false; }
          else if (code === 0x07 || code < 0x20 || code === 0x7f) { /* bell and other controls draw nothing */ }
          else this.put(ch);
          break;
        case "esc":
          this.escape(ch);
          break;
        case "charset":
          this.state = "ground"; // ESC ( B and friends: one designator character
          break;
        case "csi":
          if (code >= 0x40 && code <= 0x7e) {
            this.csi(ch, this.params);
            this.params = "";
            this.state = "ground";
          } else if (this.params.length < 64) this.params += ch;
          break;
        case "osc":
          if (code === 0x07 || (code === 0x5c && this.osc.endsWith("\x1b"))) {
            const body = this.osc.replace(/\x1b$/, "");
            const [id, ...rest] = body.split(";");
            if (id === "0" || id === "2") this.title = rest.join(";").slice(0, 200);
            this.osc = "";
            this.state = "ground";
          } else if (this.osc.length < 1024) this.osc += ch;
          break;
      }
    }
  }

  private escape(ch: string): void {
    this.state = "ground";
    switch (ch) {
      case "[": this.state = "csi"; this.params = ""; break;
      case "]": this.state = "osc"; this.osc = ""; break;
      case "(": case ")": case "*": case "+": this.state = "charset"; break;
      case "7": this.saved = {x: this.x, y: this.y, style: {...this.style}}; break;
      case "8": this.x = this.saved.x; this.y = this.saved.y; this.style = {...this.saved.style}; this.wrapPending = false; break;
      case "D": this.lineFeed(); break;
      case "E": this.x = 0; this.lineFeed(); break;
      case "M": if (this.y === this.top) this.scrollDown(); else this.y = Math.max(0, this.y - 1); break;
      case "c": this.reset(); break;
      default: break; // ESC = / ESC > (keypad) and unsupported sequences are ignored
    }
  }

  reset(): void {
    this.style = plain();
    this.lines = Array.from({length: this.rows}, () => this.row());
    this.x = this.y = this.top = 0;
    this.bottom = this.rows - 1;
    this.alt = null;
    this.appCursor = this.bracketedPaste = false;
    this.cursorVisible = this.autowrap = true;
  }

  private csi(final: string, raw: string): void {
    const priv = raw.startsWith("?");
    const nums = raw.replace(/^[?>=]/, "").split(";").map((p) => (p === "" ? NaN : parseInt(p, 10)));
    const n = (i: number, fallback = 1) => (Number.isNaN(nums[i]) || nums[i] === undefined ? fallback : nums[i]);
    const clampX = (v: number) => Math.max(0, Math.min(this.cols - 1, v));
    const clampY = (v: number) => Math.max(0, Math.min(this.rows - 1, v));
    this.wrapPending = false;
    switch (final) {
      case "A": this.y = Math.max(this.y >= this.top ? this.top : 0, this.y - Math.max(1, n(0))); break;
      case "B": this.y = Math.min(this.y <= this.bottom ? this.bottom : this.rows - 1, this.y + Math.max(1, n(0))); break;
      case "C": this.x = clampX(this.x + Math.max(1, n(0))); break;
      case "D": this.x = clampX(this.x - Math.max(1, n(0))); break;
      case "E": this.x = 0; this.y = clampY(this.y + Math.max(1, n(0))); break;
      case "F": this.x = 0; this.y = clampY(this.y - Math.max(1, n(0))); break;
      case "G": case "`": this.x = clampX(n(0) - 1); break;
      case "d": this.y = clampY(n(0) - 1); break;
      case "H": case "f": this.y = clampY(n(0) - 1); this.x = clampX(n(1) - 1); break;
      case "J": this.eraseDisplay(n(0, 0)); break;
      case "K": this.eraseLine(n(0, 0)); break;
      case "X": for (let i = 0; i < Math.max(1, n(0)) && this.x + i < this.cols; i += 1) this.lines[this.y][this.x + i] = blank(this.style); break;
      case "P": { const line = this.lines[this.y]; line.splice(this.x, Math.max(1, n(0))); while (line.length < this.cols) line.push(blank(this.style)); break; }
      case "@": { const line = this.lines[this.y]; for (let i = 0; i < Math.max(1, n(0)); i += 1) line.splice(this.x, 0, blank(this.style)); line.length = this.cols; break; }
      case "L": if (this.y >= this.top && this.y <= this.bottom) for (let i = 0; i < Math.max(1, n(0)); i += 1) { this.lines.splice(this.bottom, 1); this.lines.splice(this.y, 0, this.row()); } break;
      case "M": if (this.y >= this.top && this.y <= this.bottom) for (let i = 0; i < Math.max(1, n(0)); i += 1) { this.lines.splice(this.y, 1); this.lines.splice(this.bottom, 0, this.row()); } break;
      case "S": this.scrollUp(Math.max(1, n(0))); break;
      case "T": this.scrollDown(Math.max(1, n(0))); break;
      case "r": {
        const top = clampY(n(0) - 1), bottom = clampY(n(1, this.rows) - 1);
        if (top < bottom) { this.top = top; this.bottom = bottom; this.x = 0; this.y = 0; }
        break;
      }
      case "s": this.saved = {x: this.x, y: this.y, style: {...this.style}}; break;
      case "u": this.x = this.saved.x; this.y = this.saved.y; break;
      case "m": this.sgr(nums); break;
      case "n": if (n(0) === 6) this.onReply(`\x1b[${this.y + 1};${this.x + 1}R`); else if (n(0) === 5) this.onReply("\x1b[0n"); break;
      case "c": if (!raw.startsWith(">")) this.onReply("\x1b[?1;2c"); break;
      case "h": case "l": if (priv) this.mode(nums, final === "h"); break;
      default: break;
    }
  }

  private mode(nums: number[], on: boolean): void {
    for (const m of nums) {
      if (m === 1) this.appCursor = on;
      else if (m === 7) this.autowrap = on;
      else if (m === 25) this.cursorVisible = on;
      else if (m === 2004) this.bracketedPaste = on;
      else if (m === 47 || m === 1047 || m === 1049) {
        if (on && !this.alt) {
          if (m === 1049) this.saved = {x: this.x, y: this.y, style: {...this.style}};
          this.alt = {lines: this.lines, x: this.x, y: this.y};
          this.lines = Array.from({length: this.rows}, () => this.row());
          this.x = this.y = 0;
        } else if (!on && this.alt) {
          this.lines = this.alt.lines.map((line) => (line.length === this.cols ? line : [...line, ...Array.from({length: Math.max(0, this.cols - line.length)}, () => blank(plain()))].slice(0, this.cols)));
          while (this.lines.length < this.rows) this.lines.push(this.row());
          this.lines.length = this.rows;
          this.x = Math.min(this.alt.x, this.cols - 1);
          this.y = Math.min(this.alt.y, this.rows - 1);
          this.alt = null;
          if (m === 1049) { this.x = this.saved.x; this.y = Math.min(this.saved.y, this.rows - 1); }
        }
        this.top = 0;
        this.bottom = this.rows - 1;
      }
    }
  }

  private eraseDisplay(mode: number): void {
    if (mode === 0) {
      this.eraseLine(0);
      for (let y = this.y + 1; y < this.rows; y += 1) this.lines[y] = this.row();
    } else if (mode === 1) {
      this.eraseLine(1);
      for (let y = 0; y < this.y; y += 1) this.lines[y] = this.row();
    } else {
      this.lines = Array.from({length: this.rows}, () => this.row());
      if (mode === 3) this.scrollback = [];
    }
  }

  private eraseLine(mode: number): void {
    const line = this.lines[this.y];
    const [from, to] = mode === 0 ? [this.x, this.cols] : mode === 1 ? [0, this.x + 1] : [0, this.cols];
    for (let x = from; x < to; x += 1) line[x] = blank(this.style);
  }

  private sgr(nums: number[]): void {
    if (nums.length === 0 || (nums.length === 1 && Number.isNaN(nums[0]))) nums = [0];
    for (let i = 0; i < nums.length; i += 1) {
      const p = Number.isNaN(nums[i]) ? 0 : nums[i];
      if (p === 0) this.style = plain();
      else if (p === 1) this.style.bold = true;
      else if (p === 2) this.style.dim = true;
      else if (p === 4) this.style.underline = true;
      else if (p === 7) this.style.inverse = true;
      else if (p === 22) this.style.bold = this.style.dim = false;
      else if (p === 24) this.style.underline = false;
      else if (p === 27) this.style.inverse = false;
      else if (p >= 30 && p <= 37) this.style.fg = BASE16[p - 30];
      else if (p >= 90 && p <= 97) this.style.fg = BASE16[p - 90 + 8];
      else if (p === 39) this.style.fg = null;
      else if (p >= 40 && p <= 47) this.style.bg = BASE16[p - 40];
      else if (p >= 100 && p <= 107) this.style.bg = BASE16[p - 100 + 8];
      else if (p === 49) this.style.bg = null;
      else if (p === 38 || p === 48) {
        let value: string | null = null;
        if (nums[i + 1] === 5 && !Number.isNaN(nums[i + 2])) { value = color256(Math.max(0, Math.min(255, nums[i + 2]))); i += 2; }
        else if (nums[i + 1] === 2) { const [r, g, b] = [nums[i + 2], nums[i + 3], nums[i + 4]].map((v) => Math.max(0, Math.min(255, v || 0))); value = `rgb(${r},${g},${b})`; i += 4; }
        if (p === 38) this.style.fg = value; else this.style.bg = value;
      }
    }
  }
}

export type KeyLike = {key: string; code?: string; ctrlKey?: boolean; altKey?: boolean; metaKey?: boolean; shiftKey?: boolean};

/** Bytes a terminal sends for a key press, or null when the browser should handle it. */
export function keyToInput(event: KeyLike, appCursor = false): string | null {
  const {key, ctrlKey, altKey, metaKey} = event;
  if (metaKey) return null;
  const arrows: Record<string, string> = {ArrowUp: "A", ArrowDown: "B", ArrowRight: "C", ArrowLeft: "D"};
  if (key in arrows) return (appCursor ? "\x1bO" : "\x1b[") + arrows[key];
  const special: Record<string, string> = {
    Enter: "\r", Backspace: "\x7f", Tab: "\t", Escape: "\x1b", Home: "\x1b[H", End: "\x1b[F", Insert: "\x1b[2~", Delete: "\x1b[3~",
    PageUp: "\x1b[5~", PageDown: "\x1b[6~", F1: "\x1bOP", F2: "\x1bOQ", F3: "\x1bOR", F4: "\x1bOS", F5: "\x1b[15~", F6: "\x1b[17~",
    F7: "\x1b[18~", F8: "\x1b[19~", F9: "\x1b[20~", F10: "\x1b[21~", F11: "\x1b[23~", F12: "\x1b[24~",
  };
  if (key === "Tab" && event.shiftKey) return "\x1b[Z";
  if (key in special) return (altKey ? "\x1b" : "") + special[key];
  if ([...key].length !== 1) return null;
  if (ctrlKey && !altKey) {
    // Ctrl+C on a Russian layout reports key "с": use the physical key instead.
    const physical = event.code && /^Key[A-Z]$/.test(event.code) ? event.code.slice(3).toLowerCase() : "";
    const lower = physical || key.toLowerCase();
    if (lower >= "a" && lower <= "z") return String.fromCharCode(lower.charCodeAt(0) - 96);
    const map: Record<string, string> = {"@": "\x00", " ": "\x00", "[": "\x1b", "\\": "\x1c", "]": "\x1d", "^": "\x1e", _: "\x1f", "?": "\x7f"};
    return map[key] ?? null;
  }
  return (altKey ? "\x1b" : "") + key;
}
