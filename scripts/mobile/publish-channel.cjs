'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const branch = 'mobile-updates';
const inventory = 'mobile-channel.json';
const apps = [
  ['corgi-lusi-android', 'VPN Shop'],
  ['corgi-lusi-android-admin', 'Lucy Admin'],
  ['corgi-lusi-client', 'Corgi Lucy Client'],
];
const digest = data => crypto.createHash('sha256').update(data).digest('hex');
const json = value => Buffer.from(JSON.stringify(value) + '\n');
const checksum = (sha, name) => Buffer.from(`${sha}  ${name}\n`);
const validSha = sha => typeof sha === 'string' && /^[a-f0-9]{40}$/.test(sha);
const missing = error => error.status === 404;

async function optional(request) {
  try { return (await request).data; }
  catch (e) { if (!missing(e)) throw e; return null; }
}

function version(value) {
  const {versionCode, versionName} = value;
  if (!Number.isSafeInteger(versionCode) || versionCode < 1 || versionCode > 2100000000 ||
      typeof versionName !== 'string' || !/^\d+\.\d+\.\d+$/.test(versionName)) throw Error('Invalid mobile version');
  return {versionCode, versionName};
}

function tagFor({family, client}) {
  return `mobile-v${family.versionName}-${family.versionCode}-client-v${client.versionName}-${client.versionCode}`;
}

function validateCatalog(catalog) {
  version(catalog.family);
  version(catalog.client);
  if (catalog.schema !== 1 || !validSha(catalog.source) || !Number.isSafeInteger(catalog.run) || catalog.run < 1 ||
      !['signed', 'blocked_missing_apple_identity'].includes(catalog.ios) || catalog.tag !== tagFor(catalog)) {
    throw Error('Invalid mobile release provenance');
  }
  return catalog;
}

function checkAdvance(previous, next) {
  for (const key of ['family', 'client']) {
    const old = previous[key], now = next[key];
    const order = now.versionName.localeCompare(old.versionName, 'en', {numeric: true});
    if (now.versionCode < old.versionCode || order < 0 || (now.versionCode === old.versionCode && now.versionName !== old.versionName)) {
      throw Error(`Cannot move ${key} from ${old.versionName} (${old.versionCode}) to ${now.versionName} (${now.versionCode})`);
    }
  }
}

function packages(catalog) {
  const names = apps.map(([stem]) => stem + '.apk');
  const v = catalog.family.versionName.replaceAll('.', '_');
  for (const role of ['user', 'admin']) {
    const base = `corgi_lusi_ios_${role}_${v}_`;
    names.push(base + 'unsigned.ipa', base + 'simulator.zip');
    if (catalog.ios === 'signed') names.push(base + 'signed.ipa');
  }
  return names;
}

function download(repo, catalog, name) {
  return `https://github.com/${repo.owner}/${repo.repo}/releases/download/${catalog.tag}/${name}`;
}

function manifest(repo, catalog, stem, hash) {
  return json({...catalog[stem === 'corgi-lusi-client' ? 'client' : 'family'], sha256: hash, apk: download(repo, catalog, stem + '.apk')});
}

function localVersions(directory) {
  const read = name => fs.readFileSync(path.join(directory, name), 'utf8').trim();
  if (read('android-status.txt') !== 'signed') throw Error('The Android channel requires production-signed APKs');
  const [shop, admin, client] = apps.map(([stem]) => version(JSON.parse(read(stem + '.json'))));
  if (shop.versionCode !== admin.versionCode || shop.versionName !== admin.versionName) throw Error('Shop and admin versions differ');
  const ios = read('ios-status.txt');
  if (!['signed', 'blocked_missing_apple_identity'].includes(ios)) throw Error('Unknown Apple signing state');
  return {family: shop, client, ios};
}

