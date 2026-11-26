#!/usr/bin/env bash
set -euo pipefail
set +x

: "${RENOVATE_TOKEN:?RENOVATE_TOKEN must be set}"
: "${RENOVATE_REPOSITORIES:?RENOVATE_REPOSITORIES must be set}"

if [[ ! "$RENOVATE_TOKEN" =~ ^[[:alnum:]_]+$ ]]; then
  echo "Cannot diagnose alert access: the token has an unexpected format." >&2
  exit 1
fi
if ! command -v curl >/dev/null; then
  echo "Cannot diagnose alert access: curl is not installed." >&2
  exit 1
fi

umask 077
headers=$(mktemp)
trap 'rm -f -- "$headers"' EXIT
IFS=',' read -r -a repositories <<< "$RENOVATE_REPOSITORIES"
for repository in "${repositories[@]}"; do
  if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    echo "Cannot diagnose alert access: invalid repository name." >&2
    exit 1
  fi
  if ! status=$(printf 'header = "Authorization: Bearer %s"\n' "$RENOVATE_TOKEN" |
    curl --disable --config - --silent --show-error --max-time 30 \
      --header 'Accept: application/vnd.github+json' \
      --dump-header "$headers" --output /dev/null --write-out '%{http_code}' \
      --url "https://api.github.com/repos/${repository}/dependabot/alerts?state=open&direction=asc&per_page=100"); then
    echo "Alert access diagnostic request failed for $repository." >&2
    exit 1
  fi
  echo "Dependabot alerts API for $repository: HTTP $status"
  if grep -iq '^x-github-sso:.*required' "$headers"; then
    echo "GitHub indicates that SSO authorization is required."
  fi
done
