'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {plan, ecosystemOf, isSecurity} = require('../scripts/dependabot-queue.cjs');

const monday = '2026-11-23T09:00:00Z';
function pull(number, ecosystem, createdAt, extra = {}) {
  const slug = ecosystem === 'github-actions' ? 'github_actions' : ecosystem;
  return {
    number,
    title: extra.title || `bump ${ecosystem}`,
    body: extra.body || '',
    created_at: createdAt,
    user: {login: 'dependabot[bot]'},
    labels: extra.labels || [{name: 'dependencies'}],
    mergeable_state: extra.mergeable_state || 'clean',
    head: {ref: `dependabot/${slug}/dir/${ecosystem}-${number}`, sha: `${number}`.padStart(40, 'a')},
  };
}

const batch = [
  pull(1, 'pip', '2026-11-23T08:01:00Z'),
  pull(2, 'npm', '2026-11-23T08:02:00Z'),
  pull(3, 'gradle', '2026-11-23T08:03:00Z'),
  pull(4, 'docker', '2026-11-23T08:04:00Z'),
  pull(5, 'docker-compose', '2026-11-23T08:05:00Z'),
  pull(6, 'github-actions', '2026-11-23T08:06:00Z'),
  pull(7, 'pip', '2026-11-23T08:00:00Z', {title: 'Security update', labels: [{name: 'security'}], body: 'GHSA-abcd-1234-efgh'}),
];

const first = plan({openPulls: batch, state: {schema: 1, active: null, deferred: [], history: []}, checksByNumber: {}, now: monday});
assert.equal(first.state.active.number, 7);
assert.equal(first.state.active.security, true);
assert.deepEqual(first.actions.filter((action) => action.type === 'close').map((action) => action.number).sort((a, b) => a - b), [1, 2, 3, 4, 5, 6]);
assert.equal(first.state.deferred.length, 6);
for (const ecosystem of ['pip', 'npm', 'gradle', 'docker', 'docker-compose', 'github_actions']) {
  assert.ok(first.state.deferred.some((item) => item.ecosystem === ecosystem), ecosystem);
}
assert.equal(new Set([...first.state.deferred.map((item) => item.number), first.state.active.number]).size, 7);

const promoted = plan({
  openPulls: [],
  state: first.state,
  checksByNumber: {},
  now: '2026-11-23T12:00:00Z',
});
assert.equal(promoted.actions.find((action) => action.type === 'reopen').number, 1);
assert.equal(promoted.state.deferred.length, 5);

const failed = plan({
  openPulls: [batch[6]],
  state: {...first.state, active: {...first.state.active, attempts: 2}},
  checksByNumber: {7: [{name: 'CI', status: 'completed', conclusion: 'failure'}]},
  now: '2026-11-23T13:00:00Z',
});
assert.ok(failed.actions.some((action) => action.type === 'close' && action.number === 7));
assert.equal(failed.actions.find((action) => action.type === 'reopen').number, 1);
assert.ok(failed.state.deferred.some((item) => item.number === 7 && item.status === 'failed'));

const conflict = plan({
  openPulls: [{...batch[6], mergeable_state: 'dirty'}],
  state: {...first.state, active: {...first.state.active, conflicts: 1}},
  checksByNumber: {},
  now: '2026-11-23T14:00:00Z',
});
assert.ok(conflict.actions.some((action) => action.type === 'close' && action.number === 7));
assert.equal(conflict.state.deferred.find((item) => item.number === 7).status, 'conflict');

const human = pull(50, 'pip', monday);
human.user = {login: 'booarkz-cpu'};
human.head.ref = 'cursor/feature';
const held = plan({openPulls: [human, batch[0], batch[1]], state: {schema: 1, active: null, deferred: [], history: []}, checksByNumber: {}, now: monday});
assert.equal(held.state.active, null);
assert.deepEqual(held.actions.filter((action) => action.type === 'close').map((action) => action.number).sort(), [1, 2]);
assert.equal(held.actions.some((action) => action.type === 'close' && action.number === 50), false);

assert.equal(ecosystemOf('dependabot/github_actions/actions/checkout-1'), 'github_actions');
assert.equal(isSecurity({title: 'x', body: 'CVE-2026-1', labels: []}), true);

const lint = fs.readFileSync(path.join(__dirname, '../.github/workflows/ci.yml'), 'utf8');
assert.match(lint, /At most one active pull request/);
assert.match(lint, /open\.length > 1/);
const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/dependabot-queue.yml'), 'utf8');
assert.match(workflow, /group: dependabot-queue/);
assert.match(workflow, /cancel-in-progress: false/);
assert.doesNotMatch(workflow, /--admin/);

console.log('dependabot queue: ok');
