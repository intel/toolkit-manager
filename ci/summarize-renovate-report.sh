#!/usr/bin/env bash
set -euo pipefail

report_file=$1
output_file=$2

jq -er -s '
  (map(select(has("report"))) | last) as $entry |
  if ($entry.report.repositories | type) != "object" then
    error("Renovate report has no repositories")
  else
    ["repository", "manager", "file", "dependency", "current", "updates", "skip_reason"],
    ($entry.report.repositories | to_entries[] |
      .key as $repository |
      (.value.packageFiles // {} | to_entries[]) |
      .key as $manager |
      .value[] |
      .packageFile as $file |
      .deps[]? |
      [$repository, $manager, $file, (.depName // .packageName // ""),
       (.currentValue // ""), ([.updates[]?.newValue] | join(",")), (.skipReason // "")])
    | @tsv
  end
' "$report_file" >"$output_file"
