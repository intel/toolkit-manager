#!/usr/bin/env bash
set -euo pipefail

input=$1
output=$2
jq '
  .force.enabledManagers = ["custom.regex"] |
  .force.packageRules = [
    {"matchPackageNames": ["!kubernetes-sigs/agent-sandbox"], "enabled": false},
    {"matchPackageNames": ["kubernetes-sigs/agent-sandbox"], "groupName": "agent sandbox version",
     "allowedVersions": "=1.0.12"}
  ] |
  .force.dependencyDashboard = {"enabled": false, "title": "Agent Sandbox Pilot Dependency Dashboard"} |
  .force.pruneStaleBranches = false |
  .force.branchPrefix = "renovate-agent-sandbox-pilot/" |
  .force.prConcurrentLimit = 1
' "$input" >"$output"
