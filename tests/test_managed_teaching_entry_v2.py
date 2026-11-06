"""Offline contracts for the newly approved baseline and still-unapproved batch."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/2026-11-06-managed-teaching-v2"
sys.path.insert(0, str(OUT))
# Load isolated names so the historical-gate tests can share one discovery run.
spec = importlib.util.spec_from_file_location("managed_common_278", OUT / "common.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
with patch.dict(sys.modules, {"common": common}):
    spec = importlib.util.spec_from_file_location("managed_entry_278", OUT / "entry.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    spec = importlib.util.spec_from_file_location("managed_bootstrap_278", OUT / "bootstrap.py")
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)


class ManagedEntryV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="review-today-278-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.out = self.root / "evidence"
        self.out.mkdir()
        self.app = self.runtime / "candidate.app"
        self.package = self.root / "candidate.zip"
        self.package.write_bytes(b"test-only archive")
        self.source = self.root / "source.py"
        self.source.write_text("# fixture\n")
        self.plan = self.out / "plan.json"
        common.write(self.plan, dict(scope="fixture"))
        common.write(self.out / "source-pins.json", {"source.py": common.sha(self.source)})
        self.setup = dict(directory=str(self.runtime), native_app=str(self.app), native_zip=str(self.package),
                          native_zip_sha256=common.sha(self.package), batch_id="new", scope="fixture", dependency_links={})
        common.write(self.out / "setup.json", self.setup)
        self.auth = dict(status="pending", batch_id="new", scope="fixture", actual_model_request_limit=20,
                         provider_web_operation_limit=0, plan_sha256=common.sha(self.plan),
                         source_pins_sha256=common.sha(self.out / "source-pins.json"))
        common.write(self.runtime / "authorization.json", self.auth)
        (self.runtime / "HOLD").write_text("pending")
        self.pins = common.files(self.runtime)
        self.addCleanup(patch.stopall)
        patch.object(entry, "OUT", self.out).start()
        patch.object(bootstrap, "OUT", self.out).start()

    def check_held(self, pins=None):
        return entry.held_runtime(self.setup, self.pins if pins is None else pins)

    def test_exact_held_runtime_matches_but_cannot_execute(self):
        self.assertEqual(self.check_held(), 2)
        with self.assertRaisesRegex(PermissionError, "pending/HOLD/STOP"):
            bootstrap.check_approved(self.runtime, self.root)

    def test_missing_changed_and_added_runtime_files_fail(self):
        (self.runtime / "HOLD").unlink()
        with self.assertRaisesRegex(RuntimeError, "runtime changed"):
            self.check_held()
        (self.runtime / "HOLD").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "runtime changed"):
            self.check_held()
        (self.runtime / "HOLD").write_text("pending")
        (self.runtime / "unexpected").write_text("new")
        with self.assertRaisesRegex(RuntimeError, "runtime changed"):
            self.check_held()

    def test_activity_artifact_fails_even_if_inventory_is_relisted(self):
        for name in ["STOP", "quota.json", "startup-claim.json", "app.store", "review.sqlite3"]:
            with self.subTest(name=name):
                target = self.runtime / name
                target.write_text("unexpected")
                with self.assertRaisesRegex(RuntimeError, "Unexpected new batch activity"):
                    self.check_held(common.files(self.runtime))
                target.unlink()

    def test_pending_limits_cannot_expand(self):
        for key, value in [("actual_model_request_limit", 21), ("provider_web_operation_limit", 1), ("batch_id", "old")]:
            with self.subTest(key=key):
                common.write(self.runtime / "authorization.json", dict(self.auth, **{key: value}))
                with self.assertRaises(RuntimeError):
                    self.check_held(common.files(self.runtime))

    def test_added_dependency_alias_and_changed_archive_fail(self):
        link = self.runtime / "python"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(RuntimeError, "dependency links changed"):
            self.check_held(common.files(self.runtime))
        link.unlink()
        self.package.write_bytes(b"changed archive")
        with self.assertRaisesRegex(RuntimeError, "candidate changed"):
            self.check_held()

    def test_current_baseline_fingerprint_cannot_be_replaced(self):
        common.write(self.out / "baseline.json", dict(decision=278, formal_files={}))
        with patch.object(common, "OUT", self.out):
            with self.assertRaisesRegex(RuntimeError, "baseline changed"):
                common.unchanged()

    def test_port_checks_refuse_listener_and_inspection_error(self):
        for code in [0, 1, 2]:
            with self.subTest(code=code), patch.object(common.subprocess, "run", return_value=subprocess.CompletedProcess([], code)):
                if code == 1:
                    common.require_idle_port(56096)
                else:
                    with self.assertRaisesRegex(RuntimeError, "active"):
                        common.require_idle_port(56096)

    def test_exact_approved_fixture_still_checks_sources_dependencies_and_claim(self):
        (self.runtime / "HOLD").unlink()
        common.write(self.runtime / "authorization.json", dict(self.auth, status="approved"))
        bootstrap.check_approved(self.runtime, self.root)
        self.source.write_text("# changed")
        with self.assertRaisesRegex(PermissionError, "Source changed"):
            bootstrap.check_approved(self.runtime, self.root)
        self.source.write_text("# fixture\n")
        (self.runtime / "startup-claim.json").write_text("claimed")
        with self.assertRaisesRegex(PermissionError, "already claimed"):
            bootstrap.check_approved(self.runtime, self.root)


if __name__ == "__main__":
    unittest.main()
