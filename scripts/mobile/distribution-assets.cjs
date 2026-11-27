'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const digest = data => 'sha256:' + createHash('sha256').update(data).digest('hex');
const checksum = (hash, name) => Buffer.from(hash.slice(7) + '  ' + name + '\n');
const api = (repo, tag, name) => 'https://github.com/' + repo.owner + '/' + repo.repo + '/releases/' + tag + '/' + name;

async function commitForTag(github, repo, tag) {
  let {object} = (await github.rest.git.getRef({...repo, ref: 'tags/' + tag})).data;
  while (object.type === 'tag') object = (await github.rest.git.getTag({...repo, tag_sha: object.sha})).data.object;
  if (object.type !== 'commit' || !/^[a-f0-9]{40}$/.test(object.sha)) throw Error('Invalid tag target: ' + tag);
  return object.sha;
}

// A workflow_run may observe a newer release in /latest. Resolve the triggering commit's own distribution.
async function selectDistribution({github, context, core}, requestedTag) {
  const repo = context.repo;
  const automatic = context.eventName === 'workflow_run';
  const trigger = context.payload.workflow_run;
  let tag = requestedTag;
  if (automatic) {
    const file = (await github.rest.repos.getContent({...repo, path: 'release-manifest.template.json', ref: trigger.head_sha})).data;
    tag = JSON.parse(Buffer.from(file.content, 'base64')).distribution_tag;
  }
  if (tag && !/^v\d+\.\d+\.\d+$/.test(tag)) throw Error('Unexpected distribution tag: ' + tag);
  let release;
  try {
    release = (tag ? await github.rest.repos.getReleaseByTag({...repo, tag}) : await github.rest.repos.getLatestRelease(repo)).data;
  } catch (err) {
    if (!automatic || err.status !== 404) throw err;
  }
  if (!release || (automatic && release.draft)) {
    core.setOutput('skip', 'true');
    return;
  }
  if (release.draft || release.prerelease || !/^v\d+\.\d+\.\d+$/.test(release.tag_name)) throw Error('Expected a published stable distribution');
  const sha = await commitForTag(github, repo, release.tag_name);
  if (automatic && sha !== trigger.head_sha) {
    core.notice('No distribution was published for this commit.');
    core.setOutput('skip', 'true');
    return;
  }
  core.setOutput('tag', release.tag_name);
  core.setOutput('ref', sha);
  core.setOutput('release_id', String(release.id));
}

function group(directory, packages, {reports = [], apk, alias, repo, tag, expectedVersion} = {}) {
  const files = new Map();
  function add(name, bytes) {
    const read = bytes ? () => bytes : () => fs.readFileSync(path.join(directory, name));
    const data = read();
    if (!data.length) throw Error('Empty asset: ' + name);
    files.set(name, {name, size: data.length, digest: digest(data), read});
    return data;
  }
  for (const name of packages) {
    add(name);
    if (!add(name + '.sha256').equals(checksum(files.get(name).digest, name))) throw Error('Invalid checksum: ' + name);
  }
  if (alias && files.get(alias).digest !== files.get(apk).digest) throw Error('APK alias differs: ' + alias);
  for (const name of reports) add(name);
  const manifest = apk && apk.replace(/\.apk$/, '.json');
  let update;
  if (manifest) {
    update = JSON.parse(fs.readFileSync(path.join(directory, manifest)));
    if (tag) update.apk = api(repo, 'download/' + tag, apk);
    add(manifest, Buffer.from(JSON.stringify(update) + '\n'));
  }
  if (update && (!Number.isSafeInteger(update.versionCode) || update.versionCode < 1 ||
      !/^\d+\.\d+\.\d+$/.test(update.versionName) || (expectedVersion && update.versionName !== expectedVersion) ||
      update.sha256 !== files.get(apk).digest.slice(7))) throw Error('Invalid APK manifest: ' + manifest);
  return {files, packages, manifest, update, apk, alias};
}

function distributionGroups(directory, repo, tag) {
  const names = fs.readdirSync(directory);
  const matchOne = regex => {
    const matches = names.map(name => regex.exec(name)).filter(Boolean);
    if (matches.length !== 1) throw Error('Expected one package matching ' + regex);
    return matches[0];
  };
  const groups = [];
  for (const role of ['user', 'admin']) {
    const [apk, version, variant] = matchOne(new RegExp('^corgi_lusi_android_' + role + '_(\\d+_\\d+_\\d+)_(release|unsigned)\\.apk$'));
    const bundle = apk.replace(/\.apk$/, '.aab');
    if (variant === 'release') {
      const stable = role === 'user' ? 'corgi-lusi-android.apk' : 'corgi-lusi-android-admin.apk';
      groups.push(group(directory, [apk, bundle, stable], {apk: stable, alias: apk, repo, tag, expectedVersion: version.replaceAll('_','.'),
        reports: [apk + '.package.txt', apk + '.certificate.txt']}));
    } else {
      groups.push(group(directory, [apk, bundle]));
    }
    const [device, iosVersion] = matchOne(new RegExp('^corgi_lusi_ios_' + role + '_(\\d+_\\d+_\\d+)_unsigned\\.ipa$'));
    const ios = 'corgi_lusi_ios_' + role + '_' + iosVersion + '_';
    groups.push(group(directory, [device]), group(directory, [ios + 'simulator.zip']));
    if (names.includes(ios + 'signed.ipa')) groups.push(group(directory, [ios + 'signed.ipa']));
  }
  return groups;
}

