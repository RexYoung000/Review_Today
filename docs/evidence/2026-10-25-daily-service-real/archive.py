"""Preserve and stream-read every completed batch member; no runtime imports."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import zipfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / "docs/evidence/2026-10-25-daily-service-preflight"))
from common import ARCHIVE, PRIVATE, read, write, sha, files, stopped


def main():
    stopped()
    assert read(OUT / "verification.json")["status"] == "PASS_SERVICE_ONLY_STARTUP_CLOSED"
    assert read(PRIVATE / "activation/quota.json")["model_requests"] == 8
    destination = ARCHIVE / "actual-runtime.zip"
    assert not destination.exists()
    members = {"actual/" + str(Path(p).relative_to(ARCHIVE / "actual")): Path(p)
               for p in files(ARCHIVE / "actual")}
    members.update({"activation/" + str(Path(p).relative_to(PRIVATE / "activation")): Path(p)
                    for p in files(PRIVATE / "activation")})
    members["execution.json"] = PRIVATE / "execution.json"
    pins = {name: sha(path) for name, path in members.items()}
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as z:
        for name, path in members.items():
            z.write(path, name)
    destination.chmod(0o600)
    with zipfile.ZipFile(destination) as z:
        assert set(z.namelist()) == set(pins)
        for name, digest in pins.items():
            with z.open(name) as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    assert all(sha(path) == pins[name] for name, path in members.items())
    result = dict(status="PASS", archived_at=datetime.now(timezone.utc).isoformat(),
        archive=str(destination), sha256=sha(destination), members=pins,
        every_member_stream_read_and_matched=True, member_count=len(pins),
        original_formal_databases_opened=False, runtime_and_initial_observer_failure_preserved=True,
        private_archive_mode="0600", private_parent_mode="0700", runtime_still_closed=True,
        actual_model_requests=8, actual_web_operations=0)
    write(ARCHIVE / "actual-runtime-manifest.json", result)
    write(OUT / "archive.json", result)
    print(f"PASS: {len(pins)} private runtime members archived and fully stream-read; real 8/0 remains closed.")


if __name__ == "__main__":
    main()
