#!/usr/bin/env bash
set -euo pipefail
set +x

: "${RENOVATE_TOKEN:?RENOVATE_TOKEN must be set}"
if [[ ! "$RENOVATE_TOKEN" =~ ^[[:alnum:]_]+$ ]]; then
  echo "Cannot check PR credential: unexpected token format." >&2
  exit 1
fi
for command in curl jq; do
  if ! command -v "$command" >/dev/null; then
    echo "Cannot check PR credential: $command is not installed." >&2
    exit 1
  fi
done

umask 077
response=$(mktemp)
trap 'rm -f -- "$response"' EXIT

request() {
  local status
  if ! status=$(printf 'header = "Authorization: Bearer %s"\n' "$RENOVATE_TOKEN" |
    curl --disable --config - --silent --show-error --max-time 30 \
      --header 'Accept: application/vnd.github+json' \
      --output "$response" --write-out '%{http_code}' \
      --url "$1"); then
    echo "GitHub API request failed." >&2
    return 1
  fi
  printf '%s' "$status"
}

status=$(request 'https://api.github.com/user')
if [[ "$status" != 200 ]]; then
  echo "GitHub credential identity check failed: HTTP $status." >&2
  exit 1
fi
if ! login=$(jq -er '.login | select(type == "string" and test("^[A-Za-z0-9-]+$"))' "$response"); then
  echo "GitHub returned an invalid account identity." >&2
  exit 1
fi
echo "PR credential GitHub account: $login"

status=$(request "https://api.github.com/repos/$login/agent-toolkit")
if [[ "$status" != 200 ]]; then
  echo "Conventional account fork $login/agent-toolkit: HTTP $status."
  echo "This does not check renamed forks or forks owned by organizations."
  exit 1
fi
if ! jq -er '
  select(.fork == true and .parent.full_name == "intel/agent-toolkit") |
  "Fork: \(.full_name); parent: \(.parent.full_name); push permission: \(.permissions.push)"
' "$response"; then
  echo "The conventional account repository is not a verified Agent Toolkit fork." >&2
  exit 1
fi
