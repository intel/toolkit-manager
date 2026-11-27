'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { makeMatrix, writeMatrix } = require('./make-upgrade-matrix.cjs');
const { applyProposal, checkConfiguration, checkCheckout, checkTools, run } = require('./validate-toolkit-config.cjs');
const manifest = require('./toolkit-components.json');
const policy = require('./toolkit-upgrade-policy.json');

// Build #30's supplied source-release observation, kept separate from registry evidence.
const observations = [
  [['v1.0.10', 'v1.0.10'], 'v1.0.12'],
  [['1.3.0', '1.3.0'], 'v1.8.0'],
  [['rayproject/ray:2.40.0-py312', 'rayproject/ray:2.40.0-py312', '2.40.0'], 'ray-2.60.1'],
  [['0.1.6', '0.1.6', 'v0.1.6'], 'v0.1.10'],
  [['16', 'pg16', 'pgvector/pgvector:pg16'], 'v0.8.7'],
  [['7.4.0-v8', 'redis/redis-stack-server:7.4.0-v8'], 'v7.4.0-v8'],
  [['docker.litellm.ai/berriai/litellm:v1.83.14-stable.patch.2'], 'v1.111.0'],
  [['flowiseai/flowise:3.1.2'], 'flowise@3.1.4'],
  [['bitnamilegacy/clickhouse:25.2.1'], 'v26.9.40.9-stable'],
  [['bitnamilegacy/minio:2024.12.18'], 'RELEASE.2025-10-15T17-29-55Z'],
  [['langfuse/langfuse:3.106.1', 'langfuse/langfuse-worker:3.106.1'], 'v4.88.0'],
  [['vllm/vllm-openai-cpu:v0.28.0'], 'v0.34.0'],
  [['openvino/model_server:2025.4.1', 'openvino/model_server:2025.4.1-py'], 'v2026.4.1'],
  [['v4.44.1'], 'v4.54.3'],
];

function componentReport() {
  return {
    repository: manifest.repository,
    sourceCommit: 'b3a29592ff6cb0dbc3adce0de8b334964db38e27',
    generatedAt: '2026-11-27T10:30:51.620Z',
    components: manifest.components.map((definition, index) => ({
      component: definition.name, status: 'ok', note: definition.note,
      version: observations[index][1],
      url: `https://github.com/${definition.upstream}/releases/tag/${encodeURIComponent(observations[index][1])}`,
      currentReferences: definition.refs.map((ref, i) => ({ file: ref.file, value: observations[index][0][i] })),
    })),
  };
}

function fixture() {
  const components = componentReport();
  const files = [];
  const branches = [];
  for (const row of components.components) {
    const rules = policy[row.component];
    const upgrades = [];
    row.currentReferences.forEach((ref, index) => {
      const name = rules.dependencies[index];
      if (name === null) return;
      const currentValue = ref.value.includes(':') ? ref.value.split(':').at(-1) : ref.value;
      const newValue = row.component === 'OpenVINO Model Server' && index === 1 ? null : '9.0.0';
      files.push({ packageFile: ref.file, deps: [{
        depName: name, packageName: name, currentValue, datasource: 'docker',
        updates: newValue ? [{ newValue }] : [],
      }] });
      if (newValue) upgrades.push({
        packageName: name, packageFile: ref.file, currentValue, newValue, datasource: 'docker',
      });
    });
    if (upgrades.length) branches.push({ branchName: `fixture/${row.component}`, upgrades });
  }
  return { components, logs: [{ level: 30, report: { problems: [], repositories: {
    [manifest.repository]: { problems: [], packageFiles: { fixture: files }, branches },
  } } }] };
}

