'use strict';
const assert = require('node:assert/strict');
const {decide, updateTypes} = require('../scripts/dependabot-automerge.cjs');

const message = (...types) => `build(deps): bump x\n\n---\nupdated-dependencies:\n${types.map((t, i) =>
  `- dependency-name: dep${i}\n  dependency-version: 1.0.${i}\n  dependency-type: direct:production\n  update-type: ${t}\n`).join('')}...\n\nSigned-off-by: dependabot[bot] <support@github.com>`;
const green = [{name: 'Backend', status: 'completed', conclusion: 'success'}, {name: 'Docker', status: 'completed', conclusion: 'success'},
  {name: 'Merge green patch update', status: 'in_progress', conclusion: null}];
const base = {author: 'dependabot[bot]', headRef: 'dependabot/pip/backend/x-1.0.1', checkRuns: green, ownRunName: 'Merge green patch update'};

assert.deepEqual(updateTypes(message('version-update:semver-patch', 'version-update:semver-minor')),
  ['version-update:semver-patch', 'version-update:semver-minor']);
assert.equal(decide({...base, commitMessage: message('version-update:semver-patch')}).merge, true);
assert.equal(decide({...base, commitMessage: message('version-update:semver-patch', 'version-update:semver-patch')}).merge, true);
assert.match(decide({...base, commitMessage: message('version-update:semver-patch', 'version-update:semver-minor')}).reason, /not a patch/);
assert.match(decide({...base, commitMessage: message('version-update:semver-major')}).reason, /not a patch/);
assert.match(decide({...base, commitMessage: 'bump x'}).reason, /no update metadata/);
assert.match(decide({...base, author: 'someone', commitMessage: message('version-update:semver-patch')}).reason, /not a Dependabot pull/);
assert.match(decide({...base, headRef: 'feature/x', commitMessage: message('version-update:semver-patch')}).reason, /branch/);
assert.match(decide({...base, checkRuns: [...green, {name: 'E2E', status: 'in_progress'}], commitMessage: message('version-update:semver-patch')}).reason, /still running/);
assert.match(decide({...base, checkRuns: [...green, {name: 'E2E', status: 'completed', conclusion: 'failure'}], commitMessage: message('version-update:semver-patch')}).reason, /failed: E2E/);
console.log('dependabot auto-merge: ok');
