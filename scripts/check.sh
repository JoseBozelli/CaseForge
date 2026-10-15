#!/usr/bin/env bash
# Local quality gate. Fails on lint errors, test failures, any configured Git
# remote, or an unignored secrets file.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -n "$(git remote)" ]; then
  echo "ERROR: Git remote configured; the repository must remain local-only." >&2
  exit 1
fi
echo "OK: no Git remotes"

if ! git check-ignore -q .secrets; then
  echo "ERROR: .secrets is not ignored by Git." >&2
  exit 1
fi
echo "OK: .secrets ignored"

uv run ruff check .
uv run ruff format --check .
uv run python -m pytest