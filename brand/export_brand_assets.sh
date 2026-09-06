#!/bin/zsh
set -euo pipefail
script_dir=${0:A:h}
project_root=${script_dir:h}
# The default pipeline uses the accepted original A. Historical V8 sources and
# its explicit packager remain archived; no V8 mascot/voice assets are rewritten.
swift "$script_dir/package_recall_assets.swift" "$project_root"
