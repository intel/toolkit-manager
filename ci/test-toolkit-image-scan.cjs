'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { evaluate, scan } = require('./scan-toolkit-images.cjs');

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
