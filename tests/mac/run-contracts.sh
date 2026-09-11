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
for test in BrandMaterialContractTests AnswerDocumentContractTests AppRuntimeContractTests InteractionFocusTests AgentServiceMonitorContractTests LearningInputContractTests ConversationReplayTests LearningMemoryContractTests SessionDeletionContractTests SessionListSelectionTests SessionOrganizationContractTests IndependentSessionContractTests LibraryManagementContractTests KnowledgeDeckNavigationTests KnowledgeIngestionTests; do
  test_sources=("tests/mac/$test.swift")
  if [[ "$test" == KnowledgeIngestionTests ]]; then test_sources+=(tests/mac/KnowledgeIngestionFixture.swift); fi
  xcrun swiftc -parse-as-library -D DEBUG -swift-version 5 -default-isolation MainActor \
    "${sources[@]}" "${test_sources[@]}" -o "$build_dir/$test"
  "$build_dir/$test"
done
python3 tests/mac/run-sse.py "$build_dir/ConversationReplayTests"
printf 'Isolated contract executables: %s\n' "$build_dir"
