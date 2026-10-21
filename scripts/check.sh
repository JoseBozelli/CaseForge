#!/usr/bin/env bash
# Local quality gate. Fails on lint errors, test failures, any Git remote other
# than the approved one, or an unignored secrets file.
set -euo pipefail
cd "$(dirname "$0")/.."

APPROVED_REMOTE="${CASEFORGE_APPROVED_REMOTE:-https://github.com/JoseBozelli/CaseForge.git}"
remotes="$(git remote)"
if [ -n "$remotes" ]; then
  for name in $remotes; do
    for url in $(git remote get-url --all "$name") $(git remote get-url --push --all "$name"); do
      if [ "$url" != "$APPROVED_REMOTE" ]; then
        echo "ERROR: remote '$name' points to $url; only $APPROVED_REMOTE is approved." >&2
        exit 1
      fi
    done
  done
  echo "OK: only the approved remote is configured"
else
  echo "OK: no Git remotes"
fi

if ! git check-ignore -q .secrets; then
  echo "ERROR: .secrets is not ignored by Git." >&2
  exit 1
fi
echo "OK: .secrets ignored"

uv run ruff check .
uv run ruff format --check .
uv run python -m pytest