// Keep binary buffers short-lived. The publication job has already checked Android signatures and embedded package identities.
function prepare(directory, repo, catalog) {
  const files = new Map();
  const fromDisk = name => () => fs.readFileSync(path.join(directory, name));
  const add = (name, load, data) => files.set(name, {load, digest: 'sha256:' + digest(data), size: data.length});
  for (const name of packages(catalog)) {
    const load = fromDisk(name), data = load(), sha = digest(data);
    const sidecar = fromDisk(name + '.sha256')();
    if (!data.length || !sidecar.equals(checksum(sha, name))) throw Error(`Invalid checksum for ${name}`);
    files.set(name, {load, digest: 'sha256:' + sha, size: data.length});
    add(name + '.sha256', () => sidecar, sidecar);
    if (name.endsWith('.apk')) {
      const stem = name.slice(0, -4);
      const built = JSON.parse(fromDisk(stem + '.json')());
      if (built.sha256 !== sha) throw Error(`APK and manifest disagree for ${name}`);
      const tagged = manifest(repo, catalog, stem, sha);
      add(stem + '.json', () => tagged, tagged);
    }
  }
  const proof = json(catalog);
  add(inventory, () => proof, proof);
  return files;
}

async function remoteJson(github, repo, asset) {
  if (!asset || asset.size < 1 || asset.size > 4096) throw Error('Missing or oversized published metadata');
  const result = await github.rest.repos.getReleaseAsset({...repo, asset_id: asset.id, headers: {accept: 'application/octet-stream'},
    request: {parseSuccessResponseBody: false}});
  const data = Buffer.from(await new Response(result.data).arrayBuffer());
  if (data.length !== asset.size || 'sha256:' + digest(data) !== asset.digest) throw Error(`Invalid published metadata: ${asset.name}`);
  return JSON.parse(data);
}

async function pointer(github, repo) {
  const ref = await optional(github.rest.git.getRef({...repo, ref: 'heads/' + branch}));
  if (!ref) return null;
  if (ref.object.type !== 'commit' || !validSha(ref.object.sha)) throw Error('Invalid mobile channel reference');
  const head = ref.object.sha;
  const file = (await github.rest.repos.getContent({...repo, ref: head, path: inventory})).data;
  if (file.encoding !== 'base64') throw Error('Unreadable channel catalog');
  return {head, catalog: validateCatalog(JSON.parse(Buffer.from(file.content, 'base64')))};
}

async function distribution(github, repo) {
  const release = (await github.rest.repos.getLatestRelease(repo)).data;
  if (release.draft || release.prerelease || !/^v\d+\.\d+\.\d+$/.test(release.tag_name)) throw Error('Expected a published distribution baseline');
  return release;
}

async function getBaselineTag({github, context}) {
  const repo = context.repo;
  const old = await pointer(github, repo);
  return old ? old.catalog.tag : (await distribution(github, repo)).tag_name;
}

function releaseNotes(repo, c) {
  const link = name => `[Download](${download(repo, c, name)}) · [SHA-256](${download(repo, c, name + '.sha256')})`;
  const lines = [
    '# Mobile apps · Мобильные приложения · Мобільні застосунки', '',
    '| Android | Version | APK |', '| --- | --- | --- |',
  ];
  for (const [stem, label] of apps) {
    const v = stem === 'corgi-lusi-client' ? c.client : c.family;
    lines.push(`| ${label} | ${v.versionName} (${v.versionCode}) | ${link(stem + '.apk')} |`);
  }
  lines.push('', '| iOS | Package | File |', '| --- | --- | --- |');
  for (const name of packages(c).filter(name => !name.endsWith('.apk'))) {
    const label = name.includes('_admin_') ? 'Lucy Admin' : 'VPN Shop';
    const kind = name.endsWith('unsigned.ipa') ? 'Unsigned IPA · требует подписи · потребує підпису' :
      name.endsWith('simulator.zip') ? 'Xcode Simulator ZIP' : 'Signed IPA · подписано · підписано';
    lines.push(`| ${label} ${c.family.versionName} (${c.family.versionCode}) | ${kind} | ${link(name)} |`);
  }
  const base = `https://github.com/${repo.owner}/${repo.repo}`;
  lines.push('', `[GitHub release](${base}/releases/tag/${c.tag}) · [Source](${base}/commit/${c.source}) · [Build](${base}/actions/runs/${c.run})`, '');
  return lines.join('\n');
}

async function assetsFor(github, repo, release) {
  const list = (await github.rest.repos.listReleaseAssets({...repo, release_id: release.id, per_page: 100})).data;
  if (list.length >= 100 || new Set(list.map(a => a.name)).size !== list.length) throw Error('Unexpected mobile release asset list');
  return new Map(list.map(a => [a.name, a]));
}

