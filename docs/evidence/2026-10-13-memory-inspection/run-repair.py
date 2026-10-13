"""Replay the preserved baseline fixture against a freshly built native module.

Only the same-title expectation changes; fixture identities are pinned to the
original captured report for a direct before/after comparison. No daily App.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--support-dir", type=Path, required=True)
args = parser.parse_args()
support = args.support_dir.resolve()
here = Path(__file__).resolve().parent
for name in ("ReviewTodayContractSupport.swiftmodule", "libReviewTodayContractSupport.dylib", "FSRS.swiftmodule", "libFSRS.dylib"):
    if not (support / name).is_file():
        raise SystemExit("Missing fresh native support build: " + name)
source = (here / "LearningMemoryInspection.swift").read_text()
baseline = json.loads((here / "native-baseline.json").read_text())
same_title = next(row for row in baseline["cases"] if row["case"] == "same_title_two_selected_cards")
newer = same_title["candidate_ids"][0]
older = same_title["missing_ids"][0]
replacements = {
    '/// Baseline inspection only: real native retrieval, synthetic in-memory records.':
        '/// Repair replay: real native retrieval, same synthetic in-memory scenarios.',
    'context.insert(first); context.insert(second); try context.save()':
        f'first.id = UUID(uuidString: "{older}")!; second.id = UUID(uuidString: "{newer}")!\n'
        '        context.insert(first); context.insert(second); try context.save()',
    'precondition(sameTitle.count == 1 && Set(ids(sameTitle)) != expected, "preserve the current gap as a baseline")':
        'precondition(sameTitle.count == 2 && Set(ids(sameTitle)) == expected, "both same-title selected cards survive")',
    '"phase": "gap_reproduced"': '"phase": "repair_passed"',
    '"read_only_native_baseline"': '"native_repair_replay"',
    '"date": "2026-10-13"': '"date": "2026-10-14"',
}
for old, new in replacements.items():
    if source.count(old) != 1:
        raise SystemExit("Preserved fixture changed; review required: " + old)
    source = source.replace(old, new)
with tempfile.TemporaryDirectory(prefix="review-today-memory-native-repair-") as directory:
    fixture = Path(directory) / "LearningMemoryInspection.swift"
    fixture.write_text(source)
    target = Path(directory) / "LearningMemoryInspection"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5",
                    "-default-isolation", "MainActor", "-enable-upcoming-feature", "MemberImportVisibility",
                    "-I", str(support), "-L", str(support), "-lFSRS", "-lReviewTodayContractSupport",
                    "-Xlinker", "-rpath", "-Xlinker", str(support), str(fixture), "-o", str(target)], check=True)
    subprocess.run([str(target)], check=True)
