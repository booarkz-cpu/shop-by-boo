// Shapes the panel must survive: run with `node --experimental-strip-types --test tests/admin-safe.test.mjs`.
// The two crashes named in the requirements register (REQ-QA-0005/0006, 0043/0044).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {list, label, blank} from '../apps/lucy-admin/web/src/safe.ts';

const src = (name) => fs.readFileSync(new URL(`../apps/lucy-admin/web/src/${name}`, import.meta.url), 'utf8');

test('"(s || []).map is not a function": a list wrapped in an object is still a list', () => {
  const rows = [{id: 1}, {id: 2}];
  // The exact failure: a truthy object passes `s || []` and has no map.
  const wrapped = {items: rows, total: 2};
  assert.throws(() => (wrapped || []).map((x) => x), TypeError);
  assert.deepEqual(list(wrapped).map((x) => x.id), [1, 2]);
  assert.deepEqual(list({results: rows}), rows);
  assert.deepEqual(list({data: rows}), rows);
  assert.equal(list(rows), rows);
});

test('anything that is not a list becomes an empty list', () => {
  for (const v of [undefined, null, '', 'text', 0, 7, true, {}, {items: 'no'}, {detail: 'Forbidden'}, {items: null, results: {}}]) {
    assert.deepEqual(list(v), [], JSON.stringify(v));
    assert.doesNotThrow(() => list(v).map((x) => x));
  }
});

test('"reading \'trim\'": a label without a language is completed, not read as undefined', () => {
  const stored = {ru: 'Купить'};
  // The exact failure: the missing language is undefined.
  assert.throws(() => stored.en.trim(), TypeError);
  assert.deepEqual(label(stored), {ru: 'Купить', en: '', uk: ''});
  assert.equal(label(stored).en.trim(), '');
  for (const v of [undefined, null, {}, [], {ru: null, en: undefined}, {en: 5}, 'Просто строка', 12]) {
    const l = label(v);
    for (const k of ['ru', 'en', 'uk']) assert.equal(typeof l[k], 'string', `${JSON.stringify(v)} ${k}`);
  }
  assert.equal(label('Просто строка').ru, 'Просто строка');
  assert.equal(label({en: 5}).en, '5');
});

test('blank() never throws and tells an empty label from a filled one', () => {
  for (const v of [undefined, null, {}, {ru: '  ', en: '', uk: '\n'}, {ru: null}]) assert.equal(blank(v), true, JSON.stringify(v));
  for (const v of [{ru: 'а'}, {uk: 'б'}, {ru: '', en: ' x '}, 'в']) assert.equal(blank(v), false, JSON.stringify(v));
});

test('the panel uses these helpers where the crashes happened', () => {
  const main = src('main.tsx');
  assert.match(main, /import \{list\} from "\.\/safe";/);
  assert.doesNotMatch(main, /const list\s*=/);
  const layout = src('mobileLayout.tsx');
  // Every label that leaves LabelFields is complete, and the handlers no longer trim a language directly.
  assert.match(layout, /value = fullLabel\(value\);/);
  assert.equal((layout.match(/onChange\(fullLabel\(\{\.\.\.value, \[lang\]: e\.target\.value\}\)\)/g) || []).length, 2);
  assert.doesNotMatch(layout, /v\.(en|uk)\.trim\(\)/);
});

test('every cabinet file the panel imports is copied into the panel image', () => {
  const dir = new URL('../apps/lucy-admin/web/src/', import.meta.url);
  const files = [];
  const walk = (d) => { for (const e of fs.readdirSync(d, {withFileTypes: true})) {
    const p = new URL(e.name + (e.isDirectory() ? '/' : ''), d);
    if (e.isDirectory()) walk(p); else if (/\.(tsx?|css)$/.test(e.name)) files.push(p);
  } };
  walk(dir);
  const imported = new Set();
  for (const f of files) {
    for (const m of fs.readFileSync(f, 'utf8').matchAll(/from "(?:\.\.\/)+user-cabinet\/src\/([\w.-]+)"/g)) imported.add(m[1]);
  }
  assert.ok(imported.has('dates') && imported.has('http-json'));
  const docker = fs.readFileSync(new URL('../apps/lucy-admin/web/Dockerfile', import.meta.url), 'utf8');
  for (const name of imported) {
    const file = fs.existsSync(new URL(`../apps/user-cabinet/src/${name}.ts`, import.meta.url)) ? `${name}.ts` : `${name}.tsx`;
    assert.ok(docker.includes(`COPY apps/user-cabinet/src/${file} `), `${file} is imported by the panel but not copied into its image`);
  }
});

test('server times are read as UTC in the panel', async () => {
  const {serverTime} = await import('../apps/user-cabinet/src/dates.ts');
  assert.equal(serverTime('2026-11-15T10:00:00'), Date.UTC(2026, 10, 15, 10));
  assert.equal(serverTime('2026-11-15T13:00:00+03:00'), Date.UTC(2026, 10, 15, 10));
  const panel = fs.readdirSync(new URL('../apps/lucy-admin/web/src/', import.meta.url)).filter((f) => f.endsWith('.tsx') && !f.endsWith('.test.tsx'));
  const naive = [];
  for (const f of panel) {
    const text = fs.readFileSync(new URL(`../apps/lucy-admin/web/src/${f}`, import.meta.url), 'utf8');
    // A server value shown with toLocale…: it must go through serverDate (form inputs are local and are not shown this way).
    for (const m of text.matchAll(/new Date\(([^()]+)\)\.toLocale/g)) naive.push(`${f}: ${m[0]}`);
  }
  assert.deepEqual(naive, []);
});
