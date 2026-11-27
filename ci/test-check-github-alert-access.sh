#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -f -- "$tmp/curl"; rmdir -- "$tmp"' EXIT

cat >"$tmp/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
for arg in "$@"; do
  if [[ "$arg" == *"$RENOVATE_TOKEN"* ]]; then
    echo "Token appeared in curl arguments" >&2
    exit 1
  fi
done
IFS= read -r authorization
[[ "$authorization" == "header = \"Authorization: Bearer $RENOVATE_TOKEN\"" ]]
while (($#)); do
  if [[ "$1" == "--dump-header" ]]; then
    headers=$2
    shift 2
  else
    shift
  fi
done
printf '%s\n' 'HTTP/2 403' >"$headers"
if [[ "${MOCK_SSO:-false}" == "true" ]]; then
  printf '%s\n' 'x-github-sso: required; url=https://example.com' >>"$headers"
fi
printf '%s' "${MOCK_STATUS:-403}"
EOF
chmod +x "$tmp/curl"
export PATH="$tmp:$PATH" RENOVATE_TOKEN="test_token" RENOVATE_REPOSITORIES="intel/agent-toolkit"

output=$(MOCK_SSO=true bash ci/check-github-alert-access.sh)
[[ "$output" == *"intel/agent-toolkit: HTTP 403"* ]]
[[ "$output" == *"SSO authorization is required"* ]]
[[ "$output" != *"$RENOVATE_TOKEN"* ]]
[[ "$output" != *"https://example.com"* ]]

output=$(MOCK_STATUS=200 bash ci/check-github-alert-access.sh)
[[ "$output" == *"intel/agent-toolkit: HTTP 200"* ]]
[[ "$output" != *"SSO authorization is required"* ]]

if RENOVATE_TOKEN='bad"token' bash ci/check-github-alert-access.sh >/dev/null 2>&1; then
  echo "Expected an invalid token format to fail" >&2
  exit 1
fi
if RENOVATE_REPOSITORIES='invalid repo/name' bash ci/check-github-alert-access.sh >/dev/null 2>&1; then
  echo "Expected an invalid repository name to fail" >&2
  exit 1
fi
echo "GitHub alert access diagnostic checks passed"
