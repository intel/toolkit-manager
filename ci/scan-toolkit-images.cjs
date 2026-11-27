'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { writeMatrix } = require('./make-upgrade-matrix.cjs');

function evaluate(report, reference) {
  if (report.SchemaVersion !== 2 || report.ArtifactName !== reference ||
      report.ArtifactType !== 'container_image' || !Array.isArray(report.Results)) {
    throw new Error('Invalid/incomplete Trivy image report or artifact identity mismatch');
  }
  const findings = report.Results.flatMap(result => (result.Vulnerabilities || []).filter(
    vulnerability => ['HIGH', 'CRITICAL'].includes(vulnerability.Severity)
  ).map(vulnerability => ({
    target: result.Target, id: vulnerability.VulnerabilityID, severity: vulnerability.Severity,
    package: vulnerability.PkgName, installedVersion: vulnerability.InstalledVersion,
    fixedVersion: vulnerability.FixedVersion || null,
  })));
  return { status: findings.length ? 'blocked-vulnerabilities' : 'passed', findings };
}

function scannerEnvironment(root, inherited = process.env) {
  const env = Object.fromEntries(Object.entries(inherited).filter(([key]) => !key.startsWith('TRIVY_')));
  const directories = {
    HOME: path.join(root, 'home'),
    XDG_CACHE_HOME: path.join(root, 'xdg-cache'),
    XDG_CONFIG_HOME: path.join(root, 'xdg-config'),
    XDG_DATA_HOME: path.join(root, 'xdg-data'),
    TMPDIR: path.join(root, 'tmp'),
  };
  for (const directory of Object.values(directories)) fs.mkdirSync(directory, { recursive: true });
  return { ...env, ...directories };
}

function executeScan(reference, output, cache, ignorefile, execute = spawnSync) {
  const root = path.dirname(ignorefile);
  const env = scannerEnvironment(root);
  const modules = path.join(root, 'modules');
  fs.mkdirSync(modules, { recursive: true });
  const args = ['image', '--image-src', 'remote', '--platform', 'linux/amd64',
    '--config', path.join(root, 'trivy.yaml'), '--module-dir', modules, '--no-progress',
    '--scanners', 'vuln', '--severity', 'HIGH,CRITICAL', '--ignore-unfixed=false',
    '--ignorefile', ignorefile, '--exit-code', '0', '--parallel', '1',
    '--timeout', '5m', '--cache-dir', cache, '--format', 'json', '--output', output, reference];
  const result = execute('trivy', args, { env, encoding: 'utf8', timeout: 360000, maxBuffer: 2 * 1024 * 1024 });
  if (result.error || result.status !== 0) throw new Error(`Trivy execution failed: ${result.error?.message || result.stderr}`);
  return JSON.parse(fs.readFileSync(output, 'utf8'));
}

function scan(matrix, artifactReport, outputDirectory, scanner = executeScan) {
  if (artifactReport.status !== 'passed' || artifactReport.discoverySourceCommit !== matrix.sourceCommit ||
      JSON.stringify(artifactReport.validationSource) !== JSON.stringify(matrix.validationSource)) {
    throw new Error('Passing artifact verification with matching source provenance is required');
  }
  fs.mkdirSync(outputDirectory, { recursive: true });
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'toolkit-scan-'));
  const images = new Map();
  const results = [];
  try {
    const ignorefile = path.join(temp, 'empty-ignorefile');
    fs.writeFileSync(ignorefile, '');
    fs.writeFileSync(path.join(temp, 'trivy.yaml'), '{}\n');
    for (const row of matrix.components) {
      const candidates = row.proposals.filter(proposal => proposal.status === 'candidate-unvalidated');
      for (const proposal of candidates) {
        const evidence = artifactReport.results.find(result => result.component === row.component && result.branch === proposal.branch);
        const result = { component: row.component, branch: proposal.branch, status: 'failed', images: [] };
        try {
          if (!evidence || evidence.status !== 'passed' || proposal.artifactValidation !== 'passed') throw new Error('Candidate artifact evidence missing');
          const artifacts = evidence.artifacts.filter(artifact => artifact.type === 'image');
          if (!artifacts.length) {
            result.status = 'not-applicable-no-container-images';
          } else {
            for (const artifact of artifacts) {
              const reference = artifact.immutableReference;
              if (!/^[A-Za-z0-9._:/-]+@sha256:[a-f0-9]{64}$/.test(reference) || artifact.platform !== 'linux/amd64') {
                throw new Error('Invalid immutable image reference/platform');
              }
              if (!images.has(reference)) {
                const file = `image-${images.size}.json`;
                try {
                  const raw = scanner(reference, path.join(outputDirectory, file), path.join(temp, 'cache'), ignorefile);
                  images.set(reference, { reference, reportFile: file, ...evaluate(raw, reference) });
                } catch (error) {
                  images.set(reference, { reference, status: 'failed', error: error.message });
                }
              }
              result.images.push(images.get(reference));
            }
            result.status = result.images.some(image => image.status === 'failed') ? 'failed' :
              result.images.some(image => image.status === 'blocked-vulnerabilities') ? 'blocked-vulnerabilities' : 'passed';
          }
        } catch (error) {
          result.error = error.message;
        }
        proposal.securityValidation = result.status;
        results.push(result);
      }
      row.validation.security = !candidates.length ? 'not-run-no-complete-candidate' :
        candidates.every(proposal => proposal.securityValidation === 'not-applicable-no-container-images') ? 'not-applicable-no-container-images' :
          candidates.every(proposal => proposal.securityValidation === 'passed') ? 'passed' : 'blocked';
    }
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
  return {
    generatedAt: new Date().toISOString(), discoverySourceCommit: matrix.sourceCommit,
    validationSource: matrix.validationSource,
    policy: { severities: ['HIGH', 'CRITICAL'], includeUnfixed: true, exceptions: [], platform: 'linux/amd64' },
    status: results.length && results.every(result => ['passed', 'not-applicable-no-container-images'].includes(result.status)) ? 'passed' : 'failed',
    results,
    limitations: ['Image vulnerability scanning only, not a security certification', 'No binary, Helm/IaC, secret, license, signature or runtime policy scanning', 'No deployment or PR authorization; non-container binaries are not scanned'],
  };
}

module.exports = { evaluate, scan, scannerEnvironment, executeScan };
if (require.main === module) {
  try {
    if (process.argv.length !== 7) throw new Error('Usage: node scan-toolkit-images.cjs <matrix.json> <artifacts.json> <matrix-output-prefix> <summary.json> <image-report-directory>');
    const version = spawnSync('trivy', ['--version'], { encoding: 'utf8', timeout: 30000 });
    if (version.error || version.status !== 0 || !/^Version: 0\.76\./m.test(version.stdout)) throw new Error('Trivy 0.76.x is required; scanner provisioning failed');
    const matrix = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    const artifacts = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
    const report = scan(matrix, artifacts, process.argv[6]);
    report.scanner = version.stdout.trim();
    fs.writeFileSync(process.argv[5], `${JSON.stringify(report, null, 2)}\n`);
    writeMatrix(matrix, process.argv[4]);
    for (const result of report.results) {
      console.log(`${result.component} (${result.branch}): ${result.status}${result.error ? `: ${result.error}` : ''}`);
      for (const image of result.images) console.log(`  ${image.reference}: ${image.status}; blocking findings: ${image.findings?.length ?? 'unknown'}${image.error ? `; ${image.error}` : ''}`);
    }
    if (report.status !== 'passed') throw new Error('Image vulnerability gate failed. Inspect stable-security-summary.json and per-image reports; no deployment performed.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
