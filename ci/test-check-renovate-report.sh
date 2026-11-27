#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
report=$(mktemp)
trap 'rm -f -- "$report"' EXIT
export RENOVATE_REPOSITORIES="example/one,example/two"

jq -e '
  (.gitAuthor | test("^.+ <[^@<> ]+@[^@<> ]+>$")) and
  any(.packageRules[];
    .matchDatasources == ["docker"] and
    .matchPackageNames == ["rayproject/ray"] and .enabled == false) and
  any(.packageRules[];
    .matchDatasources == ["docker"] and
    (.matchPackageNames | sort) == ["langfuse/langfuse", "langfuse/langfuse-worker"] and
    .groupName == "langfuse images") and
  .force.automerge == false and
  .force.vulnerabilityAlerts.enabled == false
' ci/renovate-config.json >/dev/null

jq -nc '{level:30,report:{repositories:{"example/one":{packageFiles:{helmv3:[{}]}},"example/two":{packageFiles:{regex:[{}]}}}}}' >"$report"
bash ci/check-renovate-report.sh "$report"

echo '{"level":40,"msg":"lookup failed"}' >>"$report"
if bash ci/check-renovate-report.sh "$report" >/dev/null 2>&1; then
  echo "Expected warning to fail the report check" >&2
  exit 1
fi

jq -nc '{level:30,report:{repositories:{"example/one":{packageFiles:{helmv3:[{}]}}}}}' >"$report"
if bash ci/check-renovate-report.sh "$report" >/dev/null 2>&1; then
  echo "Expected a missing repository to fail the report check" >&2
  exit 1
fi

jq -nc '{level:30,report:{repositories:{"example/one":{packageFiles:{helmv3:[{}]}},"example/two":{packageFiles:{}}}}}' >"$report"
if bash ci/check-renovate-report.sh "$report" >/dev/null 2>&1; then
  echo "Expected a repository with no extracted files to fail the report check" >&2
  exit 1
fi

export RENOVATE_REPOSITORIES="intel/agent-toolkit"
jq -nc '{level:30,report:{repositories:{"intel/agent-toolkit":{packageFiles:{helm:[{}]},branches:[{upgrades:[{packageName:"rayproject/ray"}]}]}}}}' >"$report"
if bash ci/check-renovate-report.sh "$report" >/dev/null 2>&1; then
  echo "Expected a Ray update proposal to fail the report check" >&2
  exit 1
fi

echo "Renovate report checks passed"
