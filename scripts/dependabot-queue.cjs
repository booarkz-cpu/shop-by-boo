'use strict';
/**
 * One open pull request at a time. Dependabot may open many updates on a Monday;
 * this keeps a single merge candidate and records every other update so none is dropped.
 * Security updates go first. A candidate that keeps failing or conflicting is deferred
 * and the next recorded update is reopened. Branch protection is not bypassed.
 */

const MAX_ATTEMPTS = 2;
const RETRY_RECHECK_MS = 10 * 60 * 1000;
const REOPEN_COOLDOWN_MS = 24 * 60 * 60 * 1000;
const ECOSYSTEMS = new Set([
  'pip', 'npm', 'gradle', 'docker', 'docker-compose', 'docker_compose',
  'github-actions', 'github_actions', 'gomod', 'cargo', 'maven', 'nuget',
  'bundler', 'composer', 'pub', 'swift', 'terraform',
]);

function emptyState(now) {
  return {schema: 2, updatedAt: now || null, active: null, deferred: [], history: []};
}

function ecosystemOf(headRef) {
  const part = String(headRef || '').split('/')[1] || 'unknown';
  return ECOSYSTEMS.has(part) ? part : part || 'unknown';
}

function isDependabot(pull) {
  const login = pull.user && pull.user.login;
  return login === 'dependabot[bot]' && String(pull.head && pull.head.ref || '').startsWith('dependabot/');
}

// pulls.list describes queue membership. Only pulls.get computes mergeability.
// With multiple open PRs, serialize intake first using the list alone.
async function inspectOpenPulls(github, repo, delay = ms => new Promise(resolve => setTimeout(resolve, ms))) {
  const pulls = await github.paginate(github.rest.pulls.list, {...repo, state: 'open', per_page: 100});
  if (pulls.length !== 1 || !isDependabot(pulls[0])) return pulls;
  const [listed] = pulls;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt) await delay(1000 * attempt);
    const {data} = await github.rest.pulls.get({...repo, pull_number: listed.number});
    if (data.state !== 'open' || data.number !== listed.number || !isDependabot(data) ||
        data.head.sha !== listed.head.sha || data.base.sha !== listed.base.sha || data.base.ref !== listed.base.ref) {
      throw new Error(`PR #${listed.number} changed during queue inspection`);
    }
    if (typeof data.mergeable === 'boolean') return [data];
  }
  throw new Error(`GitHub has not computed mergeability for #${listed.number} after 3 reads. Queue unchanged; the next intake will retry.`);
}

function isSecurity(pull) {
  const labels = (pull.labels || []).map((label) => String(label.name || label).toLowerCase());
  const text = `${pull.title || ''}\n${pull.body || ''}`;
  return labels.includes('security') || /CVE-\d|GHSA-|security update/i.test(text);
}

function recordOf(pull) {
  return {
    number: pull.number,
    ref: pull.head.ref,
    sha: pull.head.sha,
    title: pull.title,
    ecosystem: ecosystemOf(pull.head.ref),
    security: isSecurity(pull),
    createdAt: pull.created_at,
    status: 'waiting',
    attempts: 0,
    conflicts: 0,
    note: '',
  };
}

function byPriority(a, b) {
  if (a.security !== b.security) return a.security ? -1 : 1;
  if (a.createdAt !== b.createdAt) return a.createdAt < b.createdAt ? -1 : 1;
  return a.number - b.number;
}

function checksFailed(checks) {
  const runs = checks || [];
  if (!runs.length) return false;
  if (runs.some((run) => run.status !== 'completed')) return false;
  return runs.some((run) => !['success', 'skipped', 'neutral'].includes(run.conclusion));
}

function matchesCiRun(run, pull) {
  return run.path === '.github/workflows/ci.yml' && run.event === 'pull_request' &&
    run.head_sha === pull.head.sha && run.head_branch === pull.head.ref &&
    Boolean(pull.head.repo?.full_name) && run.head_repository?.full_name === pull.head.repo.full_name &&
    (!run.pull_requests?.length || run.pull_requests.some(pr => pr.number === pull.number));
}

