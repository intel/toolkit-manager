'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const manifest = require('./toolkit-components.json');
const { writeMatrix } = require('./make-upgrade-matrix.cjs');

function run(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  return {
    command: [command, ...args].join(' '),
    status: !result.error && result.status === 0 ? 'passed' : 'failed',
    stdout: result.stdout || '',
    stderr: result.stderr || '',
    output: result.error?.message || `${result.stdout || ''}${result.stderr || ''}`,
  };
}

function verifyReferences(source, matrix) {
  for (const definition of manifest.components) {
    const row = matrix.components.find(component => component.component === definition.name);
    if (!row || row.currentReferences.length !== definition.refs.length) throw new Error(`Missing matrix references: ${definition.name}`);
    definition.refs.forEach((ref, index) => {
      const text = fs.readFileSync(path.join(source, ref.file), 'utf8');
      const matches = [...text.matchAll(new RegExp(ref.pattern, 'gm'))];
      if (matches.length !== 1 || matches[0][1] !== row.currentReferences[index].value) {
        throw new Error(`Source/matrix version mismatch: ${definition.name}: ${ref.file}`);
      }
    });
  }
}

function applyProposal(source, component, proposal) {
  const definition = manifest.components.find(row => row.name === component);
  for (const change of proposal.changes) {
    const ref = definition.refs[change.reference];
    if (!ref || ref.file !== change.file) throw new Error('Invalid candidate reference');
    const file = path.join(source, ref.file);
    const text = fs.readFileSync(file, 'utf8');
    const matches = [...text.matchAll(new RegExp(ref.pattern, 'gm'))];
    if (matches.length !== 1 || matches[0][1] !== change.currentValue) throw new Error(`Candidate source drift: ${file}`);
    const match = matches[0];
    const start = match.index + match[0].lastIndexOf(match[1]);
    fs.writeFileSync(file, text.slice(0, start) + change.newValue + text.slice(start + match[1].length));
  }
}

function checkConfiguration(source, execute = run) {
  const files = [...new Set(manifest.components.flatMap(component => component.refs.map(ref => ref.file)))]
    .filter(file => /\.ya?ml$/.test(file));
  const checks = [
    execute('bash', ['-n', 'docker/deploy.sh', 'docker/scripts/generate-docker-compose.sh'], source),
    ...files.map(file => {
      const result = execute('yq', ['eval', '.', file], source);
      if (result.status === 'passed') result.output = '';
      return result;
    }),
  ];
  const charts = [
    { chart: 'charts/kuberay', values: [] },
    { chart: 'charts/pgvector', values: ['--set-string', 'auth.postgresPassword=static-test-only', '--set-string', 'auth.password=static-test-only'] },
    { chart: 'charts/redis-stack', values: ['--set-string', 'redis-stack-server.redis_stack_server.auth.password=static-test-only'] },
  ];
  for (const { chart, values } of charts) {
    checks.push(execute('helm', ['lint', chart, ...values], source));
    const rendered = execute('helm', ['template', 'upgrade-validation', chart, '--namespace', 'upgrade-validation', ...values], source);
    if (rendered.status === 'passed') rendered.output = 'Chart rendered successfully (not Kubernetes server-schema validation).';
    checks.push(rendered);
  }
  return { status: checks.every(check => check.status === 'passed') ? 'passed' : 'failed', checks };
}

function checkCheckout(source, sourceCommit, execute = run) {
  const gitOptions = ['-c', 'core.excludesFile=/dev/null', '-c', 'core.attributesFile=/dev/null'];
  const commit = execute('git', [...gitOptions, 'rev-parse', 'HEAD'], source);
  if (commit.status !== 'passed') throw new Error(`Cannot read validation checkout commit: ${commit.output}`);
  if (commit.stdout.trim() !== sourceCommit) {
    throw new Error('Validation checkout does not match the discovery source commit');
  }
  const dirty = execute('git', [...gitOptions, 'status', '--porcelain', '--untracked-files=all'], source);
  if (dirty.status !== 'passed') throw new Error(`Cannot inspect validation checkout status: ${dirty.output}`);
  if (dirty.stdout.trim()) throw new Error(`Validation checkout must be clean:\n${dirty.stdout}`);
  return [commit, dirty];
}

