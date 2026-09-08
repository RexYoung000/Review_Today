#!/bin/bash
# Same opt-in CLI in normal checkouts and isolated worktrees.
set -euo pipefail
cd "$(dirname "$0")"
python_bin="${REVIEW_TODAY_TEST_PYTHON:-.venv/bin/python}"
exec "$python_bin" -m evals "$@"