// Reconstruct from the original public build even when later builds of the same version differ byte-for-byte.
async function published(github, repo, release) {
  const assets = await assetsFor(github, repo, release);
  const catalog = validateCatalog(await remoteJson(github, repo, assets.get(inventory)));
  if (release.draft || release.prerelease || catalog.tag !== release.tag_name || release.target_commitish !== catalog.source) {
    throw Error('Published release does not match its provenance');
  }
  const names = packages(catalog);
  if (assets.size !== names.length * 2 + apps.length + 1) throw Error('Incomplete or unexpected public asset set');
  const manifests = {};
  for (const name of names) {
    const asset = assets.get(name);
    if (!asset || asset.size <= 0 || !/^sha256:[a-f0-9]{64}$/.test(asset.digest)) throw Error(`Missing published package: ${name}`);
    const sha = asset.digest.slice(7);
    const check = (key, data) => {
      const a = assets.get(key);
      if (!a || a.size !== data.length || a.digest !== 'sha256:' + digest(data)) throw Error(`Invalid published asset: ${key}`);
    };
    check(name + '.sha256', checksum(sha, name));
    if (name.endsWith('.apk')) {
      const stem = name.slice(0, -4);
      const tagged = manifest(repo, catalog, stem, sha);
      check(stem + '.json', tagged);
      manifests[stem + '.json'] = tagged.toString();
    }
  }
  return {catalog, manifests};
}

async function resolvePlan(github, repo, local) {
  const tag = tagFor(local);
  const prior = await pointer(github, repo);
  let previous, baselineTag;
  if (prior) {
    previous = prior.catalog;
    baselineTag = previous.tag;
  } else {
    const base = await distribution(github, repo);
    baselineTag = base.tag_name;
    const assets = await assetsFor(github, repo, base);
    const [shop, admin, client] = await Promise.all(apps.map(([stem]) => remoteJson(github, repo, assets.get(stem + '.json')).then(version)));
    if (shop.versionCode !== admin.versionCode || shop.versionName !== admin.versionName) throw Error('Inconsistent distribution baseline');
    previous = {family: shop, client};
  }
  checkAdvance(previous, local);
  const release = await optional(github.rest.repos.getReleaseByTag({...repo, tag}));
  const active = prior?.catalog.tag === tag;
  let publicFiles;
  if (release && !release.draft) {
    publicFiles = await published(github, repo, release);
    const ref = (await github.rest.git.getRef({...repo, ref: 'tags/' + tag})).data.object;
    if (publicFiles.catalog.tag !== tag || ref.type !== 'commit' || ref.sha !== publicFiles.catalog.source) throw Error('Published tag and provenance disagree');
    if (active && JSON.stringify(prior.catalog) !== JSON.stringify(publicFiles.catalog)) throw Error('Inconsistent active channel');
  } else if (active) {
    throw Error('Active channel points to a missing release');
  }
  const advanced = local.family.versionCode > previous.family.versionCode || local.client.versionCode > previous.client.versionCode;
  return {prior, release, publicFiles, tag, baselineTag, needsUpgrade: !publicFiles && advanced, needsPublish: !active};
}

async function planChannel({github, context, directory = 'dist/mobile'}) {
  const {tag, baselineTag, needsUpgrade, needsPublish} = await resolvePlan(github, context.repo, localVersions(directory));
  return {tag, baselineTag, needsUpgrade, needsPublish};
}

// Drafts may be absent from the tag lookup. A separate draft name per source lets the next
// verified commit build the same version if main advances during a previous upload.
async function findDraft(github, repo, tag) {
  const found = await optional(github.rest.repos.getReleaseByTag({...repo, tag}));
  if (found) return found;
  for (let page = 1; ; page++) {
    const list = (await github.rest.repos.listReleases({...repo, page, per_page: 100})).data;
    const item = list.find(r => r.tag_name === tag);
    if (item || list.length < 100) return item;
  }
}

