'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const {plan, ecosystemOf, isSecurity, inspectOpenPulls} = require('../scripts/dependabot-queue.cjs');

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
    state: 'open',
    base: {ref: 'main', sha: 'b'.repeat(40)},
    mergeable: true,
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
  mergedNumbers: [7],
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
  openPulls: [{...batch[6], mergeable: false}],
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

const recovered = plan({
  openPulls: [],
  state: {schema: 1, active: {number: 445, security: false, createdAt: '2026-11-23T18:33:29Z', ecosystem: 'gradle', ref: 'dependabot/gradle/x', sha: 'b'.repeat(40), title: 'agp', status: 'active', attempts: 0, conflicts: 0}, deferred: [], history: []},
  checksByNumber: {},
  now: '2026-11-23T21:14:32Z',
});
assert.equal(recovered.actions.find((action) => action.type === 'reopen').number, 445);

const afterMerge = plan({
  openPulls: [],
  state: {schema: 1, active: {number: 444, security: false, createdAt: '2026-11-23T18:31:52Z', ecosystem: 'gradle', status: 'active', attempts: 0, conflicts: 0, ref: 'dependabot/gradle/y', sha: 'c'.repeat(40), title: 'agp'}, deferred: [{number: 445, security: false, createdAt: '2026-11-23T18:33:29Z', ecosystem: 'gradle', status: 'waiting', attempts: 0, conflicts: 0, ref: 'dependabot/gradle/x', sha: 'b'.repeat(40), title: 'agp'}], history: []},
  checksByNumber: {},
  mergedNumbers: [444],
  now: '2026-11-23T21:14:00Z',
});
assert.equal(afterMerge.actions.find((action) => action.type === 'reopen').number, 445);
assert.equal(afterMerge.state.deferred.some((item) => item.number === 444), false);

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

const reconciled = plan({
  openPulls: [human],
  state: first.state,
  mergedNumbers: [1, 2],
  now: monday,
});
assert.equal(reconciled.state.active, null);
assert.deepEqual(reconciled.state.deferred.map(item => item.number).sort((a,b) => a-b), [3,4,5,6,7]);
assert.equal(reconciled.state.deferred.find(item => item.number === 7).status, 'waiting');
assert.ok(reconciled.state.history.some(item => item.action === 'keep' && item.number === 7));
assert.deepEqual(reconciled.actions, []);
const repeated = plan({openPulls: [human], state: reconciled.state, mergedNumbers: [1,2], now: monday});
assert.deepEqual(repeated.state, reconciled.state);
assert.deepEqual(repeated.actions, []);

 // Retry history survives pending observations and deferral, but not a new SHA.
const candidate = batch[0];
const observe = (state, checks = [], openPulls = [candidate]) => plan({
  state, openPulls, checksByNumber: {1: checks}, now: monday,
});
const badChecks = [{status: 'completed', conclusion: 'failure'}];
const pendingChecks = [{status: 'in_progress'}];
const retry1 = observe(null, badChecks);
assert.equal(retry1.state.active.attempts, 1);
const pending = observe(retry1.state, pendingChecks);
assert.equal(pending.state.active.attempts, 1);
const retry2 = observe(pending.state, badChecks);
assert.equal(retry2.state.active.attempts, 2);
const exhausted = observe(observe(retry2.state, pendingChecks).state, badChecks);
assert.equal(exhausted.state.deferred.find(item => item.number === 1).status, 'failed');
const dirtyCandidate = {...candidate, mergeable: false};
const rebased = observe(null, [], [dirtyCandidate]);
assert.equal(rebased.state.active.conflicts, 1);
const deferredConflict = observe(rebased.state, [], [human, dirtyCandidate]);
assert.equal(deferredConflict.state.deferred[0].conflicts, 1);
const reopenedConflict = observe(deferredConflict.state, [], []);
assert.equal(reopenedConflict.state.active.conflicts, 1);
const exhaustedConflict = observe(reopenedConflict.state, [], [dirtyCandidate]);
assert.equal(exhaustedConflict.state.deferred[0].status, 'conflict');
const changed = {...candidate, head: {...candidate.head, sha: 'f'.repeat(40)}};
const freshRetry = observe(retry2.state, badChecks, [changed]);
assert.equal(freshRetry.state.active.attempts, 1);
assert.equal(freshRetry.state.active.sha, changed.head.sha);
const freshConflict = observe(rebased.state, [], [{...changed, mergeable: false}]);
assert.equal(freshConflict.state.active.conflicts, 1);

 // Deferral actions must use normalized security and creation-time priority.
