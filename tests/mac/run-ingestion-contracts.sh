#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
folder=output/ingestion-tests
mkdir -p "$folder"
sources=()
for file in Review_Today/*.swift; do
  case "$file" in */Review_TodayApp.swift) ;; *) sources+=("$file");; esac
done
tests/mac/swift-with-fsrs.py -parse-as-library -D DEBUG -swift-version 5 -default-isolation MainActor \
  "${sources[@]}" tests/mac/KnowledgeIngestionFixture.swift tests/mac/KnowledgeIngestionTests.swift -o "$folder/contracts"
"$folder/contracts"