function test() {
  const toolResult = (command, output) => ({
    command, status: 'passed', stdout: output, stderr: '', output,
  });
  const tools = {
    helm: 'v3.20.2+g8fb76d6\n',
    yq: 'yq (https://github.com/mikefarah/yq/) version v4.53.2\n',
    bash: 'GNU bash, version 5.2.21\n',
  };
  assert.equal(checkTools('/unused', command => toolResult(command, tools[command])).length, 3);
  for (const command of Object.keys(tools)) {
    assert.throws(() => checkTools('/unused', name => name === command ?
      { ...toolResult(name, ''), status: 'failed', output: `spawnSync ${name} ENOENT` } :
      toolResult(name, tools[name])), error => {
      assert.match(error.message, new RegExp(command === 'bash' ? 'Bash' : command === 'helm' ? 'Helm' : 'yq'));
      assert.match(error.message, /ENOENT/);
      assert.equal(error.tools.length, 3);
      return true;
    });
  }
  for (const [command, version] of [['helm', 'v4.0.0'], ['yq', 'yq 3.4.3'], ['yq', 'yq (https://github.com/mikefarah/yq/) version v3.4.0']]) {
    assert.throws(() => checkTools('/unused', name =>
      toolResult(name, name === command ? version : tools[name])), /required; received/);
  }
  const warning = "warning: unable to access '/home/ubuntu/.config/git/ignore': Permission denied\n";
  const commandResult = run(process.execPath, ['-e', 'process.stdout.write("clean"); process.stderr.write("warning");'], process.cwd());
  assert.equal(commandResult.stdout, 'clean');
  assert.equal(commandResult.stderr, 'warning');
  assert.equal(commandResult.output, 'cleanwarning');
  const checkoutResult = (args, stdout = '', status = 'passed') => ({
    status, stdout: args.includes('rev-parse') ? 'a'.repeat(40) + '\n' : stdout,
    stderr: warning, output: warning,
  });
  assert.equal(checkCheckout('/unused', 'a'.repeat(40), (command, args) => {
    assert(args.includes('core.excludesFile=/dev/null'));
    assert(args.includes('core.attributesFile=/dev/null'));
    return checkoutResult(args);
  }).length, 2);
  assert.throws(() => checkCheckout('/unused', 'b'.repeat(40), (command, args) => checkoutResult(args)), /does not match/);
  assert.throws(() => checkCheckout('/unused', 'a'.repeat(40), (command, args) => checkoutResult(args, ' M config.yaml\n')), /must be clean/);
  assert.throws(() => checkCheckout('/unused', 'a'.repeat(40), (command, args) =>
    checkoutResult(args, '', args.includes('status') ? 'failed' : 'passed')), /Cannot inspect/);
  assert.throws(() => checkCheckout('/unused', 'a'.repeat(40), (command, args) =>
    checkoutResult(args, '', 'failed')), /Cannot read/);
  const { components, logs } = fixture();
  const matrix = makeMatrix(components, logs);
  assert.equal(matrix.components.length, 14);
  assert(matrix.components.every(row => row.prEligible === false && row.validation.deployment === 'not-run'));
  const find = name => matrix.components.find(row => row.component === name);
  assert.equal(find('Agent Sandbox').status, 'candidate-unvalidated');
  assert.equal(find('Ray').status, 'blocked');
  assert.equal(find('OpenShell').status, 'blocked');
  assert.equal(find('pgvector').status, 'blocked');
  assert.equal(find('OpenVINO Model Server').status, 'blocked');
  assert.match(find('OpenVINO Model Server').proposals[0].reason, /missing updates/);

  const drift = structuredClone(components);
  drift.components[0].currentReferences[0].value = 'v1.0.9';
  assert.throws(() => makeMatrix(drift, logs), /Missing or changed/);
  const incomplete = structuredClone(components);
  incomplete.components.pop();
  assert.throws(() => makeMatrix(incomplete, logs), /coverage/);
  assert.throws(() => makeMatrix(components, [...logs, { level: 40 }]), /warnings/);
  const problems = structuredClone(logs);
  problems[0].report.problems = [{ message: 'lookup failed' }];
  assert.throws(() => makeMatrix(components, problems), /unsuccessful/);
  const partial = structuredClone(logs);
  partial[0].report.repositories[manifest.repository].branches.find(branch => branch.branchName === 'fixture/Agent Sandbox').upgrades.pop();
  assert.equal(makeMatrix(components, partial).components[0].status, 'blocked');
  const unsupported = structuredClone(logs);
  unsupported[0].report.repositories[manifest.repository].branches[0].upgrades[0].newValue = 'not-an-observed-candidate';
  assert.throws(() => makeMatrix(components, unsupported), /candidate evidence/);
  const noUpdates = structuredClone(logs);
  noUpdates[0].report.repositories[manifest.repository].branches = [];
  assert.equal(makeMatrix(components, noUpdates).components.find(row => row.component === 'LiteLLM').status, 'no-candidate');
  const calls = [];
  const passed = checkConfiguration('/unused', (command, args) => {
    calls.push([command, ...args]);
    return { command: [command, ...args].join(' '), status: 'passed', output: '' };
  });
  assert.equal(passed.status, 'passed');
  assert.equal(calls.filter(call => call[0] === 'helm' && call[1] === 'lint').length, 3);
  assert.equal(calls.filter(call => call[0] === 'helm' && call[1] === 'template').length, 3);
  assert(calls.some(call => call[0] === 'bash' && call[1] === '-n'));
  const failedChecks = checkConfiguration('/unused', (command, args) => ({
    command: [command, ...args].join(' '), status: command === 'helm' ? 'failed' : 'passed', output: 'test failure',
  }));
  assert.equal(failedChecks.status, 'failed');

  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'toolkit-matrix-test-'));
  try {
    fs.mkdirSync(path.join(root, 'roles/agent_sandbox/defaults'), { recursive: true });
    fs.writeFileSync(path.join(root, 'config.yaml'), 'agent_sandbox_version: "v1.0.10"\n');
    fs.writeFileSync(path.join(root, 'roles/agent_sandbox/defaults/main.yaml'), 'agent_sandbox_version: "v1.0.10"\n');
    applyProposal(root, 'Agent Sandbox', find('Agent Sandbox').proposals[0]);
    assert.equal(fs.readFileSync(path.join(root, 'config.yaml'), 'utf8'), 'agent_sandbox_version: "9.0.0"\n');
    assert.throws(() => applyProposal(root, 'Agent Sandbox', find('Agent Sandbox').proposals[0]), /drift/);
    writeMatrix(matrix, path.join(root, 'matrix'));
    assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'matrix.json'), 'utf8')).components.length, 14);
    assert.equal(fs.readFileSync(path.join(root, 'matrix.tsv'), 'utf8').trimEnd().split('\n').length, 15);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
  if (process.argv[2]) {
    const actualLogs = fs.readFileSync(process.argv[2], 'utf8').trim().split(/\r?\n/).map(line => JSON.parse(line));
    const actual = makeMatrix(componentReport(), actualLogs);
    assert.equal(actual.components.find(row => row.component === 'OpenVINO Model Server').status, 'blocked');
    assert.equal(actual.components.find(row => row.component === 'Langfuse').proposals.length, 2);
    assert.equal(actual.components.find(row => row.component === 'LiteLLM').status, 'no-candidate');
    assert.equal(actual.components.find(row => row.component === 'ClickHouse').proposals[0].changes[0].newValue, 'bitnamilegacy/clickhouse:25.7.5');
    if (process.argv[3]) writeMatrix(actual, process.argv[3]);
  }
  console.log('Upgrade matrix and candidate patch tests passed');
}

if (require.main === module) {
  try { test(); } catch (error) { console.error(error); process.exitCode = 1; }
}
module.exports = { componentReport };
