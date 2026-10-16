#!/usr/bin/env bash
# Apply automatic fixes: lint autofixes, then formatting.
# Remaining lint problems are reported here and enforced by scripts/check.sh.
# Always review `git status` / `git diff` afterwards: an autofix can hide a real mistake.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run ruff check --fix --exit-zero .
uv run ruff format .