function clientGroup(directory, repo, tag) {
  const apk = 'corgi-lusi-client.apk';
  return group(directory, [apk], {apk, repo, tag});
}

async function jsonAsset(github, repo, asset) {
  if (!(asset.size > 0 && asset.size <= 8192)) throw Error('Invalid metadata size: ' + asset.name);
  const response = await github.rest.repos.getReleaseAsset({...repo, asset_id: asset.id, headers: {accept:'application/octet-stream'},
    request: {parseSuccessResponseBody: false}});
  const data = Buffer.from(await new Response(response.data).arrayBuffer());
  if (data.length !== asset.size || digest(data) !== asset.digest) throw Error('Invalid attached metadata: ' + asset.name);
  return JSON.parse(data);
}

function checkUpdate(update, candidate, asset, repo, tag, allowLatest) {
  const fixed = api(repo, 'download/' + tag, asset.name);
  const validUrl = update.apk === fixed || (allowLatest && update.apk === api(repo, 'latest/download', asset.name));
  if (!validUrl || update.sha256 !== asset.digest.slice(7) || update.versionName !== candidate.versionName ||
      update.versionCode !== candidate.versionCode) throw Error('Published APK/manifest mismatch: ' + asset.name);
}

// Inspect every group before uploading anything. A partial group may only be completed by its original bytes.
// Manifests are last in each group. The GitHub upload API rejects concurrent duplicates.
async function attachGroups({github, repo, release, groups, core}) {
  const args = {...repo, release_id: release.id};
  const existing = new Map();
  for (let page = 1; ; page++) {
    const assets = (await github.rest.repos.listReleaseAssets({...args, per_page:100, page})).data;
    for (const asset of assets) existing.set(asset.name, asset);
    if (assets.length < 100) break;
  }
  const upload = [];
  const allowLatest = /^v\d/.test(release.tag_name);
  for (const g of groups) {
    if (g.update) checkUpdate(g.update, g.update, g.files.get(g.apk), repo, release.tag_name, allowLatest);
    const present = [...g.files].filter(([name]) => existing.has(name));
    for (const [name] of present) {
      const asset = existing.get(name);
      if (asset.state !== 'uploaded' || !Number.isSafeInteger(asset.size) || asset.size < 1 ||
          !/^sha256:[a-f0-9]{64}$/.test(asset.digest)) throw Error('Incomplete published asset: ' + name);
    }
    if (present.length === g.files.size) {
      for (const name of g.packages) {
        const asset = existing.get(name), sidecar = existing.get(name + '.sha256');
        if (sidecar.digest !== digest(checksum(asset.digest, name))) {
          throw Error('Published checksum mismatch: ' + name);
        }
      }
      if (g.alias && existing.get(g.alias).digest !== existing.get(g.apk).digest) throw Error('Published aliases differ: ' + g.apk);
      if (g.update) checkUpdate(await jsonAsset(github, repo, existing.get(g.manifest)), g.update, existing.get(g.apk), repo, release.tag_name, allowLatest);
      core.notice(release.tag_name + ': already published ' + g.packages.join(', '));
      continue;
    }
    for (const [name, candidate] of present) {
      const asset = existing.get(name);
      if (asset.digest !== candidate.digest || asset.size !== candidate.size) throw Error('Asset differs; refusing to replace ' + name);
    }
    for (const [name, candidate] of g.files) if (!existing.has(name)) upload.push(candidate);
  }
  for (const item of upload) {
    const data = item.read();
    if (data.length !== item.size || digest(data) !== item.digest) throw Error('Candidate changed before upload: ' + item.name);
    const actual = (await github.rest.repos.uploadReleaseAsset({...args, name:item.name, data,
      headers:{'content-length':item.size, 'content-type':'application/octet-stream'}})).data;
    if (actual.size !== item.size || actual.digest !== item.digest) throw Error('Upload verification failed: ' + item.name);
  }
}

module.exports = {attachGroups, clientGroup, commitForTag, distributionGroups, jsonAsset, selectDistribution};
