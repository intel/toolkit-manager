#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
report=$(mktemp)
output=$(mktemp)
expected=$(mktemp)
trap 'rm -f -- "$report" "$output" "$expected"' EXIT

jq -nc '{level:30,report:{repositories:{"example/repo":{packageFiles:{
  "docker-compose":[{packageFile:"docker-compose.yml",deps:[
    {depName:"example/image",currentValue:"1.0",updates:[{newValue:"1.1"}]},
    {packageName:"example/floating",currentValue:"latest",skipReason:"invalid-value",updates:[]}
  ]}]
}}}}}' >"$report"
bash ci/summarize-renovate-report.sh "$report" "$output"
printf 'repository\tmanager\tfile\tdependency\tcurrent\tupdates\tskip_reason\nexample/repo\tdocker-compose\tdocker-compose.yml\texample/image\t1.0\t1.1\t\nexample/repo\tdocker-compose\tdocker-compose.yml\texample/floating\tlatest\t\tinvalid-value\n' >"$expected"
diff -u "$expected" "$output"
printf '%s\n' '{"level":30,"msg":"no report"}' >"$report"
if bash ci/summarize-renovate-report.sh "$report" "$output" >/dev/null 2>&1; then
  echo "Expected missing report to fail" >&2
  exit 1
fi
echo "Renovate inventory summary checks passed"