async function inspectCiRuns(github, repo, pull) {
  const runs = await github.paginate(github.rest.actions.listWorkflowRuns, {
    ...repo, workflow_id: 'ci.yml', event: 'pull_request', branch: pull.head.ref, head_sha: pull.head.sha, per_page: 100,
  });
  const matching = runs.filter(run => matchesCiRun(run, pull));
  for (const run of matching) {
    if (![run.id, run.run_attempt, run.run_number].every(n => Number.isSafeInteger(n) && n > 0)) {
      throw new Error(`Missing CI run identity for #${pull.number}`);
    }
  }
  return matching.sort((a, b) => b.run_number - a.run_number);
}

function failedRun(run) {
  return run && run.status === 'completed' && run.conclusion === 'failure';
}

// The ref contains the request before the POST. Only a later GitHub run_attempt
// confirms execution. A lost POST response can thus be reconciled after restart.
function planRetry(item, runs, checks, now, note) {
  const latest = runs[0];
  const previous = item.retry;
  if (previous) {
    const observed = runs.find(run => run.id === previous.runId);
    if (!latest || (!observed && latest.run_number <= previous.runNumber)) return;
    if (observed && observed.run_attempt < previous.runAttempt) return;
    if (previous.phase !== 'confirmed' && observed && observed.run_attempt > previous.runAttempt) {
      item.attempts++;
      previous.phase = 'confirmed';
      note({action: 'retry-confirmed', number: item.number, runId: observed.id, runAttempt: observed.run_attempt});
    }
    if (previous.runId === latest.id && latest.run_attempt === previous.runAttempt) {
      // An accepted POST can precede Actions exposing the next attempt. An
      // unacknowledged intent is eligible for a guarded replay after a grace period.
      if (previous.phase !== 'requested' || Date.parse(now) - Date.parse(previous.requestedAt) < RETRY_RECHECK_MS) return;
    } else if (latest.run_number > previous.runNumber && previous.phase !== 'confirmed') {
      note({action: 'retry-superseded', number: item.number, runId: previous.runId, runAttempt: previous.runAttempt});
      delete item.retry;
    }
  }
  if (!failedRun(latest) || !checksFailed(checks)) return;
  if (item.attempts >= MAX_ATTEMPTS) return 'defer';
  item.retry = {runId: latest.id, runNumber: latest.run_number, runAttempt: latest.run_attempt, phase: 'requested', requestedAt: now};
  note({action: 'retry-requested', number: item.number, runId: latest.id, runAttempt: latest.run_attempt});
  return 'rerun';
}

async function dispatchRetry(github, repo, pull, retry) {
  const {data: current} = await github.rest.pulls.get({...repo, pull_number: pull.number});
  if (current.state !== 'open' || !isDependabot(current) || current.head.sha !== pull.head.sha ||
      current.base.sha !== pull.base.sha || current.base.ref !== pull.base.ref) {
    throw new Error(`PR #${pull.number} changed before CI retry`);
  }
  const [run] = await inspectCiRuns(github, repo, current);
  if (!failedRun(run) || run.id !== retry.runId || run.run_attempt !== retry.runAttempt) return false;
  const response = await github.rest.actions.reRunWorkflowFailedJobs({...repo, run_id: run.id});
  if (response.status !== 201) throw new Error(`Unexpected CI rerun response ${response.status}`);
  return true;
}

// Closing a queued update can also delete its branch. GitHub retains the PR's
// head SHA. Only create an absent ref when both records identify the same head.
async function restoreDeletedHead(github, repo, item, pull) {
  if (pull.head.repo?.full_name !== `${repo.owner}/${repo.repo}` ||
      pull.head.sha !== item.sha || !/^[0-9a-f]{40}$/.test(item.sha)) return false;
  const target = {...repo, ref: `heads/${item.ref}`};
  try {
    await github.rest.git.getRef(target);
    return false;
  } catch (error) {
    if (error.status !== 404) throw error;
  }
  let createError;
  try {
    await github.rest.git.createRef({...repo, ref: `refs/${target.ref}`, sha: item.sha});
  } catch (error) {
    createError = error;
  }
  // A competing creation or a lost response is safe only at the original SHA.
  try {
    const {data} = await github.rest.git.getRef(target);
    return data.object.sha === item.sha;
  } catch (error) {
    if (error.status === 404 && createError?.status === 422) return false;
    throw createError || error;
  }
}

