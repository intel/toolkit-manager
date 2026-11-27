#!/usr/bin/env bash
set -euo pipefail

report=$1
if ! jq -e -s '
  (map(select(has("report"))) | last).report.repositories["intel/agent-toolkit"].branches as $branches |
  ($branches | type == "array" and length == 1) and
  ($branches[0].upgrades | type == "array" and length == 2) and
  ([$branches[0].upgrades[].packageFile] | sort) ==
    ["config.yaml", "roles/agent_sandbox/defaults/main.yaml"] and
  all($branches[0].upgrades[];
    .packageName == "kubernetes-sigs/agent-sandbox" and
    .currentValue == "v1.0.10" and .newValue == "v1.0.12" and
    .updateType == "patch")
' "$report" >/dev/null; then
  echo "Pilot report does not match the approved Agent Sandbox patch and both expected files." >&2
  exit 1
fi
echo "Pilot report matches the approved Agent Sandbox patch in both expected files."
