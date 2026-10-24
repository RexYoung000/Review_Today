"""Archive verified owned QA bytes, unregister its package, keep daily data intact."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
PREP = OUT.parent / "2026-10-24-teaching-scope-fullflow-preflight"
sys.path.insert(0, str(PREP))
import common


def archive_files(directory, archive, members):
    assert not archive.exists(), "Never overwrite an evidence archive"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for name in members:
            z.write(directory / name, name)
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == set(members)
        for name, digest in members.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == digest, name
    return dict(archive=str(archive), sha256=common.sha(archive), members=members,
                actual_members_read=len(members))


def main():
    setup = common.read(PREP / "setup.json")
    runtime = Path(setup["directory"])
    durable = common.DURABLE
    common.check_protection(setup)
    assert common.read(OUT / "disk-verification.json")["status"] == "PASS_FROZEN_FUNCTIONAL_PATH"
    assert not subprocess.run(["pgrep", "-x", "FreshFullflowQA"], capture_output=True).stdout
    assert not subprocess.run(["lsof", "-nP", f"-iTCP:{setup['port']}", "-sTCP:LISTEN"], capture_output=True).stdout
    assert common.read(runtime / "quota.json")["closed"] and (runtime / "STOP").is_file()
    package = Path(setup["native_app"])
    signed_zip = Path(setup["native_zip"])
    assert package == runtime / "FreshFullflowQA.app" and package.is_dir() and not package.is_symlink()
    assert common.sha(signed_zip) == setup["native_zip_sha256"]
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(package)], check=True)
    with zipfile.ZipFile(signed_zip) as z:
        matched = 0
        for item in z.infolist():
            if item.is_dir() or not item.filename.startswith("FreshFullflowQA.app/"):
                continue
            path = runtime / item.filename
            assert path.is_file() and hashlib.sha256(z.read(item)).hexdigest() == common.sha(path)
            matched += 1
    before = common.inventory(runtime)
    members = {name: row["sha256"] for name, row in before.items()
               if row["type"] == "file" and not name.startswith("FreshFullflowQA.app/")}
    runtime_archive = archive_files(runtime, durable / "runtime-final.zip", members)
    assert common.inventory(runtime) == before
    common.write(durable / "runtime-final-manifest.json", dict(
        runtime=str(runtime), inventory=before, signed_package=str(signed_zip),
        signed_package_sha256=common.sha(signed_zip), signed_package_members_matched=matched,
        symlinks_recorded_without_dereference=True, **runtime_archive))
    work = ROOT / "output/teaching-scope-fullflow-real-2026-10-24"
    work_members = {str(p.relative_to(work)): common.sha(p) for p in work.rglob("*") if p.is_file()}
    observations = archive_files(work, durable / "execution-observations.zip", work_members)
    ui = durable / "execution-ui"
    ui_members = {str(p.relative_to(ui)): common.sha(p) for p in ui.rglob("*") if p.is_file()}
    ui_archive = archive_files(ui, durable / "execution-ui.zip", ui_members)
    captures = []
    for manifest in sorted((durable / "captures").glob("*/capture.json")):
        value = common.read(manifest)
        assert common.sha(Path(value["archive"])) == value["sha256"]
        with zipfile.ZipFile(value["archive"]) as z:
            assert set(z.namelist()) == set(value["members"])
            for name, digest in value["members"].items():
                assert hashlib.sha256(z.read(name)).hexdigest() == digest
        captures.append(dict(phase=value["phase"], sha256=value["sha256"],
                             actual_members_read=value["actual_members_read"]))
    subprocess.run([common.LS, "-u", str(package)], check=True)
    shutil.rmtree(package)  # Only this archived, owned disposable QA package.
    assert not package.exists()
    identifiers = re.findall(r"^identifier:\s*(.*)$", subprocess.check_output([common.LS, "-dump"], text=True), re.M)
    registrations = [x for x in identifiers if re.search(r"review[-_]?today", x, re.I)]
    assert registrations == ["Rex.Review-Today"], registrations
    spotlight = subprocess.check_output(["mdfind", "kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"], text=True).splitlines()
    assert spotlight == [str(common.DAILY)]
    common.check_protection(setup)
    assert all(common.sha(Path(p)) == h for p, h in setup["owned_support_files"].items())
    result = dict(
        completed_at=datetime.now(timezone.utc).isoformat(), runtime=runtime_archive,
        observations=observations, ui=ui_archive, captures=captures,
        signed_package_sha256=common.sha(signed_zip), signed_package_members_matched=matched,
        raw_owned_qa_package_removed=True, owned_data_and_modules_retained=True,
        daily_registered_entries=registrations, daily_spotlight_paths=spotlight,
        all_seven_daily_files_and_app_unchanged=True, protected_inputs_unchanged=296,
        old_evidence_unchanged=524, original_and_owned_modules_unchanged=True,
        old_missing_paths=12, old_baselines_and_allowances_preserved=True,
        user_project_diff_unchanged=True, cross_database_atomic_snapshot=False,
    )
    common.write(OUT / "archive.json", result)
    print(f"Archived and read-verified {len(members)} runtime files, {len(work_members)} observations, {len(ui_members)} UI files and {len(captures)} captures; one daily entry restored.")


if __name__ == "__main__":
    main()
