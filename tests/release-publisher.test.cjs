'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {publish} = require('../scripts/publish-github-release.cjs');
const {requireVerifiedMain} = require('../scripts/release-gate.cjs');
const SHA = 'a'.repeat(40), TAG = 'v28.34.0';
const ARTIFACT = 'remnawave_vpn_shop_v28_34_0_full_release.zip';
const MANIFEST = ARTIFACT.replace('.zip', '_manifest.json');
const SBOM = 'remnawave_vpn_shop_v28_34_0_sbom.cdx.json';
const digest = data => 'sha256:' + crypto.createHash('sha256').update(data).digest('hex');
const notFound = () => Object.assign(new Error('Not found'), {status: 404});

function gateFixture(event = 'push') {
  const successful = (id, kind = event) => ({id, head_sha: SHA, head_branch: 'main', event: kind,
    status: 'completed', conclusion: 'success', html_url: `https://github.com/test/shop/actions/runs/${id}`});
  const state = {main: SHA, runs: {'ci.yml': [successful(1)], 'docker.yml': [successful(2)]}, outputs: {}};
  const args = {
    github: {rest: {
      repos: {getBranch: async () => ({data: {commit: {sha: state.main}}})},
      actions: {listWorkflowRuns: async ({workflow_id}) => ({data: {workflow_runs: state.runs[workflow_id]}})},
    }},
    context: {repo: {owner: 'test', repo: 'shop'}, payload: {workflow_run: successful(2)}},
    core: {setOutput: (name, value) => {state.outputs[name] = value;}, info() {}},
  };
  return {state, args, successful};
}

for (const event of ['push', 'workflow_dispatch']) {
  test(`release gate accepts both verified main workflows after ${event}`, async () => {
    const {state, args} = gateFixture(event);
    await requireVerifiedMain(args);
    assert.equal(state.outputs.ready, 'true');
    assert.equal(state.outputs.ci_run, state.runs['ci.yml'][0].html_url);
    assert.equal(state.outputs.ci_run_id, String(state.runs['ci.yml'][0].id));
  });
}

test('release gate accepts a push and a dispatched check of the same main commit', async () => {
  const {state, args} = gateFixture('workflow_dispatch');
  state.runs['ci.yml'][0].event = 'push';
  await requireVerifiedMain(args);
  assert.equal(state.outputs.ready, 'true');
});

for (const change of [
  run => {run.event = 'pull_request';},
  run => {run.head_branch = 'feature';},
  run => {run.head_sha = 'b'.repeat(40);},
  run => {run.status = 'in_progress'; run.conclusion = null;},
  run => {run.conclusion = 'failure';},
]) {
  test(`release gate rejects an unverified trigger: ${change.toString()}`, async () => {
    const {state, args} = gateFixture();
    change(args.context.payload.workflow_run);
    await requireVerifiedMain(args);
    assert.equal(state.outputs.ready, 'false');
    assert.equal(state.outputs.ci_run, undefined);
  });
}

for (const workflow of ['ci.yml', 'docker.yml']) {
  for (const result of ['failure', 'pending', 'missing', 'other-sha', 'pull-request', 'other-branch']) {
    test(`release gate waits for ${workflow}: ${result}`, async () => {
      const {state, args, successful} = gateFixture('workflow_dispatch');
      const newest = successful(9);
      if (result === 'failure') newest.conclusion = 'failure';
      if (result === 'pending') {newest.status = 'in_progress'; newest.conclusion = null;}
      if (result === 'other-sha') newest.head_sha = 'b'.repeat(40);
      if (result === 'pull-request') newest.event = 'pull_request';
      if (result === 'other-branch') newest.head_branch = 'feature';
      state.runs[workflow] = ['failure', 'pending'].includes(result)
        ? [state.runs[workflow][0], newest] : result === 'missing' ? [] : [newest];
      await requireVerifiedMain(args);
      assert.equal(state.outputs.ready, 'false');
      assert.equal(state.outputs.ci_run, undefined);
    });
  }
}

