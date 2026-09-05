#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
migration_dir="$(mktemp -d /tmp/review-today-migration.XXXXXX)"
git archive e89a85c Review_Today | tar -x -C "$migration_dir"
old_sources=(); new_sources=()
for file in "$migration_dir"/Review_Today/*.swift; do
  case "$file" in */Review_TodayApp.swift) ;; *) old_sources+=("$file");; esac
done
for file in Review_Today/*.swift; do
  case "$file" in */Review_TodayApp.swift) ;; *) new_sources+=("$file");; esac
done
xcrun swiftc -parse-as-library -D DEBUG -swift-version 5 -default-isolation MainActor "${old_sources[@]}" tests/mac/ModelMigrationTests.swift -o "$migration_dir/seed"
"$migration_dir/seed" seed "$migration_dir/test.store"
xcrun swiftc -parse-as-library -D DEBUG -D NEW_SCHEMA -swift-version 5 -default-isolation MainActor "${new_sources[@]}" tests/mac/ModelMigrationTests.swift -o "$migration_dir/check"
"$migration_dir/check" check "$migration_dir/test.store"
printf 'Isolated migration fixture: %s\n' "$migration_dir"
