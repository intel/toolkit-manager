'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { discover, stableTag, writeReport } = require('./discover-toolkit-releases.cjs');

async function test() {
  assert.equal(stableTag([{ name: 'v0.8.7' }, { name: 'v0.9.0-rc1' }, { name: 'v0.10.0' }]), 'v0.10.0');
  assert.equal(stableTag([{ name: 'v1.0.0-rc1' }]), undefined);
  const inventory = JSON.parse(fs.readFileSync(path.join(__dirname, 'toolkit-components.json'), 'utf8'));
  assert.equal(inventory.components.length, 14);
  assert.equal(new Set(inventory.components.map(component => component.name)).size, 14);
  assert.equal(inventory.components.find(component => component.name === 'pgvector').source, 'tags');
  assert(inventory.components.every(component => component.refs.length && component.note && component.upstream));
  const manifest = {
    repository: 'example/toolkit',
    components: [
      { name: 'release', upstream: 'example/release', refs: [{ file: 'config.yaml', pattern: '^version: "(.*)"' }] },
      { name: 'tags', upstream: 'example/tags', source: 'tags', refs: [{ file: 'config.yaml', pattern: '^version: "(.*)"' }] },
    ],
    external: [],
  };
  const get = async url => {
    if (url.endsWith('/commits/main')) return { sha: 'a'.repeat(40) };
    if (url.includes('/contents/')) return { encoding: 'base64', content: Buffer.from('version: "1.0.0"\n').toString('base64') };
    if (url.includes('/tags?')) return [{ name: 'v1.0.1' }, { name: 'v2.0.0-rc1' }];
    return { tag_name: 'v1.0.2', draft: false, prerelease: false, html_url: 'https://github.com/example/release/releases/tag/v1.0.2' };
  };
  const result = await discover(manifest, get);
  assert.deepEqual(result.components.map(row => row.status), ['ok', 'ok']);
  assert.equal(result.components[0].version, 'v1.0.2');
  assert.equal(result.components[1].version, 'v1.0.1');
  const prerelease = await discover(manifest, async url => url.endsWith('/releases/latest') ?
    { tag_name: 'v2.0.0-rc1', draft: false, prerelease: true, html_url: 'https://github.com/example' } : get(url));
  assert.equal(prerelease.components[0].status, 'error');
  const missing = await discover(manifest, async url => url.includes('/contents/') ?
    { encoding: 'base64', content: Buffer.from('other: 1').toString('base64') } : get(url));
  assert(missing.components.every(row => row.status === 'error'));
  const failed = await discover(manifest, async url => {
    if (url.endsWith('/releases/latest')) throw new Error('HTTP 403');
    return get(url);
  });
  assert.equal(failed.components[0].status, 'error');
  assert.equal(failed.components[1].status, 'ok');
  for (const response of [
    { tag_name: 'v2.0.0', draft: true, prerelease: false, html_url: 'https://github.com/example' },
    { tag_name: '', draft: false, prerelease: false, html_url: 'https://github.com/example' },
    {},
  ]) {
    const invalid = await discover(manifest, async url => url.endsWith('/releases/latest') ? response : get(url));
    assert.equal(invalid.components[0].status, 'error');
  }
  const duplicate = await discover(manifest, async url => url.includes('/contents/') ?
    { encoding: 'base64', content: Buffer.from('version: "1"\nversion: "2"\n').toString('base64') } : get(url));
  assert(duplicate.components.every(row => row.status === 'error'));
  const pages = [];
  const paginated = await discover(manifest, async url => {
    if (!url.includes('/tags?')) return get(url);
    pages.push(url);
    return url.endsWith('page=1') ? Array.from({ length: 100 }, () => ({ name: 'v1.0.0' })) : [{ name: 'v2.0.0' }];
  });
  assert.equal(pages.length, 2);
  assert.equal(paginated.components[1].version, 'v2.0.0');
  await assert.rejects(discover(manifest, async () => ({ sha: 'invalid' })), /Invalid source commit/);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'toolkit-release-test-'));
  try {
    const prefix = path.join(dir, 'report');
    writeReport(failed, prefix);
    assert.equal(JSON.parse(fs.readFileSync(`${prefix}.json`, 'utf8')).components[0].error, 'HTTP 403');
    const table = fs.readFileSync(`${prefix}.tsv`, 'utf8').trimEnd().split('\n');
    assert.equal(table.length, 3);
    assert(table[1].includes('\terror\tHTTP 403\t'));
    assert(table[2].includes('\tv1.0.1\t'));
  } finally {
    fs.rmSync(path.join(dir, 'report.json'), { force: true });
    fs.rmSync(path.join(dir, 'report.tsv'), { force: true });
    fs.rmdirSync(dir);
  }
  if (process.argv[2]) {
    for (const component of inventory.components) {
      for (const ref of component.refs) {
        const text = fs.readFileSync(path.join(process.argv[2], ref.file), 'utf8');
        assert.equal([...text.matchAll(new RegExp(ref.pattern, 'gm'))].length, 1, `${component.name}: ${ref.file}`);
      }
    }
    const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'renovate-config.json'), 'utf8'));
    for (const manager of config.customManagers.slice(0, 3)) {
      let matches = 0;
      for (const file of ['config.yaml', 'roles/kuberay/defaults/main.yaml', 'docker/scripts/generate-docker-compose.sh', 'docker/deploy.sh']) {
        if (!manager.managerFilePatterns.some(pattern => new RegExp(pattern.slice(1, -1)).test(file))) continue;
        const text = fs.readFileSync(path.join(process.argv[2], file), 'utf8');
        matches += [...text.matchAll(new RegExp(manager.matchStrings[0], 'g'))].length;
      }
      assert.equal(matches, manager.packageNameTemplate === 'kuberay-operator' ? 2 : manager.packageNameTemplate === 'mikefarah/yq' ? 1 : 3);
    }
  }
  console.log('Toolkit release discovery tests passed');
}
test().catch(error => { console.error(error); process.exitCode = 1; });
