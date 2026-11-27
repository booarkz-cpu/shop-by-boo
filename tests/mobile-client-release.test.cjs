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
        getReleaseAsset: async ({asset_id}) => ({data: Object.values(state.assets).flat().find(a => a.id === asset_id).bytes}),
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
        listReleaseAssets: async ({release_id, per_page, page = 1}) => ({data: assetsOf(release_id).slice((page-1)*per_page,page*per_page)}),
        uploadReleaseAsset: async ({release_id, name, data}) => {
          const asset = {id: Math.random(), name, size: data.length, digest: digest(data), bytes: data, state: 'uploaded'};
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
  fs.mkdirSync(path.join(dir, 'apps/vpn-shop/android/app'), {recursive: true});
  fs.writeFileSync(path.join(dir, 'release-manifest.template.json'), JSON.stringify({distribution_tag: 'v28.89.0'}));
  fs.writeFileSync(path.join(dir, 'apps/vpn-shop/android/app/build.gradle.kts'), 'versionName = "3.7.0"\n');
  fs.mkdirSync(path.join(dir, 'scripts/mobile'), {recursive: true});
  fs.copyFileSync(path.join(ROOT, 'scripts/mobile/distribution-assets.cjs'), path.join(dir, 'scripts/mobile/distribution-assets.cjs'));
  fs.mkdirSync(path.join(dir, 'scripts/audit'), {recursive: true});
  fs.copyFileSync(path.join(ROOT, 'scripts/audit/check_release_changelog.py'),
    path.join(dir, 'scripts/audit/check_release_changelog.py'));
  fs.mkdirSync(path.join(dir, 'docs/releases'), {recursive: true});
  const heading = '| Область | Изменение и причина | Подробности | Влияние и действия | Проверка | PR / коммит |\n' +
    '| --- | --- | --- | --- | --- | --- |\n';
  const row = '| Клиент | Изменена проверка соединения | Ранее статус зависел от запуска службы. Теперь он подтверждается ответом через туннель. | Пользователь видит подтверждённое соединение. | Регрессии состояний проверяются в CI. | https://github.com/booarkz-cpu/shop-by-boo/pull/372 |\n';
  const notes = '# client-v' + clientVersion + '\n\n' + heading + row + '\n' +
    ['Ломающие изменения', 'Миграции', 'Откат', 'Известные ограничения', 'Чем проверено']
      .map(title => '## ' + title + '\n\nУказано в отдельном разделе.\n').join('\n');
  fs.writeFileSync(path.join(dir, 'docs/releases', 'client-v' + clientVersion + '.md'), notes);
  fs.writeFileSync(path.join(dir, 'CHANGELOG.md'), '# client-v' + clientVersion + '\n\n' + heading + row);
  const put = (name, data) => fs.writeFileSync(path.join(dir, 'dist/mobile', name), data);
  put('android-status.txt', 'signed\n');
  put('ios-status.txt', 'unsigned\n');
  const apk = Buffer.from(`client apk ${clientVersion}`);
  put('corgi-lusi-client.apk', apk);
  put('corgi-lusi-client.apk.sha256', `${crypto.createHash('sha256').update(apk).digest('hex')}  corgi-lusi-client.apk\n`);
  put('corgi-lusi-client.json', JSON.stringify({versionCode: 1400, versionName: clientVersion, sha256: digest(apk).slice(7),
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
  const manifestPath = path.join(dir, 'dist/mobile/corgi-lusi-client.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath));
  fs.writeFileSync(manifestPath, JSON.stringify({...manifest, sha256: digest(rebuilt).slice(7)}) + '\n');
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

// v28.152.0 was published with 25 files of 33: the runner queue let «Build mobile apps for a release» attach its
// packages first, and this job stopped at the first one that differed, before the client and the status.
test('packages the release build already attached are kept, and the files only this job makes still arrive', async () => {
  const state = {releases: [{id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'}], assets: {}, uploads: []};
  const dir = workspace('1.4.0');
  const put = (name, data) => fs.writeFileSync(path.join(dir, 'dist/mobile', name), data);
  const shop = ['corgi_lusi_android_user_3_7_0_release.apk', 'corgi_lusi_android_user_3_7_0_release.apk.sha256',
    'corgi_lusi_android_user_3_7_0_release.aab', 'corgi_lusi_android_admin_3_7_0_release.apk',
    'corgi-lusi-android.apk', 'corgi-lusi-android.apk.sha256', 'corgi-lusi-android.json', 'corgi-lusi-android-admin.apk'];
  for (const name of shop) put(name, `built by Mobile packages: ${name}`);
  put('corgi_lusi_android_user_3_7_0_release.apk.certificate.txt', 'SHA-256 of the signing certificate');
  put('corgi_lusi_android_user_3_7_0_release.apk.package.txt', 'shop.remnawave.user');
  // the release build finished first: the same names, other bytes
  state.assets[1] = shop.map(name => ({id: name, name, size: 7, digest: digest(Buffer.from(`release build: ${name}`))}));

  await run(dir, state);
  const uploaded = state.uploads.filter(u => u.startsWith('1/')).map(u => u.slice(2)).sort();
  assert.deepEqual(uploaded, ['corgi-lusi-client.apk', 'corgi-lusi-client.apk.sha256', 'corgi-lusi-client.json',
    'mobile-production-status.json']);
  for (const name of shop) {
    assert.equal(state.assets[1].find(a => a.name === name).digest, digest(Buffer.from(`release build: ${name}`)), `${name} is not replaced`);
  }
  assert.ok(state.releases.find(r => r.tag_name === 'client-v1.4.0'), 'the client release is made as usual');
});

test('a client package that differs from the attached one still stops the job', async () => {
  const state = {releases: [{id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'}], assets: {}, uploads: []};
  state.assets[1] = [{id: 9, name: 'corgi-lusi-client.apk', state: 'uploaded', size: 3, digest: digest(Buffer.from('another client build'))}];
  await assert.rejects(run(workspace('1.4.0'), state), /Asset differs; refusing to replace corgi-lusi-client\.apk/);
  assert.deepEqual(state.uploads.filter(u => u.startsWith('1/')), [], 'nothing is attached next to a foreign client package');
});


test('a new client release preserves its detailed change table in the body', async () => {
  const state = {releases: [{id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'}], assets: {}, uploads: []};
  await run(workspace('1.11.0'), state);
  const body = state.releases.find(r => r.tag_name === 'client-v1.11.0').created.body;
  assert.ok(body.includes('| Область | Изменение и причина | Подробности |'));
  assert.ok(body.includes('Ранее статус зависел от запуска службы.'));
});

test('a new client release without detailed notes is refused before creating it', async () => {
  const state = {releases: [{id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'}], assets: {}, uploads: []};
  const dir = workspace('1.11.0');
  fs.writeFileSync(path.join(dir, 'docs/releases/client-v1.11.0.md'),
    '# client-v1.11.0\n\n' + ['Ломающие изменения', 'Миграции', 'Откат', 'Известные ограничения', 'Чем проверено']
      .map(title => '## ' + title + '\n\nОписано.\n').join('\n'));
  await assert.rejects(run(dir, state), /detailed change table is required/);
  assert.equal(state.releases.filter(r => r.tag_name.startsWith('client-v')).length, 0);
});

const {attachGroups, clientGroup, distributionGroups, selectDistribution} = require('../scripts/mobile/distribution-assets.cjs');
const repo = {owner: 'o', repo: 'r'};
const release = {id: 1, tag_name: 'v28.89.0', draft: false, body: 'notes'};
const quiet = {notice() {}};

function distributionDir(label) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'distribution-assets-'));
  function packageFile(name, data) {
    fs.writeFileSync(path.join(dir, name), data);
    fs.writeFileSync(path.join(dir, name + '.sha256'), digest(data).slice(7) + '  ' + name + '\n');
  }
  for (const role of ['user', 'admin']) {
    const apk = 'corgi_lusi_android_' + role + '_3_9_0_release.apk';
    const base = 'corgi_lusi_ios_' + role + '_3_9_0_';
    const stable = role === 'user' ? 'corgi-lusi-android.apk' : 'corgi-lusi-android-admin.apk';
    const bytes = Buffer.from(label + role);
    for (const name of [apk, apk.replace('.apk', '.aab'), stable, base + 'unsigned.ipa', base + 'simulator.zip']) packageFile(name, bytes);
    fs.writeFileSync(path.join(dir, apk + '.certificate.txt'), 'certificate of ' + apk);
    fs.writeFileSync(path.join(dir, apk + '.package.txt'), 'package info of ' + apk);
    fs.writeFileSync(path.join(dir, stable.replace('.apk','.json')), JSON.stringify({
      versionCode: 3900, versionName: '3.9.0', sha256: digest(bytes).slice(7),
      apk: 'https://github.com/o/r/releases/latest/download/' + stable,
    }) + '\n');
  }
  return dir;
}

test('an intact distribution keeps its first bytes, including permanent aliases and both update manifests', async () => {
  const state = {assets: {}, uploads: []};
  const github = fakeGitHub('abc', state);
  const first = distributionGroups(distributionDir('first'), repo, release.tag_name);
  await attachGroups({github, repo, release, core:quiet, groups:first});
  const published = state.uploads.slice();
  assert.equal(published.length, 26);
  for (const g of first.filter(g => g.manifest)) {
    assert.ok(published.indexOf('1/' + g.manifest) > published.indexOf('1/' + g.apk + '.sha256'));
    assert.equal(JSON.parse(state.assets[1].find(a => a.name === g.manifest).bytes).apk,
      'https://github.com/o/r/releases/download/' + release.tag_name + '/' + g.apk);
  }
  await attachGroups({github, repo, release, core:quiet, groups:distributionGroups(distributionDir('rebuilt'))});
  assert.deepEqual(state.uploads, published);
  const stale = state.assets[1].find(a => a.name === 'corgi-lusi-android-admin.json');
  const json = JSON.parse(stale.bytes);
  stale.bytes = Buffer.from(JSON.stringify({...json, sha256: '0'.repeat(64)}) + '\n');
  stale.digest = digest(stale.bytes);
  stale.size = stale.bytes.length;
  await assert.rejects(attachGroups({github, repo, release, core:quiet, groups:first}), /manifest mismatch/);
  assert.deepEqual(state.uploads, published);
});

test('a stopped upload resumes only with matching bytes and preflights every group before writing', async () => {
  const state = {assets: {}, uploads: []};
  const github = fakeGitHub('abc', state);
  const groups = distributionGroups(distributionDir('first'));
  await attachGroups({github, repo, release, core:quiet, groups});
  const original = state.assets[1].slice();
  const alias = original.find(a => a.name === 'corgi-lusi-android-admin.apk');
  state.assets[1] = [alias];
  state.uploads = [];
  await assert.rejects(attachGroups({github, repo, release, core:quiet, groups:distributionGroups(distributionDir('other'))}),
    /Asset differs; refusing to replace corgi-lusi-android-admin.apk/);
  assert.deepEqual(state.uploads, []);
  await attachGroups({github, repo, release, core:quiet, groups});
  assert.equal(state.assets[1].length, original.length);
  assert.equal(state.uploads.length, original.length - 1);
  assert.deepEqual(state.assets[1].map(a => [a.name,a.digest]).sort(), original.map(a => [a.name,a.digest]).sort());
});

test('local manifests, aliases and sidecars must describe the actual bytes before a release upload', () => {
  let dir = distributionDir('first');
  fs.writeFileSync(path.join(dir, 'corgi-lusi-android.apk.sha256'), '0'.repeat(64) + '  corgi-lusi-android.apk\n');
  assert.throws(() => distributionGroups(dir), /Invalid checksum/);
  dir = distributionDir('first');
  const data = Buffer.from('different APK');
  fs.writeFileSync(path.join(dir, 'corgi-lusi-android.apk'), data);
  fs.writeFileSync(path.join(dir, 'corgi-lusi-android.apk.sha256'), digest(data).slice(7) + '  corgi-lusi-android.apk\n');
  assert.throws(() => distributionGroups(dir), /alias differs/);
  dir = path.join(workspace('1.4.0'), 'dist/mobile');
  const filename = path.join(dir, 'corgi-lusi-client.json');
  const manifest = JSON.parse(fs.readFileSync(filename));
  fs.writeFileSync(filename, JSON.stringify({...manifest, sha256: '0'.repeat(64)}));
  assert.throws(() => clientGroup(dir, repo), /Invalid APK manifest/);
});

test('manual selection handles an explicit tag and empty input without workflow_run payload', async () => {
  const sha = 'c'.repeat(40);
  const state = {releases:[release]};
  const github = fakeGitHub(sha,state);
  let lookups = 0;
  github.rest.repos.getLatestRelease = async () => { lookups++; return {data:release}; };
  for (const input of ['v28.89.0', '']) {
    const result = {};
    await selectDistribution({github, context:{eventName:'workflow_dispatch',payload:{},repo},
      core:{...quiet,setOutput(k,v){result[k]=v;}}}, input);
    assert.deepEqual(result, {tag:'v28.89.0',ref:sha,release_id:'1'});
  }
  assert.equal(lookups, 1);
});

test('automatic release selection resolves the trigger SHA and ignores distributions for other commits', async () => {
  const sha = 'c'.repeat(40);
  const state = {releases:[release]};
  const github = fakeGitHub(sha,state);
  const outputs = {};
  const core = {...quiet,setOutput(k,v){outputs[k]=v;}};
  let listed = 0;
  github.rest.repos.getContent = async ({ref: source}) => {
    listed++;
    assert.equal(source, sha);
    return {data:{content: Buffer.from(JSON.stringify({distribution_tag:release.tag_name})).toString('base64')}};
  };
  const context = {eventName:'workflow_run', payload:{workflow_run:{head_sha:sha}},repo};
  await selectDistribution({github,context,core}, '');
  assert.deepEqual(outputs, {tag:release.tag_name,ref:sha,release_id:'1'});
  github.rest.git.getRef = async () => ({data:{object:{type:'tag',sha:'d'.repeat(40)}}});
  github.rest.git.getTag = async () => ({data:{object:{type:'commit',sha:'e'.repeat(40)}}});
  await selectDistribution({github,context,core}, '');
  assert.equal(outputs.skip, 'true');
  state.releases = [];
  delete outputs.skip;
  await selectDistribution({github,context,core}, '');
  assert.equal(outputs.skip, 'true');
  assert.equal(listed, 3);
});
