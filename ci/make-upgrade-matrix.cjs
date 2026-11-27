'use strict';

const fs = require('node:fs');
const manifest = require('./toolkit-components.json');
const policy = require('./toolkit-upgrade-policy.json');

const normalize = value => value.replace(/^.*:/, '').replace(/^v/, '').replace(/-py(?:\d+)?$/, '');
const dependencyName = dep => dep.packageName || dep.depName;
const currentTag = value => value.includes(':') ? value.slice(value.lastIndexOf(':') + 1) : value;

function makeMatrix(components, logs) {
  if (components.repository !== manifest.repository || !/^[a-f0-9]{40}$/.test(components.sourceCommit)) {
    throw new Error('Invalid component repository or source commit');
  }
  if (logs.some(entry => entry.level >= 40)) throw new Error('Discovery log contains warnings/errors');
  const report = logs.filter(entry => entry.report).at(-1)?.report;
  const repository = report?.repositories?.[manifest.repository];
  if (!repository?.packageFiles || report.problems?.length || repository.problems?.length) {
    throw new Error('Missing or unsuccessful Renovate repository report');
  }
  if (components.components.length !== manifest.components.length ||
      new Set(components.components.map(row => row.component)).size !== manifest.components.length) {
    throw new Error('Component coverage mismatch');
  }
  const dependencies = Object.entries(repository.packageFiles).flatMap(([manager, files]) =>
    files.flatMap(file => file.deps.map(dep => ({ ...dep, manager, file: file.packageFile }))));
  const rows = manifest.components.map(definition => {
    const observed = components.components.find(row => row.component === definition.name);
    const rules = policy[definition.name];
    if (!observed || observed.status !== 'ok' || !observed.version ||
        observed.currentReferences.length !== definition.refs.length || rules.dependencies.length !== definition.refs.length) {
      throw new Error(`Incomplete component or policy: ${definition.name}`);
    }
    const references = observed.currentReferences.map((ref, index) => {
      if (ref.file !== definition.refs[index].file || !ref.value) throw new Error(`Reference mismatch: ${definition.name}`);
      const depName = rules.dependencies[index];
      const matches = depName === null ? [] : dependencies.filter(dep =>
        dep.file === ref.file && dependencyName(dep) === depName && dep.currentValue === currentTag(ref.value));
      if (depName !== null && !matches.length) {
        throw new Error(`Missing or changed Renovate extraction: ${definition.name}: ${ref.file}: ${ref.value}`);
      }
      return { ...ref, dependency: depName, evidence: matches.map(dep => ({
        manager: dep.manager, datasource: dep.datasource, skipReason: dep.skipReason || null,
        candidates: (dep.updates || []).map(update => update.newValue),
      })) };
    });
    if (!rules.blocked && new Set(references.map(ref => normalize(ref.value))).size !== 1) {
      throw new Error(`Current coordinated versions disagree: ${definition.name}`);
    }
    const proposals = [];
    for (const branch of repository.branches || []) {
      const upgrades = (branch.upgrades || []).filter(upgrade => references.some(ref =>
        ref.file === upgrade.packageFile && ref.dependency === dependencyName(upgrade)));
      if (!upgrades.length) continue;
      const changes = references.map((ref, index) => {
        const matches = upgrades.filter(upgrade => upgrade.packageFile === ref.file &&
          dependencyName(upgrade) === ref.dependency && upgrade.currentValue === currentTag(ref.value));
        if (matches.length > 1) throw new Error(`Ambiguous proposal: ${definition.name}`);
        const upgrade = matches[0];
        if (!upgrade) return null;
        if (typeof upgrade.newValue !== 'string' || !upgrade.newValue ||
            !ref.evidence.some(dep => dep.candidates.includes(upgrade.newValue))) {
          throw new Error(`Proposal has no extracted candidate evidence: ${definition.name}`);
        }
        return { reference: index, file: ref.file, dependency: ref.dependency,
          currentValue: ref.value, newValue: ref.value.includes(':') ?
            `${ref.value.slice(0, ref.value.lastIndexOf(':') + 1)}${upgrade.newValue}` : upgrade.newValue,
          datasource: upgrade.datasource };
      }).filter(Boolean);
      const complete = changes.length === references.length &&
        new Set(changes.map(change => normalize(change.newValue))).size === 1;
      proposals.push({
        branch: branch.branchName,
        status: rules.blocked || !complete ? 'blocked' : 'candidate-unvalidated',
        reason: rules.blocked || (!complete ? 'Coordinated references are missing updates or target versions disagree.' :
          'Candidate lookup only; artifact digest, static, security and runtime validation still required.'),
        changes,
      });
    }
    return {
      component: definition.name, currentReferences: references,
      latestUpstream: observed.version, upstreamUrl: observed.url,
      status: rules.blocked ? 'blocked' : proposals.length ? (
        proposals.some(proposal => proposal.status === 'candidate-unvalidated') ? 'candidate-unvalidated' : 'blocked'
      ) : 'no-candidate',
      reason: rules.blocked || (proposals.length ? observed.note :
        'No update candidate returned under the current registry/channel/versioning policy; this does not prove current or latest artifact availability.'),
      proposals, requiredValidation: rules.requiredValidation,
      validation: { static: 'not-run', artifactDigests: 'not-run', security: 'not-run', deployment: 'not-run', smoke: 'not-run', rollback: 'not-run' },
      prEligible: false,
    };
  });
  return {
    repository: components.repository, sourceCommit: components.sourceCommit,
    generatedAt: new Date().toISOString(), discoveryGeneratedAt: components.generatedAt,
    evidence: 'Registry/release lookup candidates, not image pulls, chart downloads or digest verification.',
    components: rows,
  };
}

