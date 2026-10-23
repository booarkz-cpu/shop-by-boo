// Node terminal screen model: run with `node --experimental-strip-types --test tests/terminal-screen.test.mjs`.
import test from 'node:test';
import assert from 'node:assert/strict';
import {Screen, keyToInput, color256} from '../admin/src/terminal-screen.ts';

test('text, wrap, carriage return and scrolling into scrollback', () => {
  const s = new Screen(10, 3);
  s.write('hello\r\nworld');
  assert.equal(s.text(0), 'hello');
  assert.equal(s.text(1), 'world');
  s.write('\r\n0123456789AB');
  assert.equal(s.text(1), '0123456789');
  assert.equal(s.text(2), 'AB', 'autowrap scrolls and continues on the next line');
  assert.equal(s.scrollback.map((l) => l.map((c) => c.ch).join('').trim()).join('|'), 'hello');
});

test('cursor movement, erase in line and display', () => {
  const s = new Screen(20, 4);
  s.write('abcdef\x1b[3D\x1b[K');
  assert.equal(s.text(0), 'abc');
  s.write('\x1b[3;5Hxy');
  assert.equal(s.text(2), '    xy');
  assert.deepEqual([s.x, s.y], [6, 2]);
  s.write('\x1b[2J');
  assert.equal([0, 1, 2, 3].map((y) => s.text(y)).join(''), '');
  s.write('\x1b[H1\x1b[2;1H2\x1b[1;1H\x1b[J');
  assert.equal(s.text(1), '', 'ED 0 clears from the cursor down');
});

test('colors and attributes: 16, 256 and truecolor', () => {
  const s = new Screen(20, 2);
  s.write('\x1b[1;31mR\x1b[0m \x1b[38;5;196mX\x1b[48;2;1;2;3mY\x1b[7mZ\x1b[m.');
  const [r, , x, y, z, dot] = s.lines[0];
  assert.equal(r.bold, true);
  assert.equal(r.fg, '#f38ba8');
  assert.equal(x.fg, color256(196));
  assert.equal(y.bg, 'rgb(1,2,3)');
  assert.equal(z.inverse, true);
  assert.deepEqual([dot.fg, dot.bg, dot.bold, dot.inverse], [null, null, false, false]);
});

test('alternate screen restores the shell screen (vim, top, less)', () => {
  const s = new Screen(20, 3);
  s.write('$ top');
  s.write('\x1b[?1049h\x1b[Hfull screen app');
  assert.equal(s.altScreen, true);
  assert.equal(s.text(0), 'full screen app');
  s.write('\x1b[?1049l');
  assert.equal(s.altScreen, false);
  assert.equal(s.text(0), '$ top');
});

test('scroll region, insert and delete lines, reverse index', () => {
  const s = new Screen(10, 4);
  s.write('a\r\nb\r\nc\r\nd');
  s.write('\x1b[2;3r\x1b[3;1H\n');
  assert.deepEqual([0, 1, 2, 3].map((y) => s.text(y)), ['a', 'c', '', 'd'], 'only the region scrolls');
  s.write('\x1b[r\x1b[1;1H\x1bM');
  assert.equal(s.text(0), '', 'reverse index at the top inserts a line');
  s.write('\x1b[2;1H\x1b[M');
  assert.equal(s.text(1), 'c');
});

test('OSC title, charset designators and DSR reply', () => {
  const s = new Screen(20, 3);
  let reply = '';
  s.onReply = (d) => { reply += d; };
  s.write('\x1b]0;root@nl-1: ~\x07\x1b(Bok\x1b[6n');
  assert.equal(s.title, 'root@nl-1: ~');
  assert.equal(s.text(0), 'ok');
  assert.equal(reply, '\x1b[1;3R');
});

test('modes: cursor keys, bracketed paste, hidden cursor', () => {
  const s = new Screen(10, 2);
  s.write('\x1b[?1h\x1b[?2004h\x1b[?25l');
  assert.equal(s.appCursor, true);
  assert.equal(s.bracketedPaste, true);
  assert.equal(s.cursorVisible, false);
});

test('resize keeps content and clamps the cursor', () => {
  const s = new Screen(10, 4);
  s.write('a\r\nb\r\nc\r\nd');
  s.resize(5, 2);
  assert.deepEqual([s.text(0), s.text(1)], ['c', 'd']);
  assert.ok(s.y <= 1);
  s.resize(12, 5);
  assert.equal(s.lines.length, 5);
  assert.equal(s.lines[0].length, 12);
});

test('keys: control letters on any layout, arrows, function keys', () => {
  assert.equal(keyToInput({key: 'c', ctrlKey: true, code: 'KeyC'}), '\x03');
  assert.equal(keyToInput({key: 'с', ctrlKey: true, code: 'KeyC'}), '\x03', 'Russian layout');
  assert.equal(keyToInput({key: 'ArrowUp'}), '\x1b[A');
  assert.equal(keyToInput({key: 'ArrowUp'}, true), '\x1bOA');
  assert.equal(keyToInput({key: 'Enter'}), '\r');
  assert.equal(keyToInput({key: 'Backspace'}), '\x7f');
  assert.equal(keyToInput({key: 'F5'}), '\x1b[15~');
  assert.equal(keyToInput({key: 'ж'}), 'ж');
  assert.equal(keyToInput({key: 'x', altKey: true}), '\x1bx');
  assert.equal(keyToInput({key: 'Shift'}), null);
  assert.equal(keyToInput({key: 'v', metaKey: true}), null, 'browser shortcuts stay with the browser');
});
