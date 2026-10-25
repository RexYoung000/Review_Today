"""Verify backups, isolated approval cases and the real pending startup entry."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from common import *


def approval_cases():
    import approval
    fixture = Path(tempfile.mkdtemp(prefix="review-today-service-approval-", suffix=".noindex"))
    for name in ["out", "activation", "app", "support"]:
        (fixture / name).mkdir()
    (fixture / "service.py").write_text("# offline approval fixture\n")
    approval.ROOT = fixture
    approval.OUT = fixture / "out"
    approval.PRIVATE = fixture
    approval.DAILY = fixture / "app"
    approval.SUPPORT = fixture / "support"
    scope = "offline service-only fixture"
    plan = dict(batch_id="fixture-new-batch", scope=scope)
    write(approval.OUT / "plan.json", plan)
    write(approval.OUT / "source-pins.json", {"service.py": sha(fixture / "service.py")})
    write(approval.OUT / "setup.json", dict(daily_app_inventory=inventory(approval.DAILY), daily_files=files(approval.SUPPORT)))
    good = dict(status="approved", batch_id=plan["batch_id"], scope=scope,
                actual_model_request_limit=8, provider_web_operation_limit=0,
                daily_app=str(approval.DAILY), database_path=str(approval.SUPPORT / "agent-harness.sqlite3"),
                plan_sha256=sha(approval.OUT / "plan.json"))
    results = []
    def attempt(name, spec, expected):
        write(fixture / "activation/authorization.json", spec)
        before = files(fixture)
        try:
            actual = approval.require_approved()
            assert expected and actual == spec, name
        except PermissionError:
            assert not expected, name
        assert files(fixture) == before
        results.append(dict(case=name, passed=True))
    attempt("approved exact service-only scope", good, True)
    for key, value in [("status", "pending"), ("batch_id", "old-batch"),
                       ("actual_model_request_limit", 9), ("provider_web_operation_limit", 1),
                       ("scope", "launch App or save"), ("daily_app", "/other.app"),
                       ("database_path", "/other.sqlite3"), ("plan_sha256", "changed")]:
        changed = dict(good, **{key: value})
        attempt(key + " mismatch", changed, False)
    for marker in ["HOLD", "STOP"]:
        (fixture / "activation" / marker).write_text("fixture\n")
        attempt(marker + " refuses", good, False)
        (fixture / "activation" / marker).unlink()
    (fixture / "execution.json").write_text("{}")
    attempt("second startup refuses", good, False)
    (fixture / "execution.json").unlink()
    (fixture / "service.py").write_text("# changed input\n")
    attempt("changed source refuses", good, False)
    (fixture / "service.py").write_text("# offline approval fixture\n")
    (fixture / "app/new-file").write_text("changed App")
    attempt("changed App refuses", good, False)
    (fixture / "app/new-file").unlink()
    (fixture / "support/new-file").write_text("changed data")
    attempt("changed data refuses", good, False)
    return results


def main():
    unchanged()
    state = read(OUT / "setup.json")
    pins = dict(state["source_config_pins"])
    for path in OUT.glob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
        pins[str(path.relative_to(ROOT))] = sha(path)
    for name in ["plan.json", "setup.json", "backup.json", "source-delta.json"]:
        pins[str((OUT / name).relative_to(ROOT))] = sha(OUT / name)
    write(OUT / "source-pins.json", pins)
    guards = approval_cases()
    program = '''import json,runpy,sys
from pathlib import Path
entry=Path(sys.argv[1]);sys.path.insert(0,str(entry.parent))
def audit(event,args):
    if event in {'socket.connect','sqlite3.connect'}:raise AssertionError('Runtime before approval')
sys.addaudithook(audit)
try:runpy.run_path(str(entry),run_name='__main__')
except PermissionError as error:
    assert 'pending explicit approval' in str(error)
    assert not any(n in sys.modules for n in ['agent_service.main','agent_service.openai_client','quota_activation'])
    print('PASS actual pending entry rejected before SDK/service/database/network')
else:raise AssertionError('Pending actual entry admitted')
'''
    activation = PRIVATE / "activation"
    held = files(activation)
    assert {p.name for p in activation.iterdir()} == {"authorization.json", "HOLD"}
    result = subprocess.run([sys.executable, "-B", "-c", program, str(OUT / "start_service.py")],
                            capture_output=True, text=True, timeout=20)
    (OUT / "pending-entry-check.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr
    assert files(activation) == held and not (PRIVATE / "execution.json").exists()
    assert not (activation / "quota.json").exists()
    for name in ["probe-checks.json", "probe-failure-check.json"]:
        assert read(OUT / name)["outcome"] == "PASS"
    assert read(OUT / "startup-rehearsal.json")["status"] == "PASS"
    assert all(sha(Path(p)) == digest for p, digest in read(PRIVATE / "backup-pins.json").items())
    before = read(PRIVATE / "before-tables.json")
    helpers = backup_helpers()
    for relative, name in DBS.items():
        assert helpers.summary(ARCHIVE / "consistent-databases" / name) == before[relative]
    assert all(sha(ARCHIVE / "raw-active-support" / Path(p).relative_to(SUPPORT)) == digest
               for p, digest in state["daily_files"].items())
    package = ARCHIVE / "prepared-backup.zip"
    manifest = read(ARCHIVE / "prepared-backup-manifest.json")
    assert sha(package) == manifest["sha256"]
    with zipfile.ZipFile(package) as z:
        assert set(z.namelist()) == set(manifest["members"])
        assert all(hashlib.sha256(z.read(n)).hexdigest() == h for n, h in manifest["members"].items())
    ids = re.findall(r"^identifier:\s*(.*)$", subprocess.check_output([LS, "-dump"], text=True), re.M)
    registered = [x for x in ids if re.search(r"review[-_]?today", x, re.I)]
    assert registered == ["Rex.Review-Today"]
    spotlight = subprocess.check_output(["mdfind", "kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"], text=True).splitlines()
    assert spotlight == [str(DAILY)]
    unchanged()
    write(OUT / "verification.json", dict(status="READY_PENDING_SERVICE_ONLY_8_0", decision=272,
        actual_model_requests=0, actual_web_operations=0, daily_app_replacement_needed=False,
        daily_app_started=False, daily_service_started=False, app_and_service_stopped=True,
        daily_seven_files_unchanged=True, original_formal_databases_opened=False,
        backup_members_read=len(manifest["members"]), consistent_db_copies=3,
        original_raw_bytes_and_consistent_logical_rows_preserved=True,
        source_config_execution_pins=len(pins), old_evidence_pins_preserved=len(state["prior_evidence_pins"]),
        known_missing_paths_preserved=len(state["known_missing_old_paths"]),
        approval_cases=guards, actual_pending_entry_rejected_before_runtime=True,
        actual_pending_entry_files_unchanged=True, quota_and_execution_not_created=True,
        sdk_fake_transport_checks=read(OUT / "probe-checks.json"),
        first_failure_stop_check=read(OUT / "probe-failure-check.json"),
        copied_daily_startup_rehearsal=read(OUT / "startup-rehearsal.json"),
        single_daily_registration=registered, spotlight_paths=spotlight,
        current_module_and_user_project_diff_preserved=True, all_old_allowances_frozen=True,
        new_limit_not_approved=True, original_native_functional_evidence="271 preserved; no new native acceptance",
        app_managed_service_startup_and_rex_experience_not_verified=True))
    print(f"READY pending service-only 8/0; {len(guards)} isolated approval cases, real pending refusal, fake SDK caps, backups and one entry passed; real 0/0.")


if __name__ == "__main__":
    main()
