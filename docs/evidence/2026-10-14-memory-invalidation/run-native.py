"""Run inspection probes against a verified isolated native support module.

Build current support with tests/mac/run-contracts.py when app source changed.
Both probes assert the reproduced pre-repair state; neither proves a fix.
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
        raise SystemExit("Missing verified native support: " + name)
with tempfile.TemporaryDirectory(prefix="review-today-invalidation-probes-") as directory:
    flags = ["-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
             "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
             "-lFSRS", "-lReviewTodayContractSupport", "-Xlinker", "-rpath", "-Xlinker", str(support)]
    for name, output in [("MemoryInvalidationInspection", "native-baseline.json"), ("ServiceEventReplay", "paired-baseline.json")]:
        target = Path(directory) / name
        subprocess.run(["xcrun", "swiftc", *flags, str(here / (name + ".swift")), "-o", str(target)], check=True)
        command = [str(target)]
        if name == "ServiceEventReplay":
            command.append(str(here / "service-baseline.json"))
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        (here / output).write_text(result.stdout)
        print(name + ": current behavior reproduced; not repair acceptance")
