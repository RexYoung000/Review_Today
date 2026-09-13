#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ "$#" -eq 0 ]; then set -- DictationContractTests LearningInputContractTests SessionDeletionContractTests; fi
exec python3 tests/mac/run-contracts.py "$@"
