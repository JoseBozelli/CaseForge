#!/usr/bin/env bash
# Apply automatic fixes: lint autofixes, then formatting.
# Always review `git diff` afterwards: an autofix can hide a real mistake.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run ruff check --fix .
uv run ruff format .