function validate(source, matrix) {
  const checkout = checkCheckout(source, matrix.sourceCommit);
  for (const check of checkout) {
    if (check.stderr.trim()) console.warn(`Git checkout diagnostic: ${check.stderr.trim()}`);
  }
  const tools = [
    run('helm', ['version', '--short'], source),
    run('yq', ['--version'], source),
    run('bash', ['--version'], source),
  ];
  if (tools.some(tool => tool.status !== 'passed') ||
      !tools[1].output.includes('mikefarah/yq') || !/\bversion v4\./.test(tools[1].output)) {
    throw new Error('Static checks require Helm, Bash and mikefarah/yq v4 on the validation agent');
  }
  verifyReferences(source, matrix);
  const report = { sourceCommit: matrix.sourceCommit, generatedAt: new Date().toISOString(), checkout, tools, baseline: checkConfiguration(source), candidates: [] };
  for (const row of matrix.components) {
    for (const proposal of row.proposals.filter(candidate => candidate.status === 'candidate-unvalidated')) {
      const root = fs.mkdtempSync(path.join(os.tmpdir(), 'toolkit-static-'));
      try {
        const snapshot = path.join(root, 'source');
        fs.cpSync(source, snapshot, { recursive: true, filter: file => path.basename(file) !== '.git' });
        applyProposal(snapshot, row.component, proposal);
        const result = checkConfiguration(snapshot);
        proposal.staticValidation = result.status;
        const failures = result.checks.filter(check => check.status === 'failed').map(check => check.command);
        const baselineFailures = report.baseline.checks.filter(check => check.status === 'failed').map(check => check.command);
        report.candidates.push({
          component: row.component, branch: proposal.branch, ...result,
          inheritedFailingChecks: failures.filter(command => baselineFailures.includes(command)),
          newlyFailingChecks: failures.filter(command => !baselineFailures.includes(command)),
        });
      } finally {
        fs.rmSync(root, { recursive: true, force: true });
      }
    }
    row.validation.static = report.baseline.status === 'failed' ? 'blocked-baseline-failure' :
      row.proposals.some(proposal => proposal.staticValidation === 'failed') ? 'failed' :
        row.proposals.some(proposal => proposal.staticValidation === 'passed') ? 'passed' : 'not-run-no-complete-candidate';
  }
  report.status = report.baseline.status === 'passed' && report.candidates.every(candidate => candidate.status === 'passed') ? 'passed' : 'failed';
  return report;
}

module.exports = { applyProposal, verifyReferences, checkConfiguration, checkCheckout, run, validate };
if (require.main === module) {
  let reportWritten = false;
  try {
    if (process.argv.length !== 6) throw new Error('Usage: node validate-toolkit-config.cjs <clean-source-checkout> <matrix.json> <matrix-output-prefix> <static-report.json>');
    const matrix = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
    const report = validate(path.resolve(process.argv[2]), matrix);
    fs.writeFileSync(process.argv[5], `${JSON.stringify(report, null, 2)}\n`);
    reportWritten = true;
    writeMatrix(matrix, process.argv[4]);
    console.log(`Baseline static checks: ${report.baseline.status}`);
    for (const result of report.candidates) console.log(`${result.component} (${result.branch}): ${result.status}`);
    if (report.status !== 'passed') throw new Error('Static validation failed; inspect stable-static-validation.json for baseline and candidate errors. No deployment was performed.');
  } catch (error) {
    if (!reportWritten && process.argv.length === 6) {
      fs.writeFileSync(process.argv[5], `${JSON.stringify({ status: 'failed', phase: 'preflight', error: error.message }, null, 2)}\n`);
    }
    console.error(error.message);
    process.exitCode = 1;
  }
}
