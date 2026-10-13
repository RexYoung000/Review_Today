"""Compile the baseline probe against the current isolated native support build.

First run tests/mac/run-contracts.py LearningMemoryContractTests
SessionDeletionContractTests, then pass its printed build directory here.
Rebuild support after source changes; do not point at the daily App.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--support-dir", type=Path, required=True)
args = parser.parse_args()
support = args.support_dir.resolve()
for name in ("ReviewTodayContractSupport.swiftmodule", "libReviewTodayContractSupport.dylib", "FSRS.swiftmodule", "libFSRS.dylib"):
    if not (support / name).is_file():
        raise SystemExit("Missing native support build: " + name)
with tempfile.TemporaryDirectory(prefix="review-today-memory-native-replay-") as directory:
    target = Path(directory) / "LearningMemoryInspection"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5",
                    "-default-isolation", "MainActor", "-enable-upcoming-feature", "MemberImportVisibility",
                    "-I", str(support), "-L", str(support), "-lFSRS", "-lReviewTodayContractSupport",
                    "-Xlinker", "-rpath", "-Xlinker", str(support),
                    str(Path(__file__).with_name("LearningMemoryInspection.swift")), "-o", str(target)], check=True)
    subprocess.run([str(target)], check=True)