// A human can open a PR after intake. Re-read membership just before changing
// it. If GitHub loses the PATCH response, the pull detail resolves the outcome.
async function reopenQueuedPull(github, repo, item, restored = false) {
  const {data: open} = await github.rest.pulls.list({...repo, state: 'open', per_page: 1});
  if (open.length) return 'busy';
  if (restored) {
    // The bot can replace or delete the branch while we check for another PR.
    try {
      const {data} = await github.rest.git.getRef({...repo, ref: `heads/${item.ref}`});
      if (data.object.sha !== item.sha) return 'refused';
    } catch (error) {
      if (error.status === 404) return 'refused';
      throw error;
    }
  }
  const target = {...repo, pull_number: item.number};
  let pull, patchError;
  try {
    ({data: pull} = await github.rest.pulls.update({...target, state: 'open'}));
  } catch (error) {
    patchError = error;
    ({data: pull} = await github.rest.pulls.get(target));
  }
  if (pull.number !== item.number || !isDependabot(pull) || pull.head.ref !== item.ref) {
    throw new Error(`Unexpected pull request identity while reopening #${item.number}`);
  }
  if (pull.state === 'open') {
    if (restored && (pull.head.sha !== item.sha || pull.head.repo?.full_name !== `${repo.owner}/${repo.repo}`)) {
      throw new Error(`Restored head changed while reopening #${item.number}`);
    }
    return 'open';
  }
  if (pull.state === 'closed' && pull.merged === true) return 'merged';
  if (pull.state === 'closed' && pull.merged === false && patchError?.status === 422) {
    if (!restored && await restoreDeletedHead(github, repo, item, pull)) {
      return reopenQueuedPull(github, repo, item, true);
    }
    return 'refused';
  }
  throw patchError || new Error(`Unconfirmed reopen for #${item.number}`);
}

function loadState(state, now) {
  const current = JSON.parse(JSON.stringify(state || emptyState()));
  if (current.schema === 1) {
    // The old counter measured observations, including requests that never ran.
    for (const item of [current.active, ...current.deferred].filter(Boolean)) {
      if (item.attempts) {
        current.history.push({at: now, action: 'legacy-retry-count', number: item.number, sha: item.sha, attempts: item.attempts});
        item.attempts = 0;
      }
    }
    current.schema = 2;
  }
  if (current.schema !== 2) throw new Error(`Unknown queue schema: ${current.schema}`);
  return current;
}

/**
 * @returns {{state: object, actions: object[]}}
 * actions: close | reopen | rerun | comment. Closing is safe only after the caller stores state.
 */
