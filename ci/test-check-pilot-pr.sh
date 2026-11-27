#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -f -- "$tmp/curl"; rmdir -- "$tmp"' EXIT

cat >"$tmp/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
for arg in "$@"; do [[ "$arg" != *"$RENOVATE_TOKEN"* ]] || exit 1; done
IFS= read -r authorization
[[ "$authorization" == "header = \"Authorization: Bearer $RENOVATE_TOKEN\"" ]]
while (($#)); do
  case "$1" in
    --output) output=$2; shift 2 ;;
    --url) url=$2; shift 2 ;;
    *) shift ;;
  esac
done
[[ "$url" == 'https://api.github.com/repos/intel/agent-toolkit/pulls?state=open&head=nishi252003%3Arenovate-agent-sandbox-pilot%2Fagent-sandbox-version&base=main' ]]
printf '%s' "${MOCK_BODY:-[]}" >"$output"
printf '%s' "${MOCK_STATUS:-200}"
EOF
chmod +x "$tmp/curl"
export PATH="$tmp:$PATH" RENOVATE_TOKEN=test_token
valid='[{"number":99,"state":"open","html_url":"https://github.com/intel/agent-toolkit/pull/99","base":{"ref":"main","repo":{"full_name":"intel/agent-toolkit"}},"head":{"ref":"renovate-agent-sandbox-pilot/agent-sandbox-version","repo":{"full_name":"nishi252003/enterprise-agent-toolkit"}}}]'
output=$(MOCK_BODY="$valid" bash ci/check-pilot-pr.sh)
[[ "$output" == *"https://github.com/intel/agent-toolkit/pull/99"* ]]
[[ "$output" != *"$RENOVATE_TOKEN"* ]]
if bash ci/check-pilot-pr.sh >/dev/null 2>&1; then
  echo "Expected no PR to fail" >&2
  exit 1
fi
if MOCK_BODY="$valid" MOCK_STATUS=403 bash ci/check-pilot-pr.sh >/dev/null 2>&1; then
  echo "Expected API failure to fail" >&2
  exit 1
fi
wrong=$(printf '%s' "$valid" | jq '.[0].head.repo.full_name = "someone/else"')
if MOCK_BODY="$wrong" bash ci/check-pilot-pr.sh >/dev/null 2>&1; then
  echo "Expected wrong fork to fail" >&2
  exit 1
fi
echo "Pilot PR verification checks passed"
