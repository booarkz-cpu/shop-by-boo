import {expect,it} from 'vitest';
import {serverDate,serverTime} from './dates';
import {daysLeft} from './ui';

it('reads a server time without a zone as UTC, whatever the browser zone is', () => {
  const utc = Date.UTC(2026, 10, 15, 10, 0, 0);
  expect(serverTime('2026-11-15T10:00:00')).toBe(utc);
  expect(serverTime('2026-11-15T10:00:00.250000')).toBe(utc + 250);
  expect(serverTime('2026-11-15 10:00:00')).toBe(utc);
  // Times that carry their zone are taken as they are.
  expect(serverTime('2026-11-15T10:00:00Z')).toBe(utc);
  expect(serverTime('2026-11-15T13:00:00+03:00')).toBe(utc);
  expect(serverTime('2026-11-15T13:00:00+0300')).toBe(utc);
  expect(serverTime('2026-11-15')).toBe(Date.UTC(2026, 10, 15));
  expect(serverDate('2026-11-15T10:00:00').toISOString()).toBe('2026-11-15T10:00:00.000Z');
});

it('empty and broken values stay empty', () => {
  for (const v of [null, undefined, '', 'not a date']) expect(Number.isNaN(serverTime(v as any))).toBe(true);
  expect(serverTime(new Date(5))).toBe(5);
  expect(serverTime(7)).toBe(7);
});

it('days left counts to the UTC end, not to the same clock time in the local zone', () => {
  const end = new Date(Date.now() + 36 * 3_600_000).toISOString().replace('Z', '');  // naive UTC, like the API
  expect(daysLeft(end)).toBe(2);
  expect(Math.abs(daysLeft(new Date(Date.now() - 3_600_000).toISOString().replace('Z', ''))!)).toBe(0);  // ended an hour ago
});
