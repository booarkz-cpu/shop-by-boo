#!/usr/bin/env node
/**
 * Moves every inline <script> of a Next.js static export into a same-origin file.
 *
 * Production serves the panels with `Content-Security-Policy: script-src 'self'`
 * (deploy/Caddyfile). Next.js boots by streaming its RSC payload through inline
 * `self.__next_f.push(...)` scripts, which that policy blocks. Replacing each one
 * with `<script src>` at the same position keeps execution order (they stay
 * parser-blocking, in document order) while keeping the CSP free of
 * 'unsafe-inline' and per-build hashes.
 *
 * Usage: node csp-externalize.mjs <exportDir> [basePath]
 */
import {createHash} from "node:crypto";
import {mkdirSync, readdirSync, readFileSync, statSync, writeFileSync} from "node:fs";
import {join, relative} from "node:path";

const outDir = process.argv[2] || "dist";
const basePath = (process.argv[3] ?? process.env.NEXT_BASE_PATH ?? "").replace(/\/$/, "");
const assetDir = join(outDir, "_next", "static", "csp");
const EXECUTABLE = /^(?:|text\/javascript|application\/javascript|module)$/i;

function htmlFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "_next" ? [] : htmlFiles(path);
    return name.endsWith(".html") ? [path] : [];
  });
}

mkdirSync(assetDir, {recursive: true});
let moved = 0;
for (const file of htmlFiles(outDir)) {
  const html = readFileSync(file, "utf8");
  const next = html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi, (whole, attrs, body) => {
    if (/\ssrc\s*=/i.test(attrs) || !body.trim()) return whole;
    const type = (attrs.match(/\stype\s*=\s*["']?([^"'\s>]+)/i) || [])[1] || "";
    if (!EXECUTABLE.test(type)) return whole; // JSON/data blocks are not executed and need no CSP permission.
    const name = createHash("sha256").update(body).digest("hex").slice(0, 20) + ".js";
    writeFileSync(join(assetDir, name), body);
    moved += 1;
    const keep = attrs.replace(/\s(?:async|defer)(?=\s|$)/gi, "");
    return `<script${keep} src="${basePath}/_next/static/csp/${name}"></script>`;
  });
  if (next !== html) writeFileSync(file, next);
  if (/<script\b(?![^>]*\ssrc=)[^>]*>\s*[^<\s]/i.test(next.replace(/<script\b[^>]*type=["']?application\/(?:ld\+)?json[^>]*>[\s\S]*?<\/script>/gi, ""))) {
    console.error(`csp-externalize: inline script left in ${relative(outDir, file)}`);
    process.exit(1);
  }
}
console.log(`csp-externalize: moved ${moved} inline scripts to ${relative(process.cwd(), assetDir)}`);
