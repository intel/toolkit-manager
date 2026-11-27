'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { evaluate, scan, scannerEnvironment, executeScan } = require('./scan-toolkit-images.cjs');

const reference = `registry.example/image@sha256:${'a'.repeat(64)}`;
const raw = {
  SchemaVersion: 2, ArtifactName: reference, ArtifactType: 'container_image',
  Results: [{ Target: 'image', Vulnerabilities: [
    { Severity: 'LOW', VulnerabilityID: 'LOW-test' },
    { Severity: 'HIGH', VulnerabilityID: 'HIGH-unfixed', PkgName: 'test', InstalledVersion: '1' },
    { Severity: 'CRITICAL', VulnerabilityID: 'CRITICAL-fixed', FixedVersion: '2' },
  ] }],
};
assert.equal(evaluate(raw, reference).status, 'blocked-vulnerabilities');
assert.equal(evaluate(raw, reference).findings.length, 2);
assert.equal(evaluate(raw, reference).findings[0].fixedVersion, null);
assert.equal(evaluate({ ...raw, Results: [] }, reference).status, 'passed');
assert.throws(() => evaluate({ ...raw, Results: undefined }, reference), /incomplete/);
assert.throws(() => evaluate({ ...raw, ArtifactName: 'other' }, reference), /identity/);
const matrix = {
  sourceCommit: 'b'.repeat(40), validationSource: { commit: 'c'.repeat(40) },
  components: [{
    component: 'Flowise', validation: {}, proposals: [{
      status: 'candidate-unvalidated', branch: 'test/flowise', artifactValidation: 'passed',
    }],
  }, {
    component: 'yq installer utility', validation: {}, proposals: [{
      status: 'candidate-unvalidated', branch: 'test/yq', artifactValidation: 'passed',
    }],
  }],
};
const artifacts = {
  status: 'passed', discoverySourceCommit: matrix.sourceCommit, validationSource: matrix.validationSource,
  results: [
    { component: 'Flowise', branch: 'test/flowise', status: 'passed', artifacts: [{ type: 'image', immutableReference: reference, platform: 'linux/amd64' }] },
    { component: 'yq installer utility', branch: 'test/yq', status: 'passed', artifacts: [{ type: 'binary-metadata' }] },
  ],
};
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'toolkit-scan-test-'));
try {
  const inherited = {
    HOME: '/proc/inaccessible-home', XDG_CACHE_HOME: '/proc/inaccessible-cache',
    XDG_CONFIG_HOME: '/proc/inaccessible-config', XDG_DATA_HOME: '/proc/inaccessible-data',
    TMPDIR: '/proc/inaccessible-tmp', PATH: process.env.PATH,
    HTTPS_PROXY: 'http://example.test:912', SSL_CERT_FILE: '/approved/ca.pem',
    TRIVY_MODULE_DIR: '/home/ubuntu/.trivy/modules', TRIVY_IGNORE_STATUS: 'affected',
    TRIVY_IGNORE_UNFIXED: 'true', TRIVY_CONFIG: '/proc/unreadable',
  };
  const env = scannerEnvironment(dir, inherited);
  for (const key of ['HOME', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'TMPDIR']) {
    assert(env[key].startsWith(dir + path.sep));
    assert(fs.statSync(env[key]).isDirectory());
  }
  assert(!Object.keys(env).some(key => key.startsWith('TRIVY_')));
  assert.equal(env.HTTPS_PROXY, inherited.HTTPS_PROXY);
  assert.equal(env.SSL_CERT_FILE, inherited.SSL_CERT_FILE);
  const output = path.join(dir, 'test-image.json');
  const ignorefile = path.join(dir, 'empty-ignorefile');
  const executed = executeScan(reference, output, path.join(dir, 'cache'), ignorefile, (name, args, options) => {
    assert.equal(name, 'trivy');
    assert.equal(args[args.indexOf('--module-dir') + 1], path.join(dir, 'modules'));
    assert(args.includes('--no-progress'));
    assert(args.includes('--ignore-unfixed=false'));
    assert.equal(args[args.indexOf('--severity') + 1], 'HIGH,CRITICAL');
    assert.equal(args[args.indexOf('--ignorefile') + 1], ignorefile);
    assert(!Object.keys(options.env).some(key => key.startsWith('TRIVY_')));
    fs.writeFileSync(output, JSON.stringify(raw));
    return { status: 0 };
  });
  assert.equal(executed.ArtifactName, reference);
  const report = scan(structuredClone(matrix), artifacts, dir, (ref, output, cache, ignorefile) => {
    assert.equal(fs.readFileSync(ignorefile, 'utf8'), '');
    assert.equal(ref, reference);
    return raw;
  });
  assert.equal(report.status, 'failed');
  assert.equal(report.results[0].status, 'blocked-vulnerabilities');
  assert.equal(report.results[1].status, 'not-applicable-no-container-images');
  const failed = scan(structuredClone(matrix), artifacts, dir, () => { throw new Error('DB unavailable'); });
  assert.equal(failed.results[0].status, 'failed');
  assert.equal(failed.results[0].images[0].error, 'DB unavailable');
  assert.equal(scan(structuredClone(matrix), artifacts, dir, () => ({ ...raw, Results: [] })).status, 'passed');
  assert.throws(() => scan(matrix, { ...artifacts, status: 'failed' }, dir), /Passing artifact/);
  assert.throws(() => scan(matrix, { ...artifacts, discoverySourceCommit: 'd'.repeat(40) }, dir), /provenance/);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}
console.log('Image vulnerability severity, unfixed, identity, provenance, execution-error and non-container tests passed');
