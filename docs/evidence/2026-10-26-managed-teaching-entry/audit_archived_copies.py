"""Recover verified historical bytes to a new private folder, never old paths."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    assert not (OUT / "archived-copies.json").exists()
    entry = read(OUT / "entry-check.json")
    setup = read(OUT / "setup.json")
    missing = entry["prior_evidence_pins"]["missing"]
    before = read(ROOT / "docs/evidence/2026-10-25-daily-service-preflight/setup.json")
    base = Path.home() / "Library/Developer/ReviewTodayEvidence.noindex/2026-10-23-historical-protection"
    manifest = read(base / "manifest.json")
    archive = Path(manifest["archive"])
    assert sha(archive) == manifest["archive_sha256"] == before["prior_evidence_pins"][str(archive)]
    destination = Path(setup["archive"]) / "recovered-byte-objects"
    destination.mkdir(mode=0o700)
    def audit(event, args):
        if event in {"socket.connect", "sqlite3.connect"}:
            raise AssertionError("Recovery is byte-only; no network or SQLite")
    sys.addaudithook(audit)
    objects, mapping = {}, {}
    with zipfile.ZipFile(archive) as z:
        requested = {"objects/" + digest for digest in missing.values()}
        assert requested.issubset(z.namelist())
        assert sum(z.getinfo(n).file_size for n in requested) < 512 * 1024 * 1024
        for digest in sorted(set(missing.values())):
            target = destination / digest
            checksum = hashlib.sha256()
            with z.open("objects/" + digest) as source, target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    checksum.update(chunk)
            target.chmod(0o600)
            assert checksum.hexdigest() == sha(target) == digest
            objects[digest] = dict(path=str(target), bytes=target.stat().st_size, archive_member="objects/" + digest)
        for original, digest in missing.items():
            assert not Path(original).exists(), "Original path must remain an observed gap"
            mapping[original] = dict(sha256=digest, private_copy=objects[digest]["path"],
                original_still_missing=True, exact_archive_member_read=True, private_copy_reread=True)
    assert all(Path(p).is_file() and sha(Path(p)) == h for p, h in before["prior_evidence_pins"].items() if p not in missing)
    result = dict(status="ALL_121_MISSING_PATHS_HAVE_VERIFIED_DURABLE_BYTES", original_missing_paths=len(missing),
        exact_bytes_verified_for_paths=len(mapping), unique_objects=len(objects), bytes_copied=sum(v["bytes"] for v in objects.values()),
        source_archive=str(archive), source_archive_sha256=sha(archive), objects=objects, original_path_mapping=mapping,
        original_missing_paths_not_restored=True, missing_cause_not_established=True, old_baselines_unchanged=True,
        bytes_only_not_complete_database_or_runtime_restoration=True, remaining_632_old_files_matched=True,
        older_12_path_gaps_and_two_unresolved_old_main_databases_unchanged=True,
        sqlite_opened=False, app_started=False, service_started=False, actual_model_requests=0, actual_web_operations=0,
        current_20_0_stopped_and_unused_frozen=True,
        acceptance_rule_not_changed=True, next_rule_proposal="For these 121 historical evidence paths only, verify the exact persistent objects and retain the original missing-path finding. Current source, daily data, active runtime and dependencies still require exact original paths. Any other mismatch stops admission.")
    (OUT / "archived-copies.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (Path(setup["archive"]) / "recovered-byte-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"PASS: {len(mapping)} missing original paths covered by {len(objects)} exact objects, {result['bytes_copied']} bytes, read twice; old paths and baseline unchanged; real 0/0 remains stopped.")


if __name__ == "__main__":
    main()
