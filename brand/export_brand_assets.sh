#!/bin/zsh
set -euo pipefail
script_dir=${0:A:h}
project_root=${script_dir:h}
# Default: confirmed black/white native icon. Green originals remain archived.
python3 "$script_dir/package_confirmed_assets.py"
