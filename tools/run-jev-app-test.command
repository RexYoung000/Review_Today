#!/bin/bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
exec "$project_root/agent-service/.venv/bin/python" "$project_root/tools/run_jev_app_test.py"
