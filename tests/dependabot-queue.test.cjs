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
    head: {ref: `dependabot/${slug}/dir/${ecosystem}-${number}`, sha: `${number}`.padStart(40, 'a'), repo: {full_name: 'shop/queue'}},
  };
}

function ciFor(pull, runAttempt = 1, extra = {}) {
  return {
    id: 301, run_number: 19, run_attempt: runAttempt, path: '.github/workflows/ci.yml', event: 'pull_request',
    status: 'completed', conclusion: 'failure', head_sha: pull.head.sha, head_branch: pull.head.ref,
    head_repository: pull.head.repo, pull_requests: [{number: pull.number}], ...extra,
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
  ciRuns: [ciFor(batch[6], 3)],
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
const observe = (state, checks = [], openPulls = [candidate], ciRuns = []) => plan({
  state, openPulls, checksByNumber: {1: checks}, ciRuns, now: monday,
});
const badChecks = [{status: 'completed', conclusion: 'failure'}];
const pendingChecks = [{status: 'in_progress'}];
const retry1 = observe(null, badChecks, [candidate], [ciFor(candidate)]);
assert.equal(retry1.state.active.attempts, 0);
assert.equal(retry1.state.active.retry.phase, 'requested');
assert.deepEqual(observe(retry1.state, badChecks, [candidate], [ciFor(candidate)]).actions, []);
const pending = observe(retry1.state, pendingChecks, [candidate], [ciFor(candidate, 2, {status: 'in_progress', conclusion: null})]);
assert.equal(pending.state.active.attempts, 1);
const retry2 = observe(pending.state, badChecks, [candidate], [ciFor(candidate, 2)]);
assert.equal(retry2.state.active.attempts, 1);
const exhausted = observe(retry2.state, badChecks, [candidate], [ciFor(candidate, 3)]);
assert.equal(exhausted.state.deferred.find(item => item.number === 1).status, 'failed');
assert.equal(exhausted.state.deferred[0].attempts, 2);
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
const freshRetry = observe(retry2.state, badChecks, [changed], [ciFor(changed, 1, {id: 366, run_number: 58})]);
assert.equal(freshRetry.state.active.attempts, 0);
assert.equal(freshRetry.state.active.retry.runId, 366);
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

// Exercise the same github-script entry point as Actions, including the two
// durable ref updates surrounding the POST. Only GitHub and time are replaced.
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const lintScript = lint.split('      - name: At most one active pull request\n')[1]
  .split('          script: |\n')[1].split('\n      - ')[0];
const checkOpenPulls = new AsyncFunction('github', 'context', 'core', 'setTimeout', lintScript);

async function observeLint(...snapshots) {
  const errors = [];
  let reads = 0, waited = 0;
  const repo = {owner: 'owner', repo: 'shop'};
  const list = () => {};
  const github = {rest: {pulls: {list}}, async paginate(method, args) {
    assert.equal(method, list);
    assert.deepEqual(args, {...repo, state: 'open', per_page: 100});
    const current = snapshots[Math.min(reads++, snapshots.length - 1)];
    if (current instanceof Error) throw current;
    return current;
  }};
  await checkOpenPulls(github, {repo}, {info() {}, setFailed(message) { errors.push(message); }}, (resume, ms) => {
    assert.ok(ms > 0);
    waited += ms;
    resume();
  });
  return {reads, waited, errors};
}

test('the PR count is checked again after Dependabot serializes a batch', async () => {
  for (const winner of [human, batch[6]]) {
    const result = await observeLint([winner, ...batch.slice(0, 5)], [winner, batch[0]], [winner]);
    assert.deepEqual(result.errors, []);
    assert.equal(result.reads, 3);
    assert.ok(result.waited > 0);
  }
  assert.deepEqual(await observeLint([human]), {reads: 1, waited: 0, errors: []});
  assert.deepEqual(await observeLint([]), {reads: 1, waited: 0, errors: []});
});

test('the PR count includes drafts and rejects two non-queued PRs immediately', async () => {
  // Neither a bot-like branch nor a bot login alone qualifies for intake.
  for (const other of [
    {...batch[0], draft: true, user: human.user},
    {...batch[0], draft: true, head: {ref: 'feature/ordinary'}},
  ]) {
    const result = await observeLint([human, other, batch[1]]);
    assert.equal(result.reads, 1);
    assert.equal(result.waited, 0);
    assert.match(result.errors[0], /#50, #1, #2/);
  }
});

test('unresolved overlap, a newly opened ordinary PR and an unreadable list fail the gate', async () => {
  const stalled = await observeLint([human, batch[0]]);
  assert.equal(stalled.waited, 5 * 60 * 1000);
  assert.match(stalled.errors[0], /#50, #1/);
  const second = {...human, number: 51, draft: true};
  const changed = await observeLint([human, batch[0]], [human, second]);
  assert.equal(changed.reads, 2);
  assert.match(changed.errors[0], /#50, #51/);
  await assert.rejects(observeLint([human, batch[0]], new Error('unavailable')), /unavailable/);
});

const workflowScript = workflow.split('          script: |\n')[1];
assert.ok(workflowScript);
const intake = new AsyncFunction('github', 'context', 'core', 'require', 'process', 'Date', workflowScript);

function queueApi(initialState) {
  let state = initialState || {schema: 1, active: null, deferred: [], history: []};
  let blob;
  const writes = [];
  const posts = [];
  const mock = {runs: [ciFor(candidate)], detail: candidate, checks: badChecks, now: monday,
    open: [candidate], closed: new Map(), reopenNumbers: [], comments: [],
    heads: new Map(batch.map(pr => ['heads/' + pr.head.ref, pr.head.sha])), createdHeads: []};
  function commitState() {
    if (mock.failSavePhase && blob.active?.retry?.phase === mock.failSavePhase) throw new Error('ref update failed');
    state = structuredClone(blob);
    writes.push(state);
    return {data: {}};
  }
  const github = {rest: {
    git: {
      getRef: async ({ref}) => {
        if (ref === 'heads/automation/dependabot-queue') return {data: {object: {sha: 'parent'}}};
        if (!mock.heads.has(ref)) throw Object.assign(new Error('ref missing'), {status: 404});
        return {data: {object: {sha: mock.heads.get(ref)}}};
      },
      createRef: async ({ref, sha}) => {
        assert.ok(ref.startsWith('refs/heads/dependabot/'));
        mock.createdHeads.push({ref, sha});
        const branch = ref.slice('refs/'.length);
        mock.beforeCreateHead?.(branch);
        if (mock.heads.has(branch)) throw Object.assign(new Error('ref exists'), {status: 422});
        mock.heads.set(branch, sha);
        mock.afterCreateHead?.();
        return {data: {object: {sha}}};
      },
      getCommit: async () => ({data: {tree: {sha: 'tree'}}}),
      getTree: async () => ({data: {tree: [{path: 'docs/dependabot-queue.json', sha: 'blob'}]}}),
      getBlob: async () => ({data: {content: Buffer.from(JSON.stringify(state)).toString('base64')}}),
      createBlob: async args => { blob = JSON.parse(args.content); return {data: {sha: 'blob'}}; },
      createTree: async () => ({data: {sha: 'tree'}}),
      createCommit: async () => ({data: {sha: 'commit'}}),
      updateRef: async () => commitState(),
    },
    pulls: {
      list: async () => ({data: mock.freshOpen || mock.open}),
      get: async ({pull_number}) => {
        if (mock.readAfterPatchError && mock.reopenNumbers.includes(pull_number)) throw mock.readAfterPatchError;
        return {data: mock.closed.get(pull_number) || (state.active?.retry && mock.dispatchDetail) || mock.detail};
      },
      update: async ({pull_number, state: to}) => {
        assert.equal(to, 'open');
        assert.equal(state.active.number, pull_number, 'save the candidate before requesting reopen');
        mock.reopenNumbers.push(pull_number);
        const pr = mock.closed.get(pull_number);
        if (pr && !mock.heads.has('heads/' + pr.head.ref)) throw Object.assign(new Error('missing head'), {status: 422});
        if (mock.applyReopen !== false) {
          mock.closed.delete(pull_number);
          mock.open.push({...pr, state: 'open'});
          mock.detail = mock.open.at(-1);
        }
        if (mock.mergedDuringReopen) mock.closed.set(pull_number, {...pr, state: 'closed', merged: true});
        if (mock.reopenError) throw mock.reopenError;
        return {data: mock.detail};
      },
    },
    issues: {createComment: async ({issue_number, body}) => { mock.comments.push({issue_number, body}); }},
    checks: {listForRef: () => {}},
    actions: {listWorkflowRuns: () => {}, reRunWorkflowFailedJobs: async args => {
      assert.deepEqual(args, {...repo, run_id: state.active.retry.runId});
      assert.equal(state.active.retry.phase, 'requested');
      posts.push(args.run_id);
      if (mock.postError) throw mock.postError;
      return {status: 201};
    }},
  }, paginate: async (method, args) => {
    if (method === github.rest.pulls.list) return mock.open;
    if (method === github.rest.checks.listForRef) return mock.checks;
    assert.equal(method, github.rest.actions.listWorkflowRuns);
    assert.deepEqual(args, {...repo, workflow_id: 'ci.yml', event: 'pull_request', branch: candidate.head.ref, head_sha: candidate.head.sha, per_page: 100});
    if (mock.readError) throw mock.readError;
    return state.active?.retry && mock.dispatchRuns || mock.runs;
  }};
  const workspace = path.resolve(__dirname, '..');
  const clock = class extends Date { constructor(...args) { super(...(args.length ? args : [mock.now])); } };
  return {mock, writes, posts, state: () => state, run: () =>
    intake(github, {repo}, {info() {}, warning() {}}, require, {env: {GITHUB_WORKSPACE: workspace}}, clock)};
}

test('POST acceptance waits for a later run attempt and survives repeated observations', async () => {
  const api = queueApi();
  await api.run();
  assert.deepEqual(api.writes.map(s => s.active.retry.phase), ['requested', 'accepted']);
  assert.equal(api.state().active.attempts, 0);
  api.mock.now = '2026-11-23T13:00:00Z';
  await api.run();
  assert.deepEqual(api.posts, [301]);
  api.mock.runs = [ciFor(candidate, 2, {status: 'queued', conclusion: null})];
  api.mock.checks = pendingChecks;
  await api.run();
  await api.run();
  assert.equal(api.state().active.attempts, 1);
  assert.equal(api.state().history.filter(h => h.action === 'retry-confirmed').length, 1);
});

test('a missing run, an unrelated failure or a superseding success cannot spend the budget', async () => {
  const api = queueApi();
  for (const runs of [
    [], [ciFor(candidate, 1, {path: '.github/workflows/other.yml'})],
    [ciFor(candidate, 1, {head_sha: 'f'.repeat(40)})], [ciFor(candidate, 1, {event: 'push'})],
    [ciFor(candidate, 1, {head_branch: 'main'})], [ciFor(candidate, 1, {head_repository: {full_name: 'other/queue'}})],
    [ciFor(candidate, 1, {pull_requests: [{number: 89}]})],
    [ciFor(candidate), ciFor(candidate, 1, {id: 302, run_number: 20, conclusion: 'success'})],
  ]) {
    api.mock.runs = runs;
    await api.run();
    assert.deepEqual(api.posts, []);
    assert.equal(api.state().active.attempts, 0);
    assert.equal(api.state().active.retry, undefined);
  }
  api.mock.readError = new Error('Actions offline');
  const before = api.writes.length;
  await assert.rejects(api.run(), /Actions offline/);
  assert.equal(api.writes.length, before);
});

test('crashes before dispatch and after POST recover from durable state', async () => {
  const api = queueApi();
  api.mock.failSavePhase = 'requested';
  await assert.rejects(api.run(), /ref update failed/);
  assert.deepEqual(api.posts, []);
  api.mock.failSavePhase = 'accepted';
  await assert.rejects(api.run(), /ref update failed/);
  assert.equal(api.state().active.retry.phase, 'requested');
  assert.equal(api.state().active.attempts, 0);
  delete api.mock.failSavePhase;
  await api.run();
  assert.deepEqual(api.posts, [301]);
  api.mock.runs = [ciFor(candidate, 2, {conclusion: 'success'})];
  await api.run();
  assert.equal(api.state().active.attempts, 1);
  assert.deepEqual(api.posts, [301]);
});

test('a refused POST keeps the request and revalidates it before a delayed replay', async () => {
  const api = queueApi();
  api.mock.postError = new Error('Actions refused rerun');
  await assert.rejects(api.run(), /refused rerun/);
  await api.run();
  assert.equal(api.state().active.attempts, 0);
  assert.deepEqual(api.posts, [301]);
  delete api.mock.postError;
  api.mock.now = '2026-11-23T09:11:00Z';
  await api.run();
  assert.deepEqual(api.posts, [301, 301]);
  assert.equal(api.state().active.retry.phase, 'accepted');
  assert.equal(api.state().active.attempts, 0);
});

test('a changed PR or newer run between saving and dispatch receives no rerun', async () => {
  const api = queueApi();
  api.mock.dispatchDetail = changed;
  await assert.rejects(api.run(), /changed before CI retry/);
  assert.equal(api.state().active.attempts, 0);
  assert.deepEqual(api.posts, []);
  const newer = queueApi();
  newer.mock.dispatchRuns = [ciFor(candidate, 1, {id: 302, run_number: 20, conclusion: 'success'}), ciFor(candidate)];
  await newer.run();
  assert.deepEqual(newer.posts, []);
  assert.equal(newer.state().active.retry.phase, 'requested');
  await newer.run();
  assert.equal(newer.state().active.retry, undefined);
  assert.equal(newer.state().active.attempts, 0);
});

test('a new run can replace a missing run without inheriting undocumented attempts', () => {
  const replacement = ciFor(candidate, 1, {id: 377, run_number: 20});
  const result = observe(retry1.state, badChecks, [candidate], [replacement]);
  assert.equal(result.state.active.retry.runId, 377);
  assert.equal(result.state.active.attempts, 0);
  assert.equal(result.state.history.filter(h => h.action === 'retry-superseded').length, 1);
  assert.deepEqual(result.actions.map(a => a.type), ['rerun']);
});

test('old observation counts are archived once; conflicts and deferred requests survive serialization', () => {
  const previous = {...first.state, schema: 1, active: {...first.state.active, attempts: 3, conflicts: 1}};
  const upgraded = plan({state: previous, openPulls: [batch[6]], now: monday});
  assert.equal(upgraded.state.active.attempts, 0);
  assert.equal(upgraded.state.active.conflicts, 1);
  assert.deepEqual(upgraded.state.history.at(-1), {at: monday, action: 'legacy-retry-count', number: 7, sha: batch[6].head.sha, attempts: 3});
  assert.deepEqual(plan({state: upgraded.state, openPulls: [batch[6]], now: monday}).state, upgraded.state);
  const deferred = observe(retry1.state, [], [human, candidate]);
  const reopened = observe(deferred.state, [], []);
  assert.deepEqual(reopened.state.active.retry, retry1.state.active.retry);
});


function closedQueue() {
  const waiting = [batch[6], batch[1]];
  const items = waiting.map(pr => ({...plan({openPulls: [pr], now: monday}).state.active, status: 'waiting'}));
  const api = queueApi({schema: 2, active: null, deferred: items, history: []});
  api.mock.open = [];
  for (const pr of waiting) api.mock.closed.set(pr.number, {...pr, state: 'closed', merged: false});
  return api;
}

test('a refused security PR stays recorded while another update can reopen, then regains priority', async () => {
  const api = closedQueue();
  api.mock.applyReopen = false;
  api.mock.reopenError = Object.assign(new Error('validation failed'), {status: 422});
  await api.run();
  assert.deepEqual(api.mock.reopenNumbers, [7]);
  assert.deepEqual(api.mock.comments, []);
  assert.equal(api.state().active, null);
  const refused = api.state().deferred.find(row => row.number === 7);
  assert.equal(refused.security, true);
  assert.equal(refused.sha, batch[6].head.sha);
  assert.equal(refused.attempts, 0);
  assert.ok(Date.parse(refused.reopenAfter) > Date.parse(monday));

  api.mock.now = '2026-11-23T15:00:00Z';
  delete api.mock.reopenError;
  delete api.mock.applyReopen;
  await api.run();
  assert.deepEqual(api.mock.reopenNumbers, [7, 2]);
  assert.deepEqual(api.mock.comments.map(c => c.issue_number), [2]);
  api.mock.closed.set(2, {...api.mock.open.pop(), state: 'closed', merged: true});
  await api.run();
  assert.equal(api.state().active, null);
  api.mock.now = refused.reopenAfter;
  await api.run();
  assert.deepEqual(api.mock.reopenNumbers, [7, 2, 7]);
  assert.deepEqual(api.mock.comments.map(c => c.issue_number), [2, 7]);
  assert.equal(api.state().deferred.length, 0);
});

test('a deleted Dependabot branch is recreated at its recorded head before reopening', async () => {
  const api = closedQueue();
  const {ref, sha} = batch[6].head;
  api.mock.heads.delete('heads/' + ref);
  await api.run();
  assert.deepEqual(api.mock.createdHeads, [{ref: 'refs/heads/' + ref, sha}]);
  assert.deepEqual(api.mock.reopenNumbers, [7, 7]);
  assert.deepEqual(api.mock.open.map(pr => pr.number), [7]);
  assert.equal(api.state().active.sha, sha);
  assert.equal(api.mock.comments.length, 1);
});

test('recovery does not recreate a fork or a head which differs from the recorded commit', async () => {
  for (const difference of [{repo: {full_name: 'fork/queue'}}, {sha: 'f'.repeat(40)}]) {
    const api = closedQueue();
    const pr = api.mock.closed.get(7);
    api.mock.closed.set(7, {...pr, head: {...pr.head, ...difference}});
    api.mock.heads.delete('heads/' + pr.head.ref);
    await api.run();
    assert.deepEqual(api.mock.createdHeads, []);
    assert.deepEqual(api.mock.open, []);
    assert.ok(api.state().deferred.some(row => row.number === 7 && row.sha === batch[6].head.sha));
  }
});

test('restoring a branch checks the current open PR and reconciles a lost create response', async () => {
  const {ref, sha} = batch[6].head;
  const busy = closedQueue();
  busy.mock.heads.delete('heads/' + ref);
  busy.mock.afterCreateHead = () => { busy.mock.freshOpen = [human]; };
  await busy.run();
  assert.deepEqual(busy.mock.reopenNumbers, [7]);
  assert.deepEqual(busy.mock.open, []);
  assert.equal(busy.mock.heads.get('heads/' + ref), sha);
  const lost = closedQueue();
  lost.mock.heads.delete('heads/' + ref);
  lost.mock.afterCreateHead = () => { throw new Error('lost ref create response'); };
  await lost.run();
  assert.deepEqual(lost.mock.open.map(pr => pr.number), [7]);
});

test('a concurrent ref creation is used only when it matches the saved SHA', async () => {
  const {ref, sha} = batch[6].head;
  for (const concurrent of [sha, 'f'.repeat(40)]) {
    const api = closedQueue();
    api.mock.heads.delete('heads/' + ref);
    api.mock.beforeCreateHead = branch => api.mock.heads.set(branch, concurrent);
    await api.run();
    assert.equal(api.mock.heads.get('heads/' + ref), concurrent);
    assert.deepEqual(api.mock.open.map(pr => pr.number), concurrent === sha ? [7] : []);
  }
});

test('an unconfirmed ref creation preserves intent and a second refusal keeps the cooldown', async () => {
  const {ref} = batch[6].head;
  const unknown = closedQueue();
  unknown.mock.heads.delete('heads/' + ref);
  unknown.mock.beforeCreateHead = () => { throw Object.assign(new Error('create unavailable'), {status: 503}); };
  await assert.rejects(unknown.run(), /create unavailable/);
  assert.equal(unknown.state().active.number, 7);
  assert.deepEqual(unknown.mock.reopenNumbers, [7]);

  const refused = closedQueue();
  refused.mock.heads.delete('heads/' + ref);
  refused.mock.applyReopen = false;
  refused.mock.reopenError = Object.assign(new Error('another validation failed'), {status: 422});
  await refused.run();
  assert.equal(refused.mock.createdHeads.length, 1);
  assert.deepEqual(refused.mock.reopenNumbers, [7, 7]);
  assert.ok(refused.state().deferred.find(row => row.number === 7).reopenAfter);
});

test('reopen reconciles a lost HTTP response and stops when the result is unknown', async () => {
  const accepted = closedQueue();
  accepted.mock.reopenError = new Error('lost response');
  await accepted.run();
  assert.deepEqual(accepted.mock.reopenNumbers, [7]);
  assert.deepEqual(accepted.mock.comments.map(c => c.issue_number), [7]);
  assert.equal(accepted.state().active.number, 7);

  const uncertain = closedQueue();
  uncertain.mock.applyReopen = false;
  uncertain.mock.reopenError = Object.assign(new Error('service unavailable'), {status: 503});
  await assert.rejects(uncertain.run(), /service unavailable/);
  assert.deepEqual(uncertain.mock.comments, []);
  assert.equal(uncertain.state().active.number, 7);
  assert.equal(uncertain.state().deferred.length, 1);
  delete uncertain.mock.applyReopen;
  delete uncertain.mock.reopenError;
  await uncertain.run();
  assert.deepEqual(uncertain.mock.reopenNumbers, [7, 7]);
  assert.equal(uncertain.mock.open.length, 1);
});

test('a newly opened human PR prevents the queued reopen after the queue state was saved', async () => {
  const api = closedQueue();
  api.mock.freshOpen = [human];
  await api.run();
  assert.deepEqual(api.mock.reopenNumbers, []);
  assert.deepEqual(api.mock.comments, []);
  api.mock.open = [human];
  await api.run();
  assert.deepEqual(api.state().deferred.map(row => row.number).sort(), [2, 7]);
});

test('a merged candidate is retired and an unreadable outcome keeps the saved intent', async () => {
  const merged = closedQueue();
  merged.mock.applyReopen = false;
  merged.mock.mergedDuringReopen = true;
  merged.mock.reopenError = Object.assign(new Error('already merged'), {status: 422});
  await merged.run();
  assert.deepEqual(merged.mock.comments, []);
  delete merged.mock.mergedDuringReopen;
  delete merged.mock.reopenError;
  delete merged.mock.applyReopen;
  await merged.run();
  assert.equal(merged.state().active.number, 2);
  assert.deepEqual(merged.state().deferred, []);

  const unreadable = closedQueue();
  unreadable.mock.applyReopen = false;
  unreadable.mock.reopenError = Object.assign(new Error('validation failed'), {status: 422});
  unreadable.mock.readAfterPatchError = new Error('cannot read disposition');
  await assert.rejects(unreadable.run(), /cannot read disposition/);
  assert.equal(unreadable.state().active.number, 7);
  assert.deepEqual(unreadable.mock.comments, []);
  assert.equal(unreadable.state().deferred[0].number, 2);
});
