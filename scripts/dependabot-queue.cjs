'use strict';
/**
 * One open pull request at a time. Dependabot may open many updates on a Monday;
 * this keeps a single merge candidate and records every other update so none is dropped.
 * Security updates go first. A candidate that keeps failing or conflicting is deferred
 * and the next recorded update is reopened. Branch protection is not bypassed.
 */

const MAX_ATTEMPTS = 2;
const ECOSYSTEMS = new Set([
  'pip', 'npm', 'gradle', 'docker', 'docker-compose', 'docker_compose',
  'github-actions', 'github_actions', 'gomod', 'cargo', 'maven', 'nuget',
  'bundler', 'composer', 'pub', 'swift', 'terraform',
]);

function emptyState(now) {
  return {schema: 1, updatedAt: now || null, active: null, deferred: [], history: []};
}

function ecosystemOf(headRef) {
  const part = String(headRef || '').split('/')[1] || 'unknown';
  return ECOSYSTEMS.has(part) ? part : part || 'unknown';
}

function isDependabot(pull) {
  const login = pull.user && pull.user.login;
  return login === 'dependabot[bot]' && String(pull.head && pull.head.ref || '').startsWith('dependabot/');
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

function clone(state) {
  return JSON.parse(JSON.stringify(state || emptyState()));
}

/**
 * @returns {{state: object, actions: object[]}}
 * actions: close | reopen | rerun | comment. Closing is safe only after the caller stores state.
 */
function plan({openPulls, state, checksByNumber, now, mergedNumbers}) {
  const current = clone(state);
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
    const item = {...(known.get(pull.number) || recordOf(pull)), ...recordOf(pull), status, ...extra};
    return item;
  }

  if (others.length) {
    current.active = null;
    const deferred = [];
    for (const pull of dependabot.sort(byPriority)) {
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
    current.deferred = deferred.sort(byPriority);
    return {state: current, actions};
  }

  const ranked = dependabot.map((pull) => ({pull, item: remember(pull, 'active', {})})).sort((a, b) => byPriority(a.item, b.item));
  let winner = ranked[0] || null;
  if (winner) {
    const checks = (checksByNumber || {})[winner.pull.number] || [];
    const dirty = winner.pull.mergeable_state === 'dirty';
    if (dirty) {
      const conflicts = (known.get(winner.pull.number) || {}).conflicts || 0;
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
    } else if (checksFailed(checks)) {
      const attempts = ((known.get(winner.pull.number) || {}).attempts || 0) + 1;
      if (attempts > MAX_ATTEMPTS) {
        const item = remember(winner.pull, 'failed', {attempts, note: 'checks failed after retries'});
        actions.push({type: 'close', number: winner.pull.number,
          comment: `Deferred after ${attempts - 1} failed check runs (#${winner.pull.number}). The update stays in the queue.`});
        note({action: 'rollback', number: winner.pull.number, reason: 'checks failed'});
        ranked.shift();
        winner = ranked[0] || null;
        current.deferred = [item, ...(current.deferred || []).filter((row) => row.number !== item.number)];
      } else {
        actions.push({type: 'rerun', number: winner.pull.number});
        note({action: 'retry', number: winner.pull.number, reason: `attempt ${attempts}`});
        winner.item = remember(winner.pull, 'active', {attempts});
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
    const next = current.deferred.find((item) => item.status === 'waiting');
    if (next) {
      current.active = {...next, status: 'active'};
      current.deferred = current.deferred.filter((item) => item.number !== next.number);
      actions.push({type: 'reopen', number: next.number,
        comment: `This is now the only open update (#${next.number}, ${next.ecosystem}).`});
      note({action: 'reopen', number: next.number, reason: 'promoted'});
    }
  }
  return {state: current, actions};
}

module.exports = {
  ECOSYSTEMS, MAX_ATTEMPTS, emptyState, ecosystemOf, isDependabot, isSecurity,
  plan, checksFailed,
};
