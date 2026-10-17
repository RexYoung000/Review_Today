"""Compile the already reviewed reader and inspect only this closed QA store."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    previous = json.loads((EVIDENCE.parent / "2026-10-16-native-save-continuation/setup.json").read_text())
    support = Path(previous["support_dir"])
    source = EVIDENCE.parent / "2026-10-16-status-native-input/NativeDiskRead.swift"
    cmd = ["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
        "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
        "-lReviewTodayContractSupport", "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(support),
        str(source), "-o", str(directory / "native-real-disk-reader")]
    with (EVIDENCE / "native-disk-read-build.log").open("w") as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
    with (EVIDENCE / "native-disk-read.log").open("w") as output:
        subprocess.run([str(directory / "native-real-disk-reader"), str(directory)], stdout=output, stderr=subprocess.STDOUT, check=True)
    (EVIDENCE / "native-reader-source.json").write_text(json.dumps(dict(
        source=str(source.relative_to(ROOT)), sha256=hashlib.sha256(source.read_bytes()).hexdigest()),indent=2)+"\n")


if __name__ == "__main__":
    main()