function plan({openPulls, state, checksByNumber, ciRuns = [], now, mergedNumbers}) {
  const current = loadState(state, now);
  const merged = new Set(mergedNumbers || []);
  const previousActive = current.active ? {...current.active} : null;
  current.updatedAt = now;
  const actions = [];
  const note = (action) => { current.history.push({at: now, ...action}); };
  const open = openPulls || [];
  const dependabot = open.filter(isDependabot);
  const others = open.filter((pull) => !isDependabot(pull));
  const known = new Map((current.deferred || []).map((item) => [item.number, item]));
  if (current.active) known.set(current.active.number, current.active);

  function remember(pull, status, extra) {
    const fresh = recordOf(pull);
    const previous = known.get(pull.number);
    if (previous && previous.sha === fresh.sha) {
      fresh.attempts = previous.attempts || 0;
      fresh.conflicts = previous.conflicts || 0;
      fresh.note = previous.note || '';
      if (previous.retry) fresh.retry = {...previous.retry};
    }
    return {...fresh, status, ...extra};
  }

  if (others.length) {
    current.active = null;
    const deferred = [];
    for (const pull of dependabot.sort((a, b) => byPriority(recordOf(a), recordOf(b)))) {
      const item = remember(pull, 'waiting', {note: 'deferred while another pull request is open'});
      deferred.push(item);
      actions.push({type: 'close', number: pull.number,
        comment: `Queued (#${pull.number}, ${item.ecosystem}). Another pull request is open, so this update waits. It is not discarded.`});
      note({action: 'defer', number: pull.number, reason: 'another pull request is open'});
    }
    for (const item of current.deferred || []) {
      if (!deferred.some((row) => row.number === item.number) && !dependabot.some((pull) => pull.number === item.number)) {
        deferred.push(item);
      }
    }
    if (previousActive && !merged.has(previousActive.number) && !deferred.some((row) => row.number === previousActive.number)) {
      deferred.push({...previousActive, status: 'waiting'});
      note({action: 'keep', number: previousActive.number, reason: 'recorded candidate retained while another pull request is open'});
    }
    current.deferred = deferred.filter((item) => !merged.has(item.number)).sort(byPriority);
    return {state: current, actions};
  }

  const ranked = dependabot.map((pull) => ({pull, item: remember(pull, 'active', {})})).sort((a, b) => byPriority(a.item, b.item));
  let winner = ranked[0] || null;
  if (winner && open.length === 1) {
    const checks = (checksByNumber || {})[winner.pull.number] || [];
    if (typeof winner.pull.mergeable !== 'boolean') throw new Error(`Unknown mergeability for #${winner.pull.number}`);
    const dirty = !winner.pull.mergeable;
    if (dirty) {
      const conflicts = winner.item.conflicts || 0;
      if (conflicts >= 1) {
        const item = remember(winner.pull, 'conflict', {conflicts: conflicts + 1, note: 'conflicts with the base'});
        actions.push({type: 'close', number: winner.pull.number,
          comment: `Deferred after a conflict (#${winner.pull.number}). The next queued update can proceed. This one stays recorded.`});
        note({action: 'rollback', number: winner.pull.number, reason: 'conflict'});
        ranked.shift();
        winner = ranked[0] || null;
        current.deferred = [item, ...(current.deferred || []).filter((row) => row.number !== item.number)];
      } else {
        actions.push({type: 'comment', number: winner.pull.number, comment: '@dependabot rebase'});
        note({action: 'rebase', number: winner.pull.number, reason: 'merge conflict'});
        winner.item = remember(winner.pull, 'active', {conflicts: conflicts + 1});
      }
    } else {
      const retry = planRetry(winner.item, ciRuns, checks, now, note);
      if (retry === 'defer') {
        const item = {...winner.item, status: 'failed', note: 'CI failed after confirmed retries'};
        actions.push({type: 'close', number: winner.pull.number,
          comment: `Deferred after ${item.attempts} confirmed CI retries (#${winner.pull.number}). The update stays in the queue.`});
        note({action: 'rollback', number: winner.pull.number, reason: 'checks failed'});
        ranked.shift();
        winner = ranked[0] || null;
        current.deferred = [item, ...(current.deferred || []).filter((row) => row.number !== item.number)];
      } else if (retry === 'rerun') {
        actions.push({type: 'rerun', number: winner.pull.number});
      }
    }
  }

  const keep = winner ? winner.pull.number : null;
  current.active = winner ? winner.item : null;
  const waiting = [];
  for (const row of ranked.slice(winner && ranked[0] && ranked[0].pull.number === keep ? 1 : 0)) {
    if (!keep || row.pull.number !== keep) {
      const item = remember(row.pull, 'waiting', {note: 'waiting for the active update'});
      waiting.push(item);
      actions.push({type: 'close', number: row.pull.number,
        comment: `Queued behind the active update (#${keep}). ${item.ecosystem}; security=${item.security}. Not discarded.`});
      note({action: 'defer', number: row.pull.number, reason: 'one active pull request'});
    }
  }
  for (const item of current.deferred || []) {
    if (!waiting.some((row) => row.number === item.number) && item.number !== keep) waiting.push(item);
  }
  if (previousActive && !merged.has(previousActive.number) && previousActive.number !== keep && !waiting.some((row) => row.number === previousActive.number)) {
    waiting.push({...previousActive, status: 'waiting', note: previousActive.note || 'kept because the recorded candidate is not open'});
    note({action: 'keep', number: previousActive.number, reason: 'recorded candidate was not open'});
  }
  current.deferred = waiting.filter((item) => !merged.has(item.number)).sort(byPriority);
  if (!keep) {
    const next = current.deferred.find((item) => item.status === 'waiting' &&
      (!item.reopenAfter || Date.parse(item.reopenAfter) <= Date.parse(now)));
    if (next) {
      current.active = {...next, status: 'active'};
      current.deferred = current.deferred.filter((item) => item.number !== next.number);
      actions.push({type: 'reopen', number: next.number,
        comment: `This is now the only open update (#${next.number}, ${next.ecosystem}).`});
      note({action: 'reopen-requested', number: next.number, reason: 'promoted'});
    }
  }
  return {state: current, actions};
}

module.exports = {
  ECOSYSTEMS, MAX_ATTEMPTS, emptyState, ecosystemOf, isDependabot, isSecurity,
  plan, checksFailed, inspectOpenPulls, inspectCiRuns, dispatchRetry, reopenQueuedPull, REOPEN_COOLDOWN_MS,
};
