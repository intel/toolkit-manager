#!/usr/bin/env bash
set -euo pipefail
set +x

: "${RENOVATE_TOKEN:?RENOVATE_TOKEN must be set}"
if [[ ! "$RENOVATE_TOKEN" =~ ^[[:alnum:]_]+$ ]]; then
  echo "Cannot verify pilot PR: unexpected token format." >&2
  exit 1
fi
for command in curl node; do
  if ! command -v "$command" >/dev/null; then
    echo "Cannot verify pilot PR: $command is not installed." >&2
    exit 1
  fi
done

umask 077
response=$(mktemp)
trap 'rm -f -- "$response"' EXIT
if ! status=$(printf 'header = "Authorization: Bearer %s"\n' "$RENOVATE_TOKEN" |
  curl --disable --config - --silent --show-error --max-time 30 \
    --header 'Accept: application/vnd.github+json' \
    --output "$response" --write-out '%{http_code}' \
    --url 'https://api.github.com/repos/intel/agent-toolkit/pulls?state=open&head=nishi252003%3Arenovate-agent-sandbox-pilot%2Fagent-sandbox-version&base=main'); then
  echo "Pilot PR lookup failed." >&2
  exit 1
fi
if [[ "$status" != 200 ]]; then
  echo "Pilot PR lookup failed: HTTP $status." >&2
  exit 1
fi
if ! node -e '
  let pulls;
  try { pulls = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); }
  catch { process.exit(1); }
  if (!Array.isArray(pulls) || pulls.length !== 1) process.exit(1);
  const pr = pulls[0];
  if (pr?.state !== "open" || pr.base?.ref !== "main" ||
      pr.base?.repo?.full_name !== "intel/agent-toolkit" ||
      pr.head?.repo?.full_name !== "nishi252003/enterprise-agent-toolkit" ||
      pr.head?.ref !== "renovate-agent-sandbox-pilot/agent-sandbox-version" ||
      !Number.isSafeInteger(pr.number) || pr.number <= 0 ||
      pr.html_url !== `https://github.com/intel/agent-toolkit/pull/${pr.number}`) process.exit(1);
  console.log(`Verified open pilot PR: ${pr.html_url}`);
' "$response"; then
  echo "No unique open PR from the approved pilot branch was verified; inspect GitHub and the Renovate log." >&2
  exit 1
fi
