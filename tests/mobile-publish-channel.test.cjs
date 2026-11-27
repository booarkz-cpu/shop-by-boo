'use strict';

const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {planChannel, getBaselineTag, publishChannel} = require('../scripts/mobile/publish-channel.cjs');

const hash = data => createHash('sha256').update(data).digest('hex');
const first = 'a'.repeat(40), second = 'b'.repeat(40);
const tag = 'mobile-v3.9.1-3910-client-v1.10.2-1102';
const stems = ['corgi-lusi-android', 'corgi-lusi-android-admin', 'corgi-lusi-client'];
const pair = (versionName, versionCode) => ({versionName, versionCode});
const ok = data => Promise.resolve({data});
const absent = () => Object.assign(Error('Not found'), {status: 404});

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'publish-mobile-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const state = {main: first, head: null, files: {}, refs: {}, releases: [], blobs: {}, uploads: [], events: []};
  let seq = 0;
  function asset(release, name, content) {
    const id = ++seq, data = Buffer.from(content);
    state.blobs[id] = data;
    const a = {id, name, digest: 'sha256:' + hash(data), size: data.length};
    release.assets.push(a);
    return a;
  }
  const dist = {id: 0, tag_name: 'v28.161.0', assets: [], draft: false};
  for (const stem of stems) {
    asset(dist, stem + '.json', JSON.stringify(stem.endsWith('client') ? pair('1.10.1', 1101) : pair('3.9.0', 3900)));
  }
  state.releases.push(dist);
  const byId = id => state.releases.find(r => r.id === id);
  const refs = () => ({type: 'commit', sha: state.head});
  const repos = {
    getBranch: () => ok({commit: {sha: state.main}}),
    getLatestRelease: () => ok(dist),
    getContent: ({ref, path: name}) => {
      assert.equal(ref, state.head);
      return ok({encoding: 'base64', content: Buffer.from(state.files[name]).toString('base64')});
    },
    getReleaseByTag: ({tag}) => {
      const r = state.releases.find(r => r.tag_name === tag && !r.draft);
      return r ? ok(r) : Promise.reject(absent());
    },
    getRelease: ({release_id}) => ok(byId(release_id)),
    getReleaseAsset: ({asset_id}) => ok(state.blobs[asset_id]),
    listReleaseAssets: ({release_id}) => ok(byId(release_id).assets),
    listReleases: () => ok(state.releases),
    createRelease: args => {
      assert.equal(args.draft, true); assert.equal(args.make_latest, 'false');
      const r = {...args, id: ++seq, assets: []};
      state.releases.push(r);
      return ok(r);
    },
    uploadReleaseAsset: ({release_id, name, data}) => {
      const release = byId(release_id);
      assert.equal(release.draft, true);
      state.onUpload?.(name);
      state.uploads.push(name);
      return ok(asset(release, name, data));
    },
    deleteReleaseAsset: ({asset_id}) => {
      const release = state.releases.find(r => r.assets.some(a => a.id === asset_id));
      assert.equal(release.draft, true);
      release.assets = release.assets.filter(a => a.id !== asset_id);
      return ok(null);
    },
    updateRelease: ({release_id, ...opts}) => {
      assert.equal(opts.make_latest, 'false'); assert.equal(opts.draft, false);
      const r = byId(release_id);
      assert(r.draft);
      Object.assign(r, opts);
      state.refs[r.tag_name] = opts.target_commitish;
      state.events.push('release');
      return ok(r);
    },
    compareCommitsWithBasehead: ({basehead}) => ok({status: basehead === first + '...' + second ? 'ahead' : 'diverged'}),
  };
  const git = {
    getRef: ({ref}) => {
      if (ref === 'heads/mobile-updates' && state.head) return ok({object: refs()});
      if (ref.startsWith('tags/') && state.refs[ref.slice(5)]) return ok({object: {type: 'commit', sha: state.refs[ref.slice(5)]}});
      return Promise.reject(absent());
    },
    getCommit: () => ok({tree: {sha: 'previous-tree'}}),
    createTree: ({tree}) => {
      state.next = Object.fromEntries(tree.map(item => [item.path, item.content]));
      return ok({sha: 'new-tree'});
    },
    createCommit: ({parents}) => {
      assert.deepEqual(parents, state.head ? [state.head] : []);
      return ok({sha: (++seq).toString(16).padStart(40, '0')});
    },
    createRef: ({ref, sha}) => {
      assert.equal(ref, 'refs/heads/mobile-updates');
      state.onPointer?.();
      assert.equal(state.head, null);
      state.head = sha; state.files = state.next; state.events.push('pointer');
      return ok({});
    },
    updateRef: ({ref, sha, force}) => {
      assert.equal(ref, 'heads/mobile-updates'); assert.equal(force, false);
      state.onPointer?.();
      state.head = sha; state.files = state.next; state.events.push('pointer');
      return ok({});
    },
  };
  const opts = {github: {rest: {repos, git}}, context: {repo: {owner: 'o', repo: 'r'}}, core: {info() {}}, directory, sha: first, runId: 72};
  function build({flavor = 'one', family = pair('3.9.1', 3910), client = pair('1.10.2', 1102), ios = 'blocked_missing_apple_identity'} = {}) {
    const put = (name, data) => fs.writeFileSync(path.join(directory, name), data);
    put('android-status.txt', 'signed\n'); put('ios-status.txt', ios + '\n');
    const pkg = name => {
      const content = Buffer.from(name + flavor), sha = hash(content);
      put(name, content); put(name + '.sha256', sha + '  ' + name + '\n');
      return sha;
    };
    for (const stem of stems) {
      const sha256 = pkg(stem + '.apk');
      put(stem + '.json', JSON.stringify({...stem.endsWith('client') ? client : family, sha256}));
    }
    for (const role of ['user', 'admin']) {
      const prefix = `corgi_lusi_ios_${role}_${family.versionName.replaceAll('.', '_')}_`;
      for (const kind of ['unsigned.ipa', 'simulator.zip', ...(ios === 'signed' ? ['signed.ipa'] : [])]) pkg(prefix + kind);
    }
  }
  build();
  return {opts, state, build, dir: directory};
}

