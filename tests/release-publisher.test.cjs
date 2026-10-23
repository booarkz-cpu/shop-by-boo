'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {publish} = require('../scripts/publish-github-release.cjs');
const SHA = 'a'.repeat(40), TAG = 'v28.19.0';
const ARTIFACT = 'remnawave_vpn_shop_v28_19_0_full_release.zip';
const MANIFEST = ARTIFACT.replace('.zip', '_manifest.json');
const digest = data => 'sha256:' + crypto.createHash('sha256').update(data).digest('hex');
const notFound = () => Object.assign(new Error('Not found'), {status: 404});

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
        assert.equal(state.release.assets.length, 3);
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
  assert.equal(state.uploads,3);assert.equal(state.publications,1);assert.equal(state.dispatches,1);
  assert.equal(state.ref.sha,SHA);assert.equal(state.release.draft,false);
});
test('retry preserves existing assets and avoids duplicate publication and dispatch', async t => {
  const {state,args} = fixture(t);await publish(args);await publish(args);
  assert.equal(state.uploads,3);assert.equal(state.publications,1);assert.equal(state.dispatches,1);
});
test('stale main never creates a tag or release', async t => {
  const {state,args} = fixture(t);state.main='b'.repeat(40);
  await assert.rejects(publish(args),/current main/);assert.equal(state.ref,null);assert.equal(state.release,null);
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
  await assert.rejects(publish(args),/refusing to replace/);assert.equal(state.uploads,3);assert.equal(state.publications,1);
});
test('main moving during upload keeps the fully uploaded release draft', async t => {
  const {state,args} = fixture(t);state.moveOnUpload=true;
  await assert.rejects(publish(args),/moved during publication/);assert.equal(state.uploads,3);assert.equal(state.release.draft,true);assert.equal(state.publications,0);
});
