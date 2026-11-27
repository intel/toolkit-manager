#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
config=$(mktemp)
report=$(mktemp)
trap 'rm -f -- "$config" "$report"' EXIT

bash ci/make-pilot-config.sh ci/renovate-config.json "$config"
jq -e '
  .force.enabledManagers == ["custom.regex"] and
  .force.automerge == false and .force.vulnerabilityAlerts.enabled == false and
  .force.dependencyDashboard.enabled == false and
  .force.dependencyDashboard.title == "Agent Sandbox Pilot Dependency Dashboard" and
  .force.pruneStaleBranches == false and
  .force.branchPrefix == "renovate-agent-sandbox-pilot/" and
  .force.prConcurrentLimit == 1 and
  .force.packageRules[0].matchPackageNames == ["!kubernetes-sigs/agent-sandbox"] and
  .force.packageRules[0].enabled == false and
  .force.packageRules[1].allowedVersions == "=1.0.12"
' "$config" >/dev/null

jq -nc '
  {level:30,report:{repositories:{"intel/agent-toolkit":{
    packageFiles:{"custom.regex":[{}]},
    branches:[{upgrades:[
      {packageName:"kubernetes-sigs/agent-sandbox",packageFile:"config.yaml",currentValue:"v1.0.10",newValue:"v1.0.12",updateType:"patch"},
      {packageName:"kubernetes-sigs/agent-sandbox",packageFile:"roles/agent_sandbox/defaults/main.yaml",currentValue:"v1.0.10",newValue:"v1.0.12",updateType:"patch"}
    ]}]
  }}}}
' >"$report"
RENOVATE_REPOSITORIES=intel/agent-toolkit bash ci/check-renovate-report.sh "$report"
bash ci/check-pilot-report.sh "$report"

jq '.report.repositories["intel/agent-toolkit"].branches[0].upgrades[0].newValue = "v1.0.13"' "$report" >"$config"
if bash ci/check-pilot-report.sh "$config" >/dev/null 2>&1; then
  echo "Expected unexpected version to fail" >&2
  exit 1
fi
jq '.report.repositories["intel/agent-toolkit"].branches += [{upgrades:[{packageName:"other"}]}]' "$report" >"$config"
if bash ci/check-pilot-report.sh "$config" >/dev/null 2>&1; then
  echo "Expected extra proposal to fail" >&2
  exit 1
fi
jq 'del(.report.repositories["intel/agent-toolkit"].branches[0].upgrades[1])' "$report" >"$config"
if bash ci/check-pilot-report.sh "$config" >/dev/null 2>&1; then
  echo "Expected missing version reference to fail" >&2
  exit 1
fi
echo "Pilot checks passed"