test('release gate never publishes the previous main after a concurrent merge', async () => {
  const {state, args} = gateFixture('workflow_dispatch');
  state.main = 'b'.repeat(40);
  await requireVerifiedMain(args);
  assert.equal(state.outputs.ready, 'false');
});

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'shop-release-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const zip = Buffer.from('tested source archive');
  const sha256 = digest(zip).slice(7);
  const template = {distribution_tag: TAG, artifact: ARTIFACT, detached_manifest: MANIFEST,
    release_notes: 'notes.md', release_title: 'Verified release'};
  fs.writeFileSync(path.join(root, 'release-manifest.template.json'), JSON.stringify(template));
  fs.writeFileSync(path.join(root, ARTIFACT), zip);
  fs.writeFileSync(path.join(root, ARTIFACT + '.sha256'), `${sha256}  ${ARTIFACT}\n`);
  fs.writeFileSync(path.join(root, MANIFEST), JSON.stringify({...template, commit: SHA, sha256}));
  const sbom = Buffer.from(JSON.stringify({bomFormat: 'CycloneDX', specVersion: '1.6', components: [], dependencies: []}));
  fs.writeFileSync(path.join(root, SBOM), sbom);
  fs.writeFileSync(path.join(root, SBOM + '.sha256'), `${digest(sbom).slice(7)}  ${SBOM}\n`);
  fs.writeFileSync(path.join(root, 'notes.md'), 'Release notes');
  const state = {main: SHA, ref: null, release: null, uploads: 0, publications: 0, dispatches: 0,
    badUpload: false, moveOnUpload: false};
  const github = {rest: {
    git: {
      getRef: async () => {if (!state.ref) throw notFound(); return {data: {object: state.ref}};},
      createRef: async ({sha}) => {state.ref = {type: 'commit', sha};}
    },
    repos: {
      getBranch: async () => ({data: {commit: {sha: state.main}}}),
      getReleaseByTag: async () => {if (!state.release) throw notFound(); return {data: state.release};},
      createRelease: async args => {
        assert.equal(args.draft, true);
        state.release = {id: 1, html_url: 'https://github.com/test/releases/tag/' + TAG, draft: true, assets: []};
        return {data: state.release};
      },
      uploadReleaseAsset: async ({name, data}) => {
        state.uploads++;
        assert.equal(state.release.draft, true);
        const asset = {id: state.uploads, name, size: data.length, digest: state.badUpload ? 'sha256:bad' : digest(data)};
        state.release.assets.push(asset);
        if (state.moveOnUpload) state.main = 'b'.repeat(40);
        return {data: asset};
      },
      updateRelease: async args => {
        assert.equal(state.release.assets.length, 5);
        assert.equal(args.draft, false);
        state.publications++; state.release.draft = false;
        return {data: state.release};
      }
    },
    actions: {
      listWorkflowRuns: async () => ({data: {workflow_runs: state.dispatches ? [{head_branch: TAG, status: 'in_progress'}] : []}}),
      createWorkflowDispatch: async ({ref}) => {assert.equal(ref, TAG);state.dispatches++;}
    }
  }};
  const args = {github, context: {repo: {owner: 'test', repo: 'shop'}, payload: {workflow_run: {head_sha: SHA}}}, core: {info() {}}, root};
  return {state, args};
}

test('uploads and verifies all files before publishing and dispatches tagged images', async t => {
  const {state,args} = fixture(t); await publish(args);
  assert.equal(state.uploads,5);assert.equal(state.publications,1);assert.equal(state.dispatches,1);
  assert.equal(state.ref.sha,SHA);assert.equal(state.release.draft,false);
});
test('retry preserves existing assets and avoids duplicate publication and dispatch', async t => {
  const {state,args} = fixture(t);await publish(args);await publish(args);
  assert.equal(state.uploads,5);assert.equal(state.publications,1);assert.equal(state.dispatches,1);
});
test('stale main never creates a tag or release', async t => {
  const {state,args} = fixture(t);state.main='b'.repeat(40);
  await assert.rejects(publish(args),/current main/);assert.equal(state.ref,null);assert.equal(state.release,null);
});
test('an invalid SBOM checksum never creates a tag or release', async t => {
  const {state,args} = fixture(t);
  fs.writeFileSync(path.join(args.root, SBOM + '.sha256'), `${'0'.repeat(64)}  ${SBOM}\n`);
  await assert.rejects(publish(args),/Invalid SBOM checksum/);
  assert.equal(state.ref,null);assert.equal(state.release,null);assert.equal(state.uploads,0);
});
test('an existing tag is never moved to another commit', async t => {
  const {state,args} = fixture(t);state.ref={type:'commit',sha:'b'.repeat(40)};
  await assert.rejects(publish(args),/another commit/);assert.equal(state.ref.sha,'b'.repeat(40));assert.equal(state.uploads,0);
});
test('published release from an earlier source commit skips a maintenance commit', async t => {
  const {state,args} = fixture(t);state.ref={type:'commit',sha:'b'.repeat(40)};
  state.release={id:1,html_url:'https://github.com/test/releases/tag/'+TAG,draft:false,assets:[]};
  const release=await publish(args);
  assert.equal(release,state.release);assert.equal(state.ref.sha,'b'.repeat(40));
  assert.equal(state.uploads,0);assert.equal(state.publications,0);assert.equal(state.dispatches,0);
});
test('corrupt uploaded bytes leave the release draft', async t => {
  const {state,args} = fixture(t);state.badUpload=true;
  await assert.rejects(publish(args),/verification failed/);assert.equal(state.release.draft,true);assert.equal(state.publications,0);
});
test('published assets are never deleted or replaced on mismatch', async t => {
  const {state,args} = fixture(t);await publish(args);state.release.assets[0].digest='sha256:different';
  await assert.rejects(publish(args),/refusing to replace/);assert.equal(state.uploads,5);assert.equal(state.publications,1);
});
test('main moving during upload keeps the fully uploaded release draft', async t => {
  const {state,args} = fixture(t);state.moveOnUpload=true;
  await assert.rejects(publish(args),/moved during publication/);assert.equal(state.uploads,5);assert.equal(state.release.draft,true);assert.equal(state.publications,0);
});
test('a tag that is not visible right after creation is read again (v28.84.0)', async t => {
  const {state,args} = fixture(t);
  let hidden = 1;
  const create = args.github.rest.git.createRef, read = args.github.rest.git.getRef;
  args.github.rest.git.createRef = async a => {await create(a); hidden = 1;};
  args.github.rest.git.getRef = async a => {if (state.ref && hidden-- > 0) throw notFound(); return read(a);};
  await publish(args);
  assert.equal(state.publications,1);assert.equal(state.ref.sha,SHA);
});
