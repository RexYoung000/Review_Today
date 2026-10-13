"""Replay the preserved inspection fixtures with the confirmed fixed expectations.

The actual service pages and stop receipt are unchanged. Compile against fresh
native support after the one-line production fix; baseline files stay intact.
"""
import argparse
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
        raise SystemExit("Missing fresh native support: " + name)
edits = {
    "MemoryInvalidationInspection": [
        ('let expectedCurrent = state == "streaming" ? "interrupted" : "recovering"', 'let expectedCurrent = "interrupted"', 1),
        ('"capture the current behavior, including the gap"', '"confirmed immediate interruption"', 1),
        ('f.response.responseState == "recovering"', 'f.response.responseState == "interrupted"', 3),
        ('"gap_reproduced": state == "recovering"', '"gap_reproduced": false', 1),
        ('"gap_reproduced": true', '"gap_reproduced": false', 3),
        ('"native_invalidation_inspection"', '"native_invalidation_repair"', 1),
    ],
    "ServiceEventReplay": [
        ('immediate == "recovering", "capture immediate UI-state gap"', 'immediate == "interrupted", "immediate UI-state repair"', 1),
        ('afterReceipt == "recovering"', 'afterReceipt == "interrupted"', 1),
        ('"immediate_gap_reproduced": true', '"immediate_gap_reproduced": false', 1),
        ('"native_service_event_replay"', '"native_service_event_repair"', 1),
    ],
}
with tempfile.TemporaryDirectory(prefix="review-today-mem02-repair-") as directory:
    flags = ["-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
             "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
             "-lFSRS", "-lReviewTodayContractSupport", "-Xlinker", "-rpath", "-Xlinker", str(support)]
    for name, output in [("MemoryInvalidationInspection", "native-fixed.json"), ("ServiceEventReplay", "paired-fixed.json"),
                         ("StopReceiptFirst", "paired-stop-first-fixed.json")]:
        base_name = "ServiceEventReplay" if name == "StopReceiptFirst" else name
        source = (here / (base_name + ".swift")).read_text()
        if name == "StopReceiptFirst":
            marker = 'precondition(LearningMemory.setAllowed(false, session: origin, context: context))'
            if source.count(marker) != 1:
                raise SystemExit("Preserved source changed; review stop receipt ordering")
            source = source.replace(marker, '''let originalRun = try context.fetch(FetchDescriptor<AgentRun>()).first { $0.id == runID }!
        precondition(ConversationProcessor.queueControl(originalRun, action: "stop", context: context))
        let originalControl = try context.fetch(FetchDescriptor<AgentRunControl>()).first!
        try await ConversationProcessor.deliverControl(originalControl, context: context, request: { _, _ in
            input["stop_receipt"] as! [String: Any]
        })
        precondition(originalRun.status == "interrupted")
        ''' + marker)
        for old, new, count in edits[base_name]:
            if source.count(old) != count:
                raise SystemExit("Preserved fixture changed; review required: " + old)
            source = source.replace(old, new)
        fixture = Path(directory) / (name + ".swift")
        fixture.write_text(source)
        target = Path(directory) / name
        subprocess.run(["xcrun", "swiftc", *flags, str(fixture), "-o", str(target)], check=True)
        command = [str(target)]
        if base_name == "ServiceEventReplay":
            command.append(str(here / "service-baseline.json"))
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        (here / output).write_text(result.stdout)
        print(name + ": repair expectations passed")
