'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { digest, inspectImage, verify } = require('./verify-toolkit-artifacts.cjs');

function response(value, status = 200, headers = {}) {
  return { status, headers, body: Buffer.from(JSON.stringify(value)) };
}

function registry({ architecture = 'amd64', corrupt = false, missingPlatform = false, auth = false } = {}) {
  const config = response({ architecture, os: 'linux' });
  const configHash = digest(config.body);
  const child = response({ schemaVersion: 2, config: { digest: configHash }, layers: [] });
  const childHash = digest(child.body);
  const index = response({ schemaVersion: 2, manifests: [{
    platform: { os: 'linux', architecture: missingPlatform ? 'arm64' : 'amd64' }, digest: childHash,
  }] });
  let tokenRequested = false;
  const get = (url, headers = {}) => {
    if (url.startsWith('https://auth.example/')) {
      tokenRequested = true;
      assert.equal(new URL(url).searchParams.get('scope'), 'repository:example/image:pull');
      return response({ token: 'test-anonymous-token' });
    }
    if (auth && !headers.Authorization) return response({}, 401, {
      'www-authenticate': 'Bearer realm="https://auth.example/token",service="registry.example"',
    });
    if (url.includes('/blobs/')) return corrupt ? response({ architecture: 'arm64' }) : config;
    if (url.endsWith(childHash)) return child;
    return index;
  };
  return { get, tokenRequested: () => tokenRequested, childHash };
}

function test() {
  const normal = registry();
  const image = inspectImage('registry.example/example/image:1.0.0', normal.get);
  assert.equal(image.platformDigest, normal.childHash);
  assert.match(image.immutableReference, /@sha256:[a-f0-9]{64}$/);
  const auth = registry({ auth: true });
  inspectImage('registry.example/example/image:1.0.0', auth.get);
  assert(auth.tokenRequested());
  assert.throws(() => inspectImage('registry.example/example/image:1', registry({ corrupt: true }).get), /digest mismatch/);
  assert.throws(() => inspectImage('registry.example/example/image:1', registry({ missingPlatform: true }).get), /No linux\/amd64/);
  assert.throws(() => inspectImage('registry.example/example/image:1', registry({ architecture: 'arm64' }).get), /not linux\/amd64/);
  assert.throws(() => inspectImage('example/image:latest', normal.get), /explicit non-latest/);
  assert.throws(() => inspectImage('example/image:1', () => response({}, 404)), /HTTP 404/);
  assert.throws(() => inspectImage('example/image:1', () => response({}, 429)), /HTTP 429/);
  assert.throws(() => inspectImage('example/image:1', () => response({}, 401)), /unsupported authentication/);
  assert.throws(() => inspectImage('example/image:1', () => response({}, 200, { 'docker-content-digest': 'sha256:wrong' })), /content digest mismatch/);

  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'toolkit-artifact-test-'));
  try {
    const matrix = {
      sourceCommit: 'a'.repeat(40),
      components: [
        { component: 'Flowise', validation: { static: 'passed' }, proposals: [
          { branch: 'test/flowise', staticValidation: 'passed', status: 'candidate-unvalidated', changes: [
            { datasource: 'docker', newValue: 'registry.example/example/image:1.0.0' },
          ] },
        ] },
        { component: 'OpenShell', validation: { static: 'not-run' }, proposals: [] },
      ],
    };
    const passed = verify(matrix, directory, normal.get);
    assert.equal(passed.status, 'passed');
    assert.equal(matrix.components[0].validation.artifactDigests, 'passed');
    assert.equal(matrix.components[1].validation.artifactDigests, 'not-run-no-complete-candidate');
    matrix.components[0].proposals[0].changes.push({ datasource: 'docker', newValue: 'example/missing:1' });
    const partial = verify(matrix, directory, normal.get, reference => {
      if (reference.startsWith('example/missing')) throw new Error('HTTP 404');
      return image;
    });
    assert.equal(partial.status, 'failed');
    assert.equal(partial.results[0].artifacts.length, 1);
    assert.equal(partial.results[0].error, 'HTTP 404');
    matrix.components[0].validation.static = 'failed';
    const blocked = verify(matrix, directory, normal.get);
    assert.match(blocked.results[0].error, /Passing static/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
  console.log('Artifact registry, digest, platform, partial-error and static-prerequisite tests passed');
}
test();
