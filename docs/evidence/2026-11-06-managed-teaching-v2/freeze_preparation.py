"""Freeze final pending inputs and read back their durable archive, without startup."""
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile
from common import *


def main():
    os.umask(0o077)
    unchanged()
    state = read(OUT / "setup.json")
    runtime = Path(state["directory"])
    require(read(runtime / "authorization.json")["status"] == "pending" and (runtime / "HOLD").exists(), "Not pending")
    pins = dict(state["protected_fingerprints"])
    for p in list(OUT.glob("*.py")) + list(OUT.glob("*.swift")) + [OUT/n for n in ["baseline.json", "plan.json", "setup.json", "dependency-provenance.json", "runtime-path-fix.json"]]:
        pins[str(p.relative_to(ROOT))] = sha(p)
    write(OUT / "source-pins.json", pins)
    auth = read(runtime / "authorization.json")
    auth.update(plan_sha256=sha(OUT / "plan.json"), source_pins_sha256=sha(OUT / "source-pins.json"))
    write(runtime / "authorization.json", auth)
    raw = files(runtime)
    write(PRIVATE / "runtime-pins.json", raw)
    owned = {str(p): sha(p) for p in runtime.rglob("*") if p.is_file() and not p.is_symlink()}
    archive = ARCHIVE / "prepared-runtime.zip"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for path in owned:
            z.write(path, str(Path(path).relative_to(runtime)))
    with zipfile.ZipFile(archive) as z:
        for path, digest in owned.items():
            with z.open(str(Path(path).relative_to(runtime))) as stream:
                require(__import__("hashlib").file_digest(stream, "sha256").hexdigest() == digest, "Runtime archive differs")
    package_members = {}
    with zipfile.ZipFile(state["native_zip"]) as z:
        for name in z.namelist():
            with z.open(name) as stream:
                package_members[name] = __import__("hashlib").file_digest(stream, "sha256").hexdigest()
    write(OUT / "archives.json", dict(runtime_archive=str(archive), runtime_sha256=sha(archive), runtime_files=raw,
        owned_archive_files=owned, dependency_links=state["dependency_links"], runtime_alias=state["runtime_alias"],
        runtime_alias_target=state["directory"], every_member_stream_read=True,
        native_package=state["native_zip"], native_package_sha256=state["native_zip_sha256"], native_members=package_members))
    unchanged()
    require(files(runtime) == raw, "Pending runtime changed during archive")
    print("Final pending source/runtime pins and all archive members verified; real 0/0.")


if __name__ == "__main__":
    main()
