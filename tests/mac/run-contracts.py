#!/usr/bin/env python3
"""Compile app code once; run each native contract in a separate process.

Internal visibility is shared through @testable. Source locations continue to
refer to the checked-in test file, including tests that inspect UI contracts.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_TESTS = [
    "NavigationRenderContractTests", "NavigationDataContractTests", "UIPolishContractTests",
    "BrandMaterialContractTests", "AnswerDocumentContractTests", "AppRuntimeContractTests",
    "InteractionFocusTests", "AgentServiceMonitorContractTests", "LearningInputContractTests",
    "ConversationReplayTests", "LearningMemoryContractTests", "SessionDeletionContractTests",
    "SessionListSelectionTests", "SessionOrganizationContractTests", "IndependentSessionContractTests",
    "LibraryManagementContractTests", "KnowledgeDeckNavigationTests", "KnowledgeIngestionTests",
    "DictationContractTests", "TopicCaptureContractTests", "LearningGoalContinuityTests", "ReviewFlowContractTests", "ReviewControllerContractTests", "ReviewMigrationContractTests",
]
names = sys.argv[1:] or DEFAULT_TESTS
for name in names:
    if not name.isidentifier() or not (ROOT / "tests/mac" / f"{name}.swift").is_file():
        raise SystemExit(f"Unknown contract: {name}")

build = pathlib.Path(tempfile.mkdtemp(prefix="review-today-shared-contracts.", dir="/tmp"))
print(f"Isolated contract directory: {build}", flush=True)
flags = ["-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor", "-enable-upcoming-feature", "MemberImportVisibility"]
fsrs_sources = [str(p) for p in sorted((ROOT / "Vendor/SwiftFSRS/Sources").rglob("*.swift"))]
subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-swift-version", "5", "-emit-library", "-emit-module", "-module-name", "FSRS", "-emit-module-path", str(build / "FSRS.swiftmodule"), *fsrs_sources, "-o", str(build / "libFSRS.dylib")], check=True)
flags += ["-I", str(build), "-L", str(build), "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(build)]
sources = [str(p) for p in sorted((ROOT / "Review_Today").glob("*.swift")) if p.name != "Review_TodayApp.swift"]
subprocess.run([
    "xcrun", "swiftc", *flags, "-enable-testing", "-emit-library", "-emit-module",
    "-module-name", "ReviewTodayContractSupport", "-emit-module-path",
    str(build / "ReviewTodayContractSupport.swiftmodule"), *sources,
    "-o", str(build / "libReviewTodayContractSupport.dylib"),
], check=True, cwd=ROOT)

for name in names:
    paths = [ROOT / "tests/mac" / f"{name}.swift"]
    if name == "KnowledgeIngestionTests":
        paths.append(ROOT / "tests/mac/KnowledgeIngestionFixture.swift")
    copies = []
    for path in paths:
        target = build / path.name
        target.write_text(
            "@testable import ReviewTodayContractSupport\n"
            + "#sourceLocation(file: " + json.dumps(str(path), ensure_ascii=False) + ", line: 1)\n"
            + path.read_text()
        )
        copies.append(str(target))
    subprocess.run([
        "xcrun", "swiftc", *flags, "-I", str(build), "-L", str(build),
        "-lReviewTodayContractSupport", "-Xlinker", "-rpath", "-Xlinker", str(build),
        *copies, "-o", str(build / name),
    ], check=True, cwd=ROOT)
    subprocess.run([str(build / name)], check=True, cwd=ROOT)
    print(f"PASS executable: {name}", flush=True)

if "ConversationReplayTests" in names:
    subprocess.run(["python3", str(ROOT / "tests/mac/run-sse.py"), str(build / "ConversationReplayTests")], check=True, cwd=ROOT)
print(f"All selected contracts complete: {build}", flush=True)
