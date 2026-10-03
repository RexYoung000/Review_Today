#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ "$#" -eq 0 ]; then set -- DictationContractTests DictationSurfaceContractTests LearningInputContractTests UIPolishContractTests SessionDeletionContractTests; fi
exec python3 tests/mac/run-contracts.py "$@"
