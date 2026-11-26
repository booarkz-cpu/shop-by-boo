'use strict';

// A GITHUB_TOKEN merge does not emit push workflows. Explicit main dispatches
// must satisfy the same two checks and exact-commit boundary as ordinary pushes.
const trustedEvent = event => ['push', 'workflow_dispatch'].includes(event);

async function requireVerifiedMain({github, context, core}) {
  core.setOutput('ready', 'false');
  const trigger = context.payload.workflow_run;
  if (!trigger || trigger.head_branch !== 'main' || !trustedEvent(trigger.event) ||
      trigger.status !== 'completed' || trigger.conclusion !== 'success') {
    core.info('Only successful push or dispatched checks on main can publish.');
    return;
  }
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const sha = trigger.head_sha;
  const main = (await github.rest.repos.getBranch({...repo, branch: 'main'})).data.commit.sha;
  if (main !== sha) {
    core.info('Newer main will publish after its own checks.');
    return;
  }
  let evidence;
  for (const workflow_id of ['ci.yml', 'docker.yml']) {
    const runs = (await github.rest.actions.listWorkflowRuns({
      ...repo, workflow_id, branch: 'main', per_page: 100,
    })).data.workflow_runs;
    // Match locally as well: the API's SHA filter has returned unrelated runs.
    // A newer failed/pending retry must never fall back to an older green run.
    const run = runs.filter(item => item.head_sha === sha && item.head_branch === 'main' &&
      trustedEvent(item.event)).sort((a, b) => b.id - a.id)[0];
    if (!run || run.status !== 'completed' || run.conclusion !== 'success') {
      core.info(`Waiting for successful ${workflow_id} on ${sha}`);
      return;
    }
    if (workflow_id === 'ci.yml') evidence = run;
  }
  if (!Number.isSafeInteger(evidence.id) || evidence.id <= 0) {
    core.info('The successful CI run has no usable artifact source ID.');
    return;
  }
  core.setOutput('ci_run', evidence.html_url);
  core.setOutput('ci_run_id', evidence.id);
  core.setOutput('ready', 'true');
}

module.exports = {requireVerifiedMain};