test('publishes verified packages and all three tagged Android manifests before advancing one ref', async t => {
  const {opts, state} = fixture(t);
  assert.equal(await getBaselineTag(opts), 'v28.161.0');
  assert.deepEqual(await planChannel(opts), {tag, baselineTag: 'v28.161.0', needsUpgrade: true, needsPublish: true});
  assert.equal(await publishChannel(opts), tag);
  assert.deepEqual(state.events, ['release', 'pointer']);
  assert.equal(state.releases[0].assets.length, 3);
  assert.equal(state.releases[1].assets.length, 18);
  assert.equal(await getBaselineTag(opts), tag);
  for (const stem of stems) {
    const doc = JSON.parse(state.files[stem + '.json']);
    const apk = state.releases[1].assets.find(a => a.name === stem + '.apk');
    assert.equal('sha256:' + doc.sha256, apk.digest);
    assert.equal(doc.apk, 'https://github.com/o/r/releases/download/' + tag + '/' + stem + '.apk');
  }
  assert.match(state.files['README.md'], /Unsigned IPA/);
  assert.equal((state.files['README.md'].match(/\[SHA-256\]/g) || []).length, 7);
});

test('repairs only the pointer from originally published bytes after a different build of the same versions', async t => {
  const {opts, state, build} = fixture(t);
  state.onPointer = () => { throw Error('ref unavailable'); };
  await assert.rejects(publishChannel(opts), /ref unavailable/);
  assert.deepEqual(state.events, ['release']);
  assert.equal(state.head, null);
  const old = state.releases[1].assets.find(a => a.name === stems[0] + '.apk').digest;
  delete state.onPointer; state.main = second;
  build({flavor: 'nondeterministic'});
  assert.deepEqual(await planChannel(opts), {tag, baselineTag: 'v28.161.0', needsUpgrade: false, needsPublish: true});
  const count = state.uploads.length;
  await publishChannel({...opts, sha: second, runId: 79});
  assert.equal(state.uploads.length, count);
  assert.equal('sha256:' + JSON.parse(state.files[stems[0] + '.json']).sha256, old);
  assert.equal(JSON.parse(state.files['mobile-channel.json']).source, first);
  assert.deepEqual(await planChannel(opts), {tag, baselineTag: tag, needsUpgrade: false, needsPublish: false});
  await publishChannel({...opts, sha: second, runId: 80});
  assert.deepEqual(state.events, ['release', 'pointer']);
});

