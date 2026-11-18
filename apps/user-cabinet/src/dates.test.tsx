import {it} from "node:test";
import {expect} from "chai";
import {serverDate,serverTime} from './dates';
import {daysLeft} from './ui';

it('reads a server time without a zone as UTC, whatever the browser zone is', () => {
  const utc = Date.UTC(2026, 10, 15, 10, 0, 0);
  expect(serverTime('2026-11-15T10:00:00')).to.equal(utc);
  expect(serverTime('2026-11-15T10:00:00.250000')).to.equal(utc + 250);
  expect(serverTime('2026-11-15 10:00:00')).to.equal(utc);
  // Times that carry their zone are taken as they are.
  expect(serverTime('2026-11-15T10:00:00Z')).to.equal(utc);
  expect(serverTime('2026-11-15T13:00:00+03:00')).to.equal(utc);
  expect(serverTime('2026-11-15T13:00:00+0300')).to.equal(utc);
  expect(serverTime('2026-11-15')).to.equal(Date.UTC(2026, 10, 15));
  expect(serverDate('2026-11-15T10:00:00').toISOString()).to.equal('2026-11-15T10:00:00.000Z');
});

it('empty and broken values stay empty', () => {
  for (const v of [null, undefined, '', 'not a date']) expect(Number.isNaN(serverTime(v as any))).to.equal(true);
  expect(serverTime(new Date(5))).to.equal(5);
  expect(serverTime(7)).to.equal(7);
});

it('days left counts to the UTC end, not to the same clock time in the local zone', () => {
  const end = new Date(Date.now() + 36 * 3_600_000).toISOString().replace('Z', '');  // naive UTC, like the API
  expect(daysLeft(end)).to.equal(2);
  expect(Math.abs(daysLeft(new Date(Date.now() - 3_600_000).toISOString().replace('Z', ''))!)).to.equal(0);  // ended an hour ago
});