const priorityBatch = [
  pull(10, 'npm', '2026-11-23T08:04:00Z'),
  pull(20, 'pip', '2026-11-23T08:01:00Z'),
  pull(30, 'gradle', '2026-11-23T08:05:00Z', {body: 'GHSA-test-1234-5678'}),
  pull(40, 'docker', '2026-11-23T08:02:00Z', {labels: [{name: 'security'}]}),
  pull(21, 'npm', '2026-11-23T08:01:00Z'),
];
for (const order of [priorityBatch, [...priorityBatch].reverse()]) {
  const result = plan({openPulls: [human, ...order], state: null, now: monday});
  assert.equal(result.state.active, null);
  assert.deepEqual(result.actions.map(action => [action.type, action.number]),
    [40, 30, 20, 21, 10].map(number => ['close', number]));
  assert.deepEqual(result.state.deferred.map(item => item.number), [40, 30, 20, 21, 10]);
}

const repo = {owner: 'shop', repo: 'queue'};
function pullApi(listed, responses) {
  const delays = [];
  const list = () => {};
  let reads = 0;
  const github = {
    paginate: async (method, args) => {
      assert.equal(method, list);
      assert.deepEqual(args, {...repo, state: 'open', per_page: 100});
      return listed;
    },
    rest: {pulls: {list, get: async args => {
      assert.deepEqual(args, {...repo, pull_number: listed[0].number});
      const value = responses[reads++];
      if (value instanceof Error) throw value;
      assert.ok(value, 'unexpected additional PR read');
      return {data: value};
    }}},
  };
  return {github, inspect: () => inspectOpenPulls(github, repo, async ms => delays.push(ms)), delays, reads: () => reads};
}

test('a conflict from the PR detail triggers a rebase after GitHub finishes computing it', async () => {
  const listed = {...candidate, mergeable: undefined, mergeable_state: 'clean'};
  const api = pullApi([listed], [{...candidate, mergeable: null}, {...candidate, mergeable: false, mergeable_state: 'dirty'}]);
  const openPulls = await api.inspect();
  const result = plan({openPulls, now: monday});
  assert.deepEqual(result.actions.map(action => action.comment), ['@dependabot rebase']);
  assert.equal(result.state.active.conflicts, 1);
  assert.deepEqual(api.delays, [1000]);
});

test('unknown mergeability has a bounded read budget and a later intake can recover', async () => {
  const unknown = {...candidate, mergeable: null, mergeable_state: 'unknown'};
  const api = pullApi([candidate], [unknown, unknown, unknown, candidate]);
  await assert.rejects(api.inspect(), /after 3 reads/);
  assert.deepEqual(api.delays, [1000, 2000]);
  const result = plan({openPulls: await api.inspect(), now: monday});
  assert.deepEqual(result.actions, []);
  assert.equal(result.state.active.conflicts, 0);
  assert.equal(api.reads(), 4);
});

test('changed head, base, PR state or an API error aborts before planning', async () => {
  for (const detail of [
    {...candidate, head: {...candidate.head, sha: 'f'.repeat(40)}},
    {...candidate, base: {...candidate.base, sha: 'c'.repeat(40)}},
    {...candidate, base: {...candidate.base, ref: 'another-branch'}},
    {...candidate, state: 'closed'},
    new Error('unavailable'),
  ]) {
    const api = pullApi([candidate], [detail]);
    await assert.rejects(api.inspect(), /changed during|unavailable/);
    assert.equal(api.reads(), 1);
  }
});

test('an uncomputed PR cannot stall independent intake or spend a retry on a list snapshot', async () => {
  for (const listed of [[human, candidate], [candidate, batch[1]]]) {
    const api = pullApi(listed.map(p => ({...p, mergeable: null})), []);
    const result = plan({openPulls: await api.inspect(), checksByNumber: {1: badChecks}, now: monday});
    assert.equal(api.reads(), 0);
    assert.deepEqual(result.actions.map(a => a.type), ['close']);
    assert.equal(result.state.deferred.length, 1);
  }
});
