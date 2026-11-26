#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -f -- "$tmp/curl"; rmdir -- "$tmp"' EXIT

cat >"$tmp/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
for arg in "$@"; do
  [[ "$arg" != *"$RENOVATE_TOKEN"* ]] || exit 1
done
IFS= read -r authorization
[[ "$authorization" == "header = \"Authorization: Bearer $RENOVATE_TOKEN\"" ]]
while (($#)); do
  case "$1" in
    --output) output=$2; shift 2 ;;
    --url) url=$2; shift 2 ;;
    *) shift ;;
  esac
done
if [[ "$url" == https://api.github.com/user ]]; then
  printf '%s' '{"login":"test-bot","email":"private@example.com"}' >"$output"
  printf '%s' "${MOCK_USER_STATUS:-200}"
else
  if [[ -n "${MOCK_FORK_BODY:-}" ]]; then
    printf '%s' "$MOCK_FORK_BODY" >"$output"
  else
    printf '%s' '{"fork":true,"full_name":"test-bot/agent-toolkit","parent":{"full_name":"intel/agent-toolkit"},"permissions":{"push":true}}' >"$output"
  fi
  printf '%s' "${MOCK_FORK_STATUS:-200}"
fi
EOF
chmod +x "$tmp/curl"
export PATH="$tmp:$PATH" RENOVATE_TOKEN="test_token"

output=$(bash ci/check-pr-credential.sh)
[[ "$output" == *"PR credential GitHub account: test-bot"* ]]
[[ "$output" == *"parent: intel/agent-toolkit; push permission: true"* ]]
[[ "$output" != *"$RENOVATE_TOKEN"* && "$output" != *"private@example.com"* ]]

if MOCK_USER_STATUS=401 bash ci/check-pr-credential.sh >/dev/null 2>&1; then
  echo "Expected failed authentication to fail the check" >&2
  exit 1
fi
if MOCK_FORK_STATUS=404 bash ci/check-pr-credential.sh >/dev/null 2>&1; then
  echo "Expected a missing conventional fork to fail the check" >&2
  exit 1
fi
if MOCK_FORK_BODY='{"fork":false}' bash ci/check-pr-credential.sh >/dev/null 2>&1; then
  echo "Expected an unrelated repository to fail the check" >&2
  exit 1
fi
echo "PR credential diagnostic checks passed"
