#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
test_dir="$(mktemp -d /tmp/review-today-python-tests.XXXXXX)"
export REVIEW_TODAY_HARNESS_DB="$test_dir/checkpoints.sqlite3"
export OPENAI_API_KEY=''
export DEEPSEEK_API_KEY=''
export REVIEW_TODAY_LLM_PROVIDER='openai_compatible'
python_bin="${REVIEW_TODAY_TEST_PYTHON:-.venv/bin/python}"
"$python_bin" -m unittest discover -s tests -v
printf 'Isolated test database: %s\n' "$test_dir"