async function publishChannel({github, context, core, sha, runId, directory = 'dist/mobile'}) {
  const repo = context.repo, git = github.rest.git, releases = github.rest.repos;
  const current = async () => {
    if ((await releases.getBranch({...repo, branch: 'main'})).data.commit.sha !== sha) throw Error('Verified main moved');
  };
  const versions = localVersions(directory);
  const local = validateCatalog({schema: 1, ...versions, source: sha, run: Number(runId), tag: tagFor(versions)});
  const tag = local.tag;
  const tagRef = () => optional(git.getRef({...repo, ref: 'tags/' + tag}));
  await current();
  const plan = await resolvePlan(github, repo, local);
  const {prior} = plan;
  if (!plan.needsPublish) {
    core.info(`Channel already points to ${tag}`);
    return tag;
  }
  let release = plan.release;
  if (!plan.publicFiles) {
    const draftTag = 'mobile-draft-' + sha;
    release = release || await findDraft(github, repo, draftTag);
    const ref = await tagRef();
    if ((ref && (ref.object.type !== 'commit' || ref.object.sha !== sha)) ||
        (release && (!release.draft || release.target_commitish !== sha))) {
      throw Error(`Existing draft or tag ${tag} belongs to another source commit`);
    }
    const files = prepare(directory, repo, local);
    if (!release) release = (await releases.createRelease({...repo, tag_name: draftTag, target_commitish: sha,
      name: `Mobile ${local.family.versionName} · Client ${local.client.versionName}`,
      body: releaseNotes(repo, local), draft: true, prerelease: false, make_latest: 'false'})).data;
    const existing = await assetsFor(github, repo, release);
    if ([...existing.keys()].some(name => !files.has(name))) throw Error('Unexpected asset in mobile draft');
    for (const [name, file] of files) {
      const old = existing.get(name);
      if (old?.digest === file.digest && old.size === file.size) continue;
      if (old) {
        const live = (await releases.getRelease({...repo, release_id: release.id})).data;
        if (!live.draft || live.target_commitish !== sha) throw Error('Draft changed during upload');
        await releases.deleteReleaseAsset({...repo, asset_id: old.id});
      }
      const uploaded = (await releases.uploadReleaseAsset({...repo, release_id: release.id, name, data: file.load(),
        headers: {'content-type': 'application/octet-stream', 'content-length': file.size}})).data;
      if (uploaded.digest !== file.digest || uploaded.size !== file.size) throw Error(`Upload verification failed: ${name}`);
    }
    const staged = await assetsFor(github, repo, release);
    if (staged.size !== files.size || [...files].some(([n, f]) => staged.get(n)?.digest !== f.digest || staged.get(n)?.size !== f.size)) {
      throw Error('Incomplete verified draft');
    }
    await current();
    const finalRef = await tagRef();
    if (finalRef && (finalRef.object.type !== 'commit' || finalRef.object.sha !== sha)) throw Error('Tag moved before publication');
    release = (await releases.updateRelease({...repo, release_id: release.id, tag_name: tag, target_commitish: sha,
      draft: false, make_latest: 'false', body: releaseNotes(repo, local)})).data;
  }
  const {catalog, manifests} = plan.publicFiles || await published(github, repo, release);
  const ref = await tagRef();
  if (!ref || ref.object.type !== 'commit' || ref.object.sha !== catalog.source) throw Error('Published tag and provenance disagree');
  if (catalog.source !== sha) {
    const range = (await releases.compareCommitsWithBasehead({...repo, basehead: catalog.source + '...' + sha})).data;
    if (!['identical', 'ahead'].includes(range.status)) throw Error('Published source is outside verified main history');
  }
  const documents = {...manifests, [inventory]: json(catalog).toString(), 'README.md': releaseNotes(repo, catalog)};
  const baseTree = prior && (await git.getCommit({...repo, commit_sha: prior.head})).data.tree.sha;
  const tree = (await git.createTree({...repo, ...(baseTree ? {base_tree: baseTree} : {}),
    tree: Object.entries(documents).map(([name, content]) => ({path: name, mode: '100644', type: 'blob', content}))})).data;
  const head = (await git.createCommit({...repo, tree: tree.sha, parents: prior ? [prior.head] : [],
    message: `Publish mobile update manifests for ${tag}`})).data.sha;
  await current();
  const currentRef = await tagRef();
  if (currentRef?.object.type !== 'commit' || currentRef.object.sha !== catalog.source) throw Error('Mobile tag moved before channel update');
  if (prior) await git.updateRef({...repo, ref: 'heads/' + branch, sha: head, force: false});
  else await git.createRef({...repo, ref: 'refs/heads/' + branch, sha: head});
  core.info(`Published ${tag} from ${catalog.source}`);
  return tag;
}

module.exports = {getBaselineTag, planChannel, publishChannel};
