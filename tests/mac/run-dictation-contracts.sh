#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
build_dir="$(mktemp -d /tmp/review-today-contracts.XXXXXX)"
sources=()
for file in Review_Today/*.swift; do
  case "$file" in
    */Review_TodayApp.swift) ;;
    *) sources+=("$file") ;;
  esac
done
tests=("$@")
if [ ${#tests[@]} -eq 0 ]; then tests=(DictationContractTests LearningInputContractTests SessionDeletionContractTests); fi
for test in "${tests[@]}"; do
  xcrun swiftc -parse-as-library -D DEBUG -swift-version 5 -default-isolation MainActor \
    "${sources[@]}" "tests/mac/$test.swift" -o "$build_dir/$test"
  "$build_dir/$test"
done

printf 'Isolated contract executables: %s\n' "$build_dir"
