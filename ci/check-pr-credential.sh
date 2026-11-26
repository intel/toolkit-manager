#!/usr/bin/env bash
set -euo pipefail
set +x

: "${RENOVATE_TOKEN:?RENOVATE_TOKEN must be set}"
if [[ ! "$RENOVATE_TOKEN" =~ ^[[:alnum:]_]+$ ]]; then
  echo "Cannot check PR credential: unexpected token format." >&2
  exit 1
fi
for command in curl node; do
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
if ! login=$(node -e '
  let data;
  try { data = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); }
  catch { process.exit(1); }
  if (!data || typeof data !== "object") process.exit(1);
  if (typeof data.login !== "string" || !/^[A-Za-z0-9-]+$/.test(data.login)) process.exit(1);
  console.log(data.login);
' "$response"); then
  echo "GitHub returned an invalid account identity." >&2
  exit 1
fi
echo "PR credential GitHub account: $login"

fork='nishi252003/enterprise-agent-toolkit'
if [[ "${login,,}" != 'nishi252003' ]]; then
  echo "The configured fork is not owned by the credential account; review fork selection." >&2
  exit 1
fi
status=$(request "https://api.github.com/repos/$fork")
if [[ "$status" != 200 ]]; then
  echo "Fork $fork: HTTP $status." >&2
  exit 1
fi
if ! node -e '
  let data;
  try { data = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); }
  catch { process.exit(1); }
  if (!data || typeof data !== "object") process.exit(1);
  if (data.fork !== true || data.parent?.full_name !== "intel/agent-toolkit" ||
      typeof data.full_name !== "string" || data.full_name.toLowerCase() !== process.argv[2].toLowerCase()) process.exit(1);
  const push = typeof data.permissions?.push === "boolean" ? data.permissions.push : "unknown";
  console.log(`Fork: ${data.full_name}; parent: ${data.parent.full_name}; push permission: ${push}`);
  if (push !== true) process.exit(1);
' "$response" "$fork"; then
  echo "Fork identity or push permission could not be verified." >&2
  exit 1
fi
