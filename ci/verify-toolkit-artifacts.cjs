'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { writeMatrix } = require('./make-upgrade-matrix.cjs');

const digest = body => `sha256:${crypto.createHash('sha256').update(body).digest('hex')}`;
const accept = 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json';

function fetchBytes(url, headers = {}) {
  if (!url.startsWith('https://')) throw new Error('Artifact transport requires HTTPS');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'toolkit-fetch-'));
  try {
    const body = path.join(dir, 'body');
    const head = path.join(dir, 'headers');
    const config = Object.entries(headers).map(([name, value]) => {
      if (!/^[A-Za-z-]+$/.test(name) || /["\\\r\n]/.test(value)) throw new Error('Invalid HTTP header');
      return `header = "${name}: ${value}"`;
    }).join('\n');
    const result = spawnSync('curl', [
      '--disable', '--config', '-', '--silent', '--show-error', '--location',
      '--proto', '=https', '--proto-redir', '=https',
      '--connect-timeout', '15', '--max-time', '120', '--max-filesize', '104857600',
      '--output', body, '--dump-header', head, '--write-out', '%{http_code}', url,
    ], { input: config + '\n', encoding: 'utf8' });
    if (result.error || result.status !== 0) throw new Error(`HTTPS transport failed (curl ${result.status}) for ${new URL(url).origin}`);
    const responseHeaders = {};
    for (const line of fs.readFileSync(head, 'utf8').trim().split(/\r?\n/)) {
      if (line.startsWith('HTTP/')) {
        for (const key of Object.keys(responseHeaders)) delete responseHeaders[key];
      }
      const separator = line.indexOf(':');
      if (separator > 0) responseHeaders[line.slice(0, separator).toLowerCase()] = line.slice(separator + 1).trim();
    }
    return { status: Number(result.stdout), headers: responseHeaders, body: fs.readFileSync(body) };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function successful(response, label) {
  if (response.status !== 200) throw new Error(`${label}: HTTP ${response.status}`);
  return response;
}

function inspectImage(reference, get = fetchBytes) {
  if (!/^[A-Za-z0-9._:/@-]+$/.test(reference) || reference.includes('://')) throw new Error('Invalid image reference');
  const slash = reference.indexOf('/');
  const first = slash < 0 ? '' : reference.slice(0, slash);
  const explicitRegistry = first.includes('.') || first.includes(':') || first === 'localhost';
  const registry = explicitRegistry ? first : 'registry-1.docker.io';
  let name = explicitRegistry ? reference.slice(slash + 1) : reference;
  const at = name.indexOf('@');
  const colon = name.lastIndexOf(':');
  const tag = at >= 0 ? name.slice(at + 1) : colon > name.lastIndexOf('/') ? name.slice(colon + 1) : null;
  name = at >= 0 ? name.slice(0, at) : tag ? name.slice(0, colon) : name;
  if (!tag || tag === 'latest') throw new Error('An explicit non-latest image tag/digest is required');
  if (!explicitRegistry && !name.includes('/')) name = `library/${name}`;
  let token;
  function request(suffix) {
    const url = `https://${registry}/v2/${name}/${suffix}`;
    const headers = { Accept: accept };
    if (token) headers.Authorization = `Bearer ${token}`;
    let response = get(url, headers);
    if (response.status === 401 && !token) {
      const challenge = response.headers['www-authenticate'] || '';
      if (!/^Bearer /i.test(challenge)) throw new Error(`Registry ${registry} requires unsupported authentication`);
      const attributes = Object.fromEntries([...challenge.matchAll(/(\w+)="([^"]*)"/g)].map(match => [match[1], match[2]]));
      const realm = new URL(attributes.realm);
      if (realm.protocol !== 'https:' || realm.username || realm.password) throw new Error('Invalid registry authentication realm');
      realm.searchParams.set('service', attributes.service || registry);
      realm.searchParams.set('scope', `repository:${name}:pull`);
      const auth = JSON.parse(successful(get(realm.href), 'Registry anonymous token').body);
      token = auth.token || auth.access_token;
      if (typeof token !== 'string' || !token || /["\\\r\n]/.test(token)) throw new Error('Invalid registry anonymous token');
      response = get(url, { ...headers, Authorization: `Bearer ${token}` });
    }
    return successful(response, `Registry ${registry}/${name}`);
  }
  function manifest(selector) {
    const response = request(`manifests/${selector}`);
    const actualDigest = digest(response.body);
    if (selector.startsWith('sha256:') && actualDigest !== selector) throw new Error('Image manifest digest mismatch');
    const reported = response.headers['docker-content-digest'];
    if (reported && reported !== actualDigest) throw new Error('Registry content digest mismatch');
    return { document: JSON.parse(response.body), digest: actualDigest };
  }
  const root = manifest(tag);
  let selected = root;
  if (Array.isArray(root.document.manifests)) {
    const platform = root.document.manifests.find(item => item.platform?.os === 'linux' && item.platform?.architecture === 'amd64');
    if (!platform || !/^sha256:[a-f0-9]{64}$/.test(platform.digest)) throw new Error('No linux/amd64 image manifest');
    selected = manifest(platform.digest);
  }
  const configDigest = selected.document.config?.digest;
  if (!/^sha256:[a-f0-9]{64}$/.test(configDigest)) throw new Error('Image configuration digest missing');
  const config = request(`blobs/${configDigest}`);
  if (digest(config.body) !== configDigest) throw new Error('Image configuration digest mismatch');
  const platform = JSON.parse(config.body);
  if (platform.os !== 'linux' || platform.architecture !== 'amd64') throw new Error('Image configuration is not linux/amd64');
  return {
    type: 'image', reference, digest: root.digest, platformDigest: selected.digest,
    platform: 'linux/amd64', immutableReference: `${registry}/${name}@${selected.digest}`,
    limitation: 'Manifest and configuration verified; layers not pulled, signature/provenance and CPU ISA not verified.',
  };
}

function command(name, args, input, env = process.env) {
  const result = spawnSync(name, args, { input, env, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  if (result.error || result.status !== 0) throw new Error(`${name} failed: ${result.error?.message || result.stderr}`);
  return result.stdout;
}

function helmEnvironment(directory, inherited = process.env) {
  const root = path.resolve(directory, 'helm-state');
  const cache = path.join(root, 'cache');
  const config = path.join(root, 'config');
  const data = path.join(root, 'data');
  for (const dir of [cache, config, data, path.join(cache, 'repository'), path.join(data, 'plugins')]) {
    fs.mkdirSync(dir, { recursive: true });
  }
  return {
    ...inherited,
    HELM_CACHE_HOME: cache,
    HELM_CONFIG_HOME: config,
    HELM_DATA_HOME: data,
    HELM_REPOSITORY_CACHE: path.join(cache, 'repository'),
    HELM_REPOSITORY_CONFIG: path.join(config, 'repositories.yaml'),
    HELM_REGISTRY_CONFIG: path.join(config, 'registry.json'),
    HELM_PLUGINS: path.join(data, 'plugins'),
  };
}

function imagesInYaml(file) {
  const documents = JSON.parse(command('yq', ['-o=json', '-I=0', 'eval-all', '[.]', file]));
  const images = [];
  function visit(value) {
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) {
      if (key === 'image' && typeof child === 'string') images.push(child);
      else visit(child);
    }
  }
  visit(documents);
  return [...new Set(images)];
}

function verifyProposal(component, proposal, dir, get = fetchBytes, inspect = inspectImage, artifacts = []) {
  const versions = [...new Set(proposal.changes.map(change => change.newValue))];
  const images = new Set();
  function download(url, filename) {
    const response = successful(get(url), `Download ${filename}`);
    if (!response.body.length) throw new Error(`Empty artifact: ${filename}`);
    const file = path.join(dir, filename);
    fs.writeFileSync(file, response.body);
    artifacts.push({ type: 'download', url, file: filename, digest: digest(response.body), bytes: response.body.length });
    return file;
  }
  if (proposal.changes.every(change => change.datasource === 'docker')) {
    for (const image of versions) images.add(image);
  } else if (component === 'Agent Sandbox') {
    if (versions.length !== 1 || !/^v\d+\.\d+\.\d+$/.test(versions[0])) throw new Error('Invalid coordinated Sandbox version');
    const version = versions[0];
    const manifest = download(`https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${version}/sandbox-with-extensions.yaml`, 'sandbox-with-extensions.yaml');
    for (const image of imagesInYaml(manifest)) images.add(image);
    for (const name of ['serviceaccount', 'rbac', 'rbac-tokenreview', 'deployment', 'service', 'pdb', 'networkpolicy']) {
      const file = download(`https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/${version}/sandbox-router/deploy/${name}.yaml`, `router-${name}.yaml`);
      for (const image of imagesInYaml(file)) {
        const effective = image.replace('registry.k8s.io/agent-sandbox/sandbox-router-go:latest',
          `registry.k8s.io/agent-sandbox/sandbox-router-go:${version}`);
        images.add(effective);
      }
    }
    images.add(`registry.k8s.io/agent-sandbox/sandbox-router-go:${version}`);
    images.add(`registry.k8s.io/agent-sandbox/python-runtime-sandbox:${version}`);
  } else if (component === 'KubeRay operator') {
    if (versions.length !== 1 || !/^\d+\.\d+\.\d+$/.test(versions[0])) throw new Error('Invalid coordinated KubeRay version');
    const version = versions[0];
    const env = helmEnvironment(dir);
    const helm = args => command('helm', args, undefined, env);
    helm(['pull', 'kuberay-operator', '--repo', 'https://ray-project.github.io/kuberay-helm/', '--version', version, '--destination', dir]);
    const filename = `kuberay-operator-${version}.tgz`;
    const file = path.join(dir, filename);
    const metadata = JSON.parse(command('yq', ['-o=json', '.', '-'], helm(['show', 'chart', file])));
    if (metadata.version !== version) throw new Error('Downloaded chart version mismatch');
    artifacts.push({ type: 'helm-chart', repository: 'https://ray-project.github.io/kuberay-helm/', version, file: filename, digest: digest(fs.readFileSync(file)) });
    const rendered = path.join(dir, 'kuberay-rendered.yaml');
    fs.writeFileSync(rendered, helm(['template', 'artifact-verification', file, '--namespace', 'artifact-verification']));
    for (const image of imagesInYaml(rendered)) images.add(image);
    if (!images.size) throw new Error('KubeRay chart rendered no images');
  } else if (component === 'yq installer utility') {
    if (versions.length !== 1 || !/^v\d+\.\d+\.\d+$/.test(versions[0])) throw new Error('Invalid yq version');
    const file = download(`https://github.com/mikefarah/yq/releases/download/${versions[0]}/yq_linux_amd64`, 'yq_linux_amd64');
    const header = fs.readFileSync(file).subarray(0, 20);
    if (header.length !== 20 || header.toString('hex', 0, 4) !== '7f454c46' || header[4] !== 2 || header[5] !== 1 || header.readUInt16LE(18) !== 62) {
      throw new Error('Downloaded yq is not an x86-64 ELF binary');
    }
    artifacts.push({ type: 'binary-metadata', architecture: 'amd64', executed: false, limitation: 'Computed hash only; publisher checksum/signature verification pending.' });
  } else {
    throw new Error(`No artifact adapter for ${component}`);
  }
  for (const image of images) artifacts.push(inspect(image, get));
  if (!artifacts.length) throw new Error('No artifacts verified');
  return artifacts;
}

function verify(matrix, outputDirectory, get = fetchBytes, inspect = inspectImage) {
  fs.mkdirSync(outputDirectory, { recursive: true });
  const results = [];
  for (const row of matrix.components) {
    const proposals = row.proposals.filter(proposal => proposal.status === 'candidate-unvalidated');
    for (const [index, proposal] of proposals.entries()) {
      const result = { component: row.component, branch: proposal.branch, status: 'failed', artifacts: [] };
      try {
        if (proposal.staticValidation !== 'passed' || row.validation.static !== 'passed') throw new Error('Passing static validation is required');
        const dir = path.join(outputDirectory, `${row.component.replace(/[^A-Za-z0-9]/g, '-')}-${index}`);
        fs.mkdirSync(dir, { recursive: true });
        verifyProposal(row.component, proposal, dir, get, inspect, result.artifacts);
        result.status = 'passed';
      } catch (error) {
        result.error = error.message;
      }
      proposal.artifactValidation = result.status;
      results.push(result);
    }
    row.validation.artifactDigests = proposals.length ? (
      proposals.every(proposal => proposal.artifactValidation === 'passed') ? 'passed' : 'failed'
    ) : 'not-run-no-complete-candidate';
  }
  return {
    generatedAt: new Date().toISOString(), discoverySourceCommit: matrix.sourceCommit,
    validationSource: matrix.validationSource, platform: 'linux/amd64',
    status: results.length && results.every(result => result.status === 'passed') ? 'passed' : 'failed',
    results,
    limitations: ['No image layers pulled or scanned', 'No publisher signature/provenance verification', 'No deployment, inference, CPU ISA or rollback tests', 'Blocked and no-candidate components are not verified'],
  };
}

module.exports = { digest, inspectImage, verifyProposal, verify, helmEnvironment };
if (require.main === module) {
  try {
    if (process.argv.length !== 6) throw new Error('Usage: node verify-toolkit-artifacts.cjs <matrix.json> <matrix-output-prefix> <report.json> <downloads-directory>');
    const matrix = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    const report = verify(matrix, process.argv[5]);
    fs.writeFileSync(process.argv[4], `${JSON.stringify(report, null, 2)}\n`);
    writeMatrix(matrix, process.argv[3]);
    for (const result of report.results) console.log(`${result.component} (${result.branch}): ${result.status}${result.error ? `: ${result.error}` : ''}`);
    if (report.status !== 'passed') throw new Error('Artifact verification incomplete or failed; inspect stable-artifact-verification.json. No deployment performed.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
