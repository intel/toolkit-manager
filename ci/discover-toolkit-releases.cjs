'use strict';

const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

function requestJson(url, token) {
  const result = spawnSync('curl', [
    '--disable', '--config', '-', '--silent', '--show-error', '--location',
    '--connect-timeout', '15', '--max-time', '60', '--fail-with-body',
    '--header', 'Accept: application/vnd.github+json', '--url', url,
  ], {
    input: token ? `header = "Authorization: Bearer ${token}"\n` : '',
    encoding: 'utf8',
    maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`GitHub request failed for ${url}; curl exit ${result.status}. Check network, token access and rate limits.`);
  }
  return JSON.parse(result.stdout);
}

function stableTag(tags) {
  return tags.map(tag => tag.name).filter(name => /^v?\d+\.\d+\.\d+$/.test(name))
    .sort((a, b) => {
      const left = a.replace(/^v/, '').split('.').map(Number);
      const right = b.replace(/^v/, '').split('.').map(Number);
      return right[0] - left[0] || right[1] - left[1] || right[2] - left[2];
    })[0];
}

async function discover(manifest, get) {
  const base = `https://api.github.com/repos/${manifest.repository}`;
  const commit = await get(`${base}/commits/main`);
  if (!/^[a-f0-9]{40}$/.test(commit.sha)) throw new Error('Invalid source commit');
  const files = new Map();
  const sources = new Map();
  const rows = [];
  for (const component of manifest.components) {
    const row = { component: component.name, currentReferences: [], status: 'ok', note: component.note };
    try {
      for (const ref of component.refs) {
        if (!files.has(ref.file)) {
          const blob = await get(`${base}/contents/${ref.file}?ref=${commit.sha}`);
          if (blob.encoding !== 'base64' || typeof blob.content !== 'string') throw new Error(`Invalid source file ${ref.file}`);
          files.set(ref.file, Buffer.from(blob.content, 'base64').toString('utf8'));
        }
        const matches = [...files.get(ref.file).matchAll(new RegExp(ref.pattern, 'gm'))];
        if (matches.length !== 1 || !matches[0][1]) throw new Error(`Expected exactly one version reference in ${ref.file}: ${ref.pattern}`);
        row.currentReferences.push({ file: ref.file, value: matches[0][1] });
      }
      const upstream = `https://api.github.com/repos/${component.upstream}`;
      const key = `${upstream}/${component.source || 'releases'}`;
      if (!sources.has(key)) {
        if (component.source === 'tags') {
          const tags = [];
          for (let page = 1; ; page++) {
            if (page > 100) throw new Error('Tag pagination limit reached; review source');
            const batch = await get(`${upstream}/tags?per_page=100&page=${page}`);
            if (!Array.isArray(batch)) throw new Error('Invalid tag list');
            tags.push(...batch);
            if (batch.length < 100) break;
          }
          const tag = stableTag(tags);
          if (!tag) throw new Error('No stable semantic version tags found');
          sources.set(key, { version: tag, url: `https://github.com/${component.upstream}/releases/tag/${encodeURIComponent(tag)}`, source: 'highest stable semantic tag' });
        } else {
          const release = await get(`${upstream}/releases/latest`);
          if (release.draft !== false || release.prerelease !== false ||
              typeof release.tag_name !== 'string' || !release.tag_name ||
              typeof release.html_url !== 'string' || !release.html_url.startsWith('https://github.com/')) {
            throw new Error('GitHub did not return a published stable release');
          }
          sources.set(key, { version: release.tag_name, url: release.html_url, source: 'GitHub designated latest stable release' });
        }
      }
      Object.assign(row, sources.get(key));
    } catch (error) {
      row.status = 'error';
      row.error = error.message;
    }
    rows.push(row);
  }
  return { repository: manifest.repository, sourceCommit: commit.sha, generatedAt: new Date().toISOString(), components: rows, boundaries: manifest.external };
}

function writeReport(report, prefix) {
  fs.writeFileSync(`${prefix}.json`, `${JSON.stringify(report, null, 2)}\n`);
  const cell = value => String(value ?? '').replace(/[\t\r\n]/g, ' ');
  const rows = [['component', 'current_repository_references', 'latest_upstream_stable', 'source', 'status', 'notes_or_error', 'url']];
  for (const row of report.components) {
    rows.push([row.component, row.currentReferences.map(ref => `${ref.file}: ${ref.value}`).join('; '),
      row.version, row.source, row.status, row.error || row.note, row.url]);
  }
  fs.writeFileSync(`${prefix}.tsv`, `${rows.map(row => row.map(cell).join('\t')).join('\n')}\n`);
}

async function main() {
  const token = process.env.RENOVATE_TOKEN;
  if (!token || !/^[A-Za-z0-9_]+$/.test(token)) throw new Error('RENOVATE_TOKEN is missing or has an invalid format');
  if (process.argv.length !== 4) throw new Error('Usage: node discover-toolkit-releases.cjs <manifest.json> <output-prefix>');
  const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const report = await discover(manifest, url => requestJson(url, token));
  writeReport(report, process.argv[3]);
  for (const row of report.components) {
    console.log(`${row.component}: ${row.status === 'ok' ? row.version : `ERROR: ${row.error}`}`);
  }
  if (report.components.some(row => row.status !== 'ok')) throw new Error('Component discovery is incomplete; inspect the release report');
}

module.exports = { discover, stableTag, writeReport };
if (require.main === module) main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
