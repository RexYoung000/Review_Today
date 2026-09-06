#!/usr/bin/env python3
"""Backup, preflight and verify a bounded SwiftData library import.

Run the app only after this command finishes. Source remains read-only. Each
invocation makes online SQLite backups (including WAL), never copies live files.
"""
import argparse
import json
import pathlib
import sqlite3
import subprocess
import uuid

TABLES = {"ZSOURCE": "ZID", "ZKNOWLEDGE": "ZID", "ZQUESTION": "ZID", "ZFSRSSTATE": "ZKNOWLEDGEID", "ZREVIEWSESSION": "ZID", "ZREVIEWATTEMPT": "ZATTEMPTID"}
IGNORE = {"Z_PK", "Z_ENT", "Z_OPT"}


def snapshot(source, destination):
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def read(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    result = {}
    for table in TABLES:
        result[table] = [{k: str(uuid.UUID(bytes=v)) if isinstance(v, bytes) and len(v) == 16 else v for k, v in dict(row).items()} for row in db.execute("SELECT * FROM " + table)]
    db.close()
    sources = {r["Z_PK"]: r["ZID"] for r in result["ZSOURCE"]}
    cards = {r["Z_PK"]: r["ZID"] for r in result["ZKNOWLEDGE"]}
    for r in result["ZKNOWLEDGE"]: r["source_id"] = sources.get(r.pop("ZSOURCE"))
    for r in result["ZQUESTION"]: r["knowledge_id"] = cards.get(r.pop("ZKNOWLEDGE"))
    return result


def selected(source):
    # Preserve all review history, but never copy CaptureTask/AppSettings outboxes.
    source_ids = {r["source_id"] for r in source["ZKNOWLEDGE"]}
    source["ZSOURCE"] = [r for r in source["ZSOURCE"] if r["ZID"] in source_ids]
    cards = {r["ZID"] for r in source["ZKNOWLEDGE"]}
    assert all(r["ZKNOWLEDGEID"] in cards for r in source["ZREVIEWATTEMPT"] + source["ZFSRSSTATE"])
    questions = {r["ZID"] for r in source["ZQUESTION"]}
    reviews = {r["ZID"] for r in source["ZREVIEWSESSION"]}
    assert all(r["ZQUESTIONID"] in questions and r["ZSESSIONID"] in reviews for r in source["ZREVIEWATTEMPT"])
    needed_reviews = {r["ZSESSIONID"] for r in source["ZREVIEWATTEMPT"]}
    source["ZREVIEWSESSION"] = [r for r in source["ZREVIEWSESSION"] if r["ZID"] in needed_reviews]
    # Unfinished historical review sessions would be a new product decision.
    assert all(r["ZENDEDAT"] is not None for r in source["ZREVIEWSESSION"]), "Unfinished review: do not reactivate old work"
    return source


def verify(source, target, require_all=False):
    for table, id_key in TABLES.items():
        existing = {r[id_key]: r for r in target[table]}
        for row in source[table]:
            other = existing.get(row[id_key])
            if other is None:
                assert not require_all, f"Missing imported {table} ID"
                continue
            for key, value in row.items():
                if key in IGNORE: continue
                assert value == other.get(key), f"Conflict in {table}.{key}; original ID preserved, refusing overwrite"
            if table == "ZREVIEWATTEMPT":
                assert other.get("ZCOMPLETEDAT") is None, "Legacy completion time must remain unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=pathlib.Path, required=True)
    parser.add_argument("--target", type=pathlib.Path, required=True)
    parser.add_argument("--backup-dir", type=pathlib.Path, required=True)
    parser.add_argument("--importer", type=pathlib.Path, required=True)
    args = parser.parse_args()
    assert args.source.resolve() != args.target.resolve()
    args.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    snapshot(args.source, args.backup_dir / "legacy.store")
    snapshot(args.target, args.backup_dir / "current.store")
    source = selected(read(args.backup_dir / "legacy.store"))
    verify(source, read(args.backup_dir / "current.store"))
    # Deleted sessions are not imported. Library rows without known origin cannot
    # be assigned to a session or resurrect its messages/checkpoint.
    payload = args.backup_dir / "library.json"
    payload.write_text(json.dumps(source, ensure_ascii=False))
    payload.chmod(0o600)
    subprocess.run([str(args.importer.resolve()), str(payload.resolve()), str(args.target.resolve())], check=True)
    verify(source, read(args.target), require_all=True)
    # A repeated import must have precisely the same library IDs and values.
    before = read(args.target)
    subprocess.run([str(args.importer.resolve()), str(payload.resolve()), str(args.target.resolve())], check=True)
    assert read(args.target) == before, "Repeated import changed persisted rows"
    counts = {table: len(rows) for table, rows in source.items()}
    report = dict(status="verified", counts=counts, preview_count=sum(r["ZMODE"] == "preview" for r in source["ZREVIEWATTEMPT"]), original_preserved=True, repeated_import_unchanged=True)
    (args.backup_dir / "verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__": main()
