// v28.89.0 (BACKLOG A6): the «Mobile packages» publish step gives «Корги Люси: клиент» a release of its own.
// The real script from .github/workflows/mobile-release.yml runs against a fake GitHub API.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const ROOT = path.resolve(__dirname, '..');

function publishScript() {
  const text = fs.readFileSync(path.join(ROOT, '.github/workflows/mobile-release.yml'), 'utf8');
  const start = text.indexOf("const fs = require('fs');");
  const end = text.indexOf('\n      - ', start);
  return (end === -1 ? text.slice(start) : text.slice(start, end)).split('\n').map(line => line.replace(/^ {12}/, '')).join('\n');
}

function digest(data) { return 'sha256:' + crypto.createHash('sha256').update(data).digest('hex'); }

function fakeGitHub(sha, state) {
  const assetsOf = id => state.assets[id] || (state.assets[id] = []);
  return {
    rest: {
      repos: {
        getBranch: async () => ({data: {commit: {sha}}}),
        getReleaseByTag: async ({tag}) => {
          const release = state.releases.find(r => r.tag_name === tag);
          if (!release) { const e = new Error('Not Found'); e.status = 404; throw e; }
          return {data: release};
        },
        createRelease: async (args) => {
          const release = {id: 100 + state.releases.length, tag_name: args.tag_name, draft: false, body: args.body, created: args};
          state.releases.push(release);
          return {data: release};
        },
        listReleaseAssets: async ({release_id}) => ({data: assetsOf(release_id)}),
        uploadReleaseAsset: async ({release_id, name, data}) => {
          const asset = {id: Math.random(), name, size: data.length, digest: digest(data)};
          assetsOf(release_id).push(asset);
          state.uploads.push(`${release_id}/${name}`);
          return {data: asset};
        },
        deleteReleaseAsset: async () => ({}),
        updateRelease: async () => ({}),
      },
      actions: {listWorkflowRuns: async () => ({data: {workflow_runs: [{head_sha: sha, event: 'push', status: 'completed', conclusion: 'success'}]}})},
      git: {getRef: async () => ({data: {object: {type: 'commit', sha}}}), getTag: async () => ({data: {object: {type: 'commit', sha}}})},
    },
  };
}

function workspace(clientVersion) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mobile-release-'));
  fs.mkdirSync(path.join(dir, 'dist/mobile'), {recursive: true});
  fs.mkdirSync(path.join(dir, 'mobile/android-user/app'), {recursive: true});
  fs.writeFileSync(path.join(dir, 'release-manifest.template.json'), JSON.stringify({distribution_tag: 'v28.89.0'}));
  fs.writeFileSync(path.join(dir, 'mobile/android-user/app/build.gradle.kts'), 'versionName = "3.6.0"\n');
  const put = (name, data) => fs.writeFileSync(path.join(dir, 'dist/mobile', name), data);
  put('android-status.txt', 'signed\n');
  put('ios-status.txt', 'unsigned\n');
  const apk = Buffer.from(`client apk ${clientVersion}`);
  put('corgi-lusi-client.apk', apk);
  put('corgi-lusi-client.apk.sha256', `${crypto.createHash('sha256').update(apk).digest('hex')}  corgi-lusi-client.apk\n`);
  put('corgi-lusi-client.json', JSON.stringify({versionCode: 1400, versionName: clientVersion, sha256: 'abc',
    apk: 'https://github.com/o/r/releases/latest/download/corgi-lusi-client.apk'}) + '\n');
  return dir;
}

async function run(dir, state, sha = 'c0ffee') {
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const notices = [];
  const core = {notice: m => notices.push(m), summary: {addRaw: () => ({write: () => undefined})}};
  const cwd = process.cwd();
  process.chdir(dir);
  try {
    await new AsyncFunction('github', 'context', 'core', 'require', publishScript())(
      fakeGitHub(sha, state), {repo: {owner: 'o', repo: 'r'}, sha, runId: 1}, core, require);
  } finally { process.chdir(cwd); }
  return notices;
}

test('the client gets its own release once, never as «latest», with a manifest pointing at that release', async () => {
  const state = {releases: [{id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'}], assets: {}, uploads: []};
  await run(workspace('1.4.0'), state);
  const own = state.releases.find(r => r.tag_name === 'client-v1.4.0');
  assert.ok(own, 'client-v1.4.0 was created');
  assert.equal(own.created.make_latest, 'false');
  assert.equal(own.created.target_commitish, 'c0ffee');
  assert.deepEqual(state.assets[own.id].map(a => a.name).sort(), ['corgi-lusi-client.apk', 'corgi-lusi-client.apk.sha256', 'corgi-lusi-client.json']);
  assert.ok(state.uploads.includes('1/corgi-lusi-client.apk'), 'the distribution release still gets the client too');

  // The next shop release with the same client version: no second client release, nothing re-uploaded there.
  state.releases.push({id: 2, tag_name: 'v28.90.0', draft: false, body: 'notes'});
  const before = state.uploads.filter(u => u.startsWith(`${own.id}/`)).length;
  const dir = workspace('1.4.0');
  fs.writeFileSync(path.join(dir, 'release-manifest.template.json'), JSON.stringify({distribution_tag: 'v28.90.0'}));
  const rebuilt = Buffer.from('client apk 1.4.0, built again');
  fs.writeFileSync(path.join(dir, 'dist/mobile/corgi-lusi-client.apk'), rebuilt);
  fs.writeFileSync(path.join(dir, 'dist/mobile/corgi-lusi-client.apk.sha256'), `${crypto.createHash('sha256').update(rebuilt).digest('hex')}  corgi-lusi-client.apk\n`);
  const notices = await run(dir, state);
  assert.equal(state.releases.filter(r => r.tag_name.startsWith('client-v')).length, 1);
  assert.equal(state.uploads.filter(u => u.startsWith(`${own.id}/`)).length, before);
  assert.ok(notices.some(n => n.includes('already published')), 'a different build of the same version is kept, not replaced');
});

test('the client manifest of its own release points at that release', async () => {
  const state = {releases: [{id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'}], assets: {}, uploads: []};
  const dir = workspace('1.5.0');
  await run(dir, state);
  const own = state.releases.find(r => r.tag_name === 'client-v1.5.0');
  const json = state.assets[own.id].find(a => a.name === 'corgi-lusi-client.json');
  assert.ok(json);
  // Rebuild what was uploaded to compare the URL.
  const client = JSON.parse(fs.readFileSync(path.join(dir, 'dist/mobile/corgi-lusi-client.json'), 'utf8'));
  const expected = Buffer.from(JSON.stringify({...client, apk: 'https://github.com/o/r/releases/download/client-v1.5.0/corgi-lusi-client.apk'}) + '\n');
  assert.equal(json.digest, digest(expected));
});

test('without signed Android packages no client release is made', async () => {
  const state = {releases: [{id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'}], assets: {}, uploads: []};
  const dir = workspace('1.4.0');
  fs.writeFileSync(path.join(dir, 'dist/mobile/android-status.txt'), 'unsigned\n');
  await run(dir, state);
  assert.equal(state.releases.length, 1);
});