test('resumes an interrupted private draft with verified bytes from the retry', async t => {
  const {opts, state, build, dir} = fixture(t);
  state.onUpload = name => { if (name === stems[1] + '.apk') throw Error('upload interrupted'); };
  await assert.rejects(publishChannel(opts), /upload interrupted/);
  assert.equal(state.releases[1].draft, true); assert.equal(state.head, null);
  delete state.onUpload; build({flavor: 'new build'});
  await publishChannel({...opts, runId: 96});
  assert.equal(state.releases.length, 2);
  const expected = hash(fs.readFileSync(path.join(dir, stems[0] + '.apk')));
  assert.equal(JSON.parse(state.files[stems[0] + '.json']).sha256, expected);
});

test('a moving main leaves an unpublished draft and the verified new source can publish independently', async t => {
  const {opts, state, build} = fixture(t);
  state.onUpload = () => { state.main = second; };
  await assert.rejects(publishChannel(opts), /main moved/);
  assert.equal(state.head, null);
  assert.equal(state.releases[1].draft, true);
  delete state.onUpload;
  build({ios: 'signed'});
  await publishChannel({...opts, sha: second});
  assert.equal(state.releases[1].draft, true);
  assert.equal(state.releases[2].assets.length, 22);
  assert.match(state.files['README.md'], /Signed IPA/);
});

test('rejects damaged APKs and unsigned Android inputs before creating any draft', async t => {
  const {opts, state, dir} = fixture(t);
  fs.appendFileSync(path.join(dir, stems[0] + '.apk'), 'damage');
  await assert.rejects(publishChannel(opts), /Invalid checksum/);
  fs.writeFileSync(path.join(dir, 'android-status.txt'), 'blocked_missing_signing_key');
  await assert.rejects(planChannel(opts), /production-signed/);
  assert.equal(state.releases.length, 1);
});

test('rejects a downgrade even when another application advances, and refuses a renamed build number', async t => {
  const {opts, build, state} = fixture(t);
  await publishChannel(opts);
  build({client: pair('1.10.1', 1101), family: pair('3.10.0', 4000)});
  await assert.rejects(planChannel(opts), /Cannot move client/);
  build({family: pair('3.10.0', 3910)});
  await assert.rejects(publishChannel(opts), /Cannot move family/);
  build({client: pair('1.10.3', 1103)});
  assert.deepEqual(await planChannel(opts), {tag: 'mobile-v3.9.1-3910-client-v1.10.3-1103', baselineTag: tag, needsUpgrade: true, needsPublish: true});
  state.main = second;
  await publishChannel({...opts, sha: second});
  assert.deepEqual(state.events, ['release', 'pointer', 'release', 'pointer']);
});

test('published partial releases, mismatched tags and changed checksums cannot repair or advance the pointer', async t => {
  const {opts, state} = fixture(t);
  state.onPointer = () => { throw Error('first write failed'); };
  await assert.rejects(publishChannel(opts), /first write failed/);
  delete state.onPointer;
  const files = state.releases[1].assets;
  const missing = files.pop();
  await assert.rejects(publishChannel(opts), /metadata|asset set/);
  files.push(missing);
  state.refs[tag] = second;
  await assert.rejects(planChannel(opts), /tag and provenance/);
  state.refs[tag] = first;
  files.find(a => a.name === stems[1] + '.json').digest = 'sha256:' + '1'.repeat(64);
  await assert.rejects(publishChannel(opts), /Invalid published asset/);
  assert.equal(state.head, null);
});
