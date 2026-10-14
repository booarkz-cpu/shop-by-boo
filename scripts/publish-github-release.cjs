'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const digest = data => 'sha256:' + crypto.createHash('sha256').update(data).digest('hex');
const missing = error => error && error.status === 404;

async function publish({github, context, core, root = process.cwd()}) {
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const sha = context.payload.workflow_run.head_sha;
  const template = JSON.parse(fs.readFileSync(path.join(root, 'release-manifest.template.json'), 'utf8'));
  const tag = template.distribution_tag;
  if (!/^v\d+\.\d+\.\d+$/.test(tag)) throw new Error('Invalid distribution tag');
  const artifact = `remnawave_vpn_shop_${tag.replaceAll('.', '_')}_full_release.zip`;
  const detached = artifact.replace(/\.zip$/, '_manifest.json');
  if (template.artifact !== artifact || template.detached_manifest !== detached) throw new Error('Invalid artifact names');
  const names = [artifact, artifact + '.sha256', detached];
  const files = names.map(name => ({name, data: fs.readFileSync(path.join(root, name))}));
  const manifest = JSON.parse(files[2].data.toString('utf8'));
  if (manifest.commit !== sha || manifest.distribution_tag !== tag ||
      manifest.sha256 !== digest(files[0].data).slice(7)) throw new Error('Detached manifest does not match the release commit and archive');
  if (files[1].data.toString('utf8').trim() !== `${manifest.sha256}  ${artifact}`) throw new Error('Invalid checksum file');
  const main = async () => (await github.rest.repos.getBranch({...repo, branch: 'main'})).data.commit.sha;
  if (await main() !== sha) throw new Error('Verified commit is no longer current main');
  const notesPath = path.resolve(root, template.release_notes);
  if (!notesPath.startsWith(path.resolve(root) + path.sep)) throw new Error('Release notes path escapes checkout');
  const body = fs.readFileSync(notesPath, 'utf8');
  const tagRef = async () => (await github.rest.git.getRef({...repo, ref: `tags/${tag}`})).data.object;
  let ref;
  try { ref = await tagRef(); } catch (error) {
    if (!missing(error)) throw error;
    await github.rest.git.createRef({...repo, ref: `refs/tags/${tag}`, sha});
    ref = await tagRef();
  }
  let release;
  try { release = (await github.rest.repos.getReleaseByTag({...repo, tag})).data; }
  catch (error) { if (!missing(error)) throw error; }
  if (ref.type !== 'commit') throw new Error('Existing tag does not point directly to a commit');
  if (ref.sha !== sha) {
    if (release && !release.draft) {
      core.info(`Release ${tag} is already published from ${ref.sha}; skipping maintenance commit ${sha}`);
      return release;
    }
    throw new Error('Existing tag belongs to another commit');
  }
  if (!release) release = (await github.rest.repos.createRelease({
    ...repo, tag_name: tag, target_commitish: sha, name: template.release_title,
    body, draft: true, prerelease: false
  })).data;
  for (const file of files) {
    const expectedDigest = digest(file.data);
    const existing = release.assets.find(asset => asset.name === file.name);
    if (existing) {
      if (existing.digest !== expectedDigest || existing.size !== file.data.length)
        throw new Error(`Existing asset differs; refusing to replace ${file.name}`);
      continue;
    }
    if (!release.draft) throw new Error(`Published release is missing ${file.name}`);
    const uploaded = (await github.rest.repos.uploadReleaseAsset({
      ...repo, release_id: release.id, name: file.name, data: file.data,
      headers: {'content-type': file.name.endsWith('.zip') ? 'application/zip' : 'text/plain',
        'content-length': file.data.length}
    })).data;
    if (uploaded.digest !== expectedDigest || uploaded.size !== file.data.length)
      throw new Error(`Uploaded asset verification failed: ${file.name}`);
  }
  ref = await tagRef();
  if (ref.type !== 'commit' || ref.sha !== sha || await main() !== sha)
    throw new Error('Main or tag moved during publication; release remains draft');
  if (release.draft) release = (await github.rest.repos.updateRelease({
    ...repo, release_id: release.id, draft: false, make_latest: 'true'
  })).data;
  const runs = (await github.rest.actions.listWorkflowRuns({...repo, workflow_id: 'docker.yml', head_sha: sha, per_page: 100})).data.workflow_runs;
  if (!runs.some(run => run.head_branch === tag &&
      (['queued', 'in_progress'].includes(run.status) || run.conclusion === 'success'))) {
    // GITHUB_TOKEN-created tags do not trigger push workflows; dispatch explicitly.
    await github.rest.actions.createWorkflowDispatch({...repo, workflow_id: 'docker.yml', ref: tag});
  }
  core.info(`Published ${release.html_url}`);
  return release;
}
module.exports = {publish};
