"""Compare closed formal-data snapshots on new private copies, without approving a baseline."""
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
SUPPORT = Path.home() / "Library/Application Support/Review Today"
PRIVATE = Path.home() / "Library/Developer/ReviewTodayEvidence.noindex"
PREPARED = ROOT / "docs/evidence/2026-10-25-managed-teaching-preflight/setup.json"
OLD_ARCHIVE = PRIVATE / "2026-10-25-daily-service"
DBS = {"native": "Data/ReviewToday.store", "service": "agent-harness.sqlite3", "review": "agent-harness.review.sqlite3"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def stopped():
    require(subprocess.run(["pgrep", "-x", "Review_Today"], capture_output=True).returncode == 1, "App is active")
    require(subprocess.run(["lsof", "-nP", "-iTCP:8742", "-sTCP:LISTEN", "-t"], capture_output=True).returncode == 1,
            "Service is active")


def inventory(directory):
    result = {}
    for path in Path(directory).rglob("*"):
        require(not path.is_symlink(), "Snapshot source contains a symlink")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = sha(path)
    return result


def copy_files(source, target, pins):
    target.mkdir(mode=0o700)
    for rel, digest in pins.items():
        src, dst = source / rel, target / rel
        require(src.is_file() and sha(src) == digest, "Snapshot source changed")
        dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with src.open("rb") as stream, dst.open("xb") as dest:
            shutil.copyfileobj(stream, dest)
        os.chmod(dst, 0o600)
        require(sha(dst) == digest, "Snapshot copy differs")


def fingerprint(value):
    def encode(item):
        if isinstance(item, bytes):
            return {"blob": item.hex()}
        return item
    payload = json.dumps([encode(item) for item in value], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def inspect_copy(path):
    # mode=ro includes the copied WAL; immutable=1 would wrongly ignore it.
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        require(integrity == [("ok",)], "Copy integrity check failed")
        schemas = connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        tables = {}
        for name, sql in schemas:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = connection.execute("PRAGMA table_info(" + quoted + ")").fetchall()
            pk = [row[0] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
            rows = connection.execute("SELECT * FROM " + quoted).fetchall()
            digests = [fingerprint(row) for row in rows]
            identities = {fingerprint([row[i] for i in pk]): fingerprint(row) for row in rows} if pk else None
            require(identities is None or len(identities) == len(rows), "Non-unique declared row identity")
            tables[name] = dict(count=len(rows), schema_sha256=fingerprint([sql]), rows=Counter(digests), ids=identities)
            if name in {"ZAGENTSESSION", "ZAPPSETTINGS", "ZLEARNINGTASK"} and pk:
                tables[name]["column_names"] = [c[1] for c in columns]
                tables[name]["cells"] = {fingerprint([row[i] for i in pk]): row for row in rows}
        return tables
    finally:
        connection.close()


def compare(old, current):
    result = []
    for name in sorted(old.keys() | current.keys()):
        before, after = old.get(name), current.get(name)
        if before is None or after is None:
            result.append(dict(table=name, state="added_table" if before is None else "removed_table",
                               old_count=before["count"] if before else 0, current_count=after["count"] if after else 0))
            continue
        row = dict(table=name, old_count=before["count"], current_count=after["count"],
                   schema_matches=before["schema_sha256"] == after["schema_sha256"],
                   identical_rows=sum((before["rows"] & after["rows"]).values()))
        if before["ids"] is not None and after["ids"] is not None and row["schema_matches"]:
            first, second = before["ids"], after["ids"]
            row.update(added_ids=len(second.keys() - first.keys()), removed_ids=len(first.keys() - second.keys()),
                       changed_ids=sum(first[k] != second[k] for k in first.keys() & second.keys()))
            if "cells" in before and "cells" in after:
                changes = {column: sum(before["cells"][key][i] != after["cells"][key][i]
                                       for key in first.keys() & second.keys())
                           for i, column in enumerate(before["column_names"])}
                row["changed_columns_counts"] = {column: count for column, count in changes.items() if count}
        else:
            row.update(removed_row_versions=sum((before["rows"] - after["rows"]).values()),
                       added_row_versions=sum((after["rows"] - before["rows"]).values()))
        result.append(row)
    return result


def main():
    stopped()
    prepared = json.loads(PREPARED.read_text())
    old_pins = {Path(p).relative_to(SUPPORT).as_posix(): h for p, h in prepared["daily_files"].items()}
    current_pins = inventory(SUPPORT)
    require(set(current_pins) == set(old_pins), "Current file set differs; review before copying")
    manifest = json.loads((OLD_ARCHIVE / "actual-runtime-manifest.json").read_text())
    require(sha(manifest["archive"]) == manifest["sha256"], "Pinned old archive changed")
    old_source = OLD_ARCHIVE / "actual/after-raw"
    for rel, digest in old_pins.items():
        require(manifest["members"]["actual/after-raw/" + rel] == digest, "Old copy differs from authoritative baseline")
    work = Path(tempfile.mkdtemp(prefix="2026-11-06-formal-copy-review-", dir=PRIVATE)).resolve()
    allowed = {((work / label / rel).as_uri() + "?mode=ro") for label in ["old-work", "current-work"] for rel in DBS.values()}
    original_connections = 0

    def audit(event, args):
        if event in {"socket.connect", "socket.bind"}:
            raise PermissionError("No network in data-copy review")
        if event == "sqlite3.connect" and str(args[0]) not in allowed:
            raise PermissionError("Only the six new private working copies may be opened")
    sys.addaudithook(audit)
    copy_files(old_source, work / "old-raw", old_pins)
    copy_files(SUPPORT, work / "current-raw", current_pins)
    stopped()
    require(inventory(SUPPORT) == current_pins, "Formal data changed during capture")
    copy_files(work / "old-raw", work / "old-work", old_pins)
    copy_files(work / "current-raw", work / "current-work", current_pins)
    databases = {label: dict(old_integrity="ok", current_integrity="ok", tables=compare(
        inspect_copy(work / "old-work" / rel), inspect_copy(work / "current-work" / rel))) for label, rel in DBS.items()}
    stopped()
    require(inventory(SUPPORT) == current_pins, "Formal originals changed during copy inspection")
    require(inventory(work / "current-raw") == current_pins, "Captured current bytes changed")
    require(inventory(work / "old-raw") == old_pins, "Captured old bytes changed")
    report = dict(status="COPIES_INSPECTED_NOT_BASELINE_APPROVAL", recorded_at=datetime.now().astimezone().isoformat(),
                  private_copy_directory=str(work), formal_originals_unchanged_during_review=True,
                  original_database_connections=original_connections, approved_new_baseline=False,
                  current_file_pins=current_pins, old_file_pins=old_pins, databases=databases,
                  limits="Counts and exact-row comparisons only; changes are not attributed or declared semantically correct.",
                  actual_model_requests=0, actual_web_operations=0, app_or_service_started=False)
    # Keep one new raw snapshot; the old bytes already have a pinned archive.
    # Delete only temporary copies created by this invocation, after verification.
    for label in ["old-raw", "old-work", "current-work"]:
        shutil.rmtree(work / label)
    report["temporary_work_copies_removed"] = True
    report["retained_current_raw_copy"] = str(work / "current-raw")
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    os.chmod(work / "report.json", 0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
