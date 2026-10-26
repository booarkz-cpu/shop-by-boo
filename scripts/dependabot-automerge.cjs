'use strict';
/**
 * Dependabot patch auto-merge. Decides from trusted data only: the PR author, the
 * `updated-dependencies` block Dependabot writes into its commit message, and the
 * check runs of the exact head commit. Minor and major updates stay for a person.
 */

/** Update types listed in a Dependabot commit message, e.g. ["version-update:semver-patch"]. */
function updateTypes(message) {
  const block = String(message || '').split(/^updated-dependencies:\s*$/m)[1];
  if (!block) return [];
  return [...block.split(/^\.\.\.\s*$/m)[0].matchAll(/^\s*update-type:\s*(\S+)\s*$/gm)].map((m) => m[1]);
}

/** Returns {merge: boolean, reason: string}. */
function decide({author, headRef, commitMessage, checkRuns, ownRunName}) {
  if (author !== 'dependabot[bot]') return {merge: false, reason: 'not a Dependabot pull request'};
  if (!String(headRef || '').startsWith('dependabot/')) return {merge: false, reason: 'not a Dependabot branch'};
  const types = updateTypes(commitMessage);
  if (!types.length) return {merge: false, reason: 'no update metadata in the commit message'};
  const notPatch = types.filter((t) => t !== 'version-update:semver-patch');
  if (notPatch.length) return {merge: false, reason: `not a patch update: ${notPatch.join(', ')}`};
  const runs = (checkRuns || []).filter((r) => r.name !== ownRunName);
  if (!runs.length) return {merge: false, reason: 'no checks yet'};
  const pending = runs.filter((r) => r.status !== 'completed');
  if (pending.length) return {merge: false, reason: `checks still running: ${pending.map((r) => r.name).join(', ')}`};
  const failed = runs.filter((r) => !['success', 'skipped', 'neutral'].includes(r.conclusion));
  if (failed.length) return {merge: false, reason: `checks failed: ${failed.map((r) => r.name).join(', ')}`};
  return {merge: true, reason: `patch update, ${runs.length} checks green`};
}

module.exports = {decide, updateTypes};