function writeMatrix(matrix, prefix) {
  fs.writeFileSync(`${prefix}.json`, `${JSON.stringify(matrix, null, 2)}\n`);
  const cell = value => String(value ?? '').replace(/[\t\r\n]/g, ' ');
  const table = [['component', 'current_references', 'latest_upstream', 'lookup_candidates', 'proposed_targets', 'status', 'static_validation', 'deployment_validation', 'reason', 'required_validation', 'validation_source', 'artifact_verification', 'image_vulnerability_scan']];
  for (const row of matrix.components) {
    table.push([row.component, row.currentReferences.map(ref => `${ref.file}: ${ref.value}`).join('; '),
      row.latestUpstream, row.currentReferences.flatMap(ref => ref.evidence.flatMap(dep =>
        dep.candidates.map(candidate => `${ref.dependency}: ${candidate}`))).join('; '),
      row.proposals.map(proposal => `${proposal.branch} [${proposal.status}]: ${proposal.changes.map(change => change.newValue).join(', ')}`).join('; '),
      row.status, row.validation.static, row.validation.deployment, row.reason, row.requiredValidation.join('; '),
      matrix.validationSource ? `${matrix.validationSource.repository}@${matrix.validationSource.commit} (${matrix.validationSource.mode})` : 'not-run',
      row.validation.artifactDigests, row.validation.security]);
  }
  fs.writeFileSync(`${prefix}.tsv`, `${table.map(row => row.map(cell).join('\t')).join('\n')}\n`);
}

module.exports = { makeMatrix, writeMatrix };
if (require.main === module) {
  try {
    if (process.argv.length !== 5) throw new Error('Usage: node make-upgrade-matrix.cjs <components.json> <discovery.jsonl> <output-prefix>');
    const components = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    const logs = fs.readFileSync(process.argv[3], 'utf8').trim().split(/\r?\n/).map(line => JSON.parse(line));
    const matrix = makeMatrix(components, logs);
    writeMatrix(matrix, process.argv[4]);
    for (const row of matrix.components) console.log(`${row.component}: ${row.status}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
