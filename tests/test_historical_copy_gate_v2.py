"""Decision-277 regressions: historical bytes do not waive current protection."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GATE_DIR = ROOT / "docs/evidence/2026-11-06-historical-copy-gate-v2"
spec = importlib.util.spec_from_file_location("evidence_gate_v2", GATE_DIR / "evidence_gate_v2.py")
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)
spec = importlib.util.spec_from_file_location("entry_277_tests", GATE_DIR / "entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class HistoricalCopyGateV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="review-today-277-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.objects = self.root / "objects"
        self.objects.mkdir()
        self.first, self.second = self.root / "first", self.root / "second"
        self.first.write_bytes(b"original bytes")
        self.second.write_bytes(self.first.read_bytes())
        self.digest = gate.sha(self.first)
        self.obj = self.objects / self.digest
        self.obj.write_bytes(self.first.read_bytes())
        self.expected = {str(self.first): self.digest, str(self.second): self.digest}
        self.mapping = {str(self.first): dict(sha256=self.digest, private_copy=str(self.obj))}

    def history(self):
        return gate.historical_files(self.expected, self.mapping, copy_root=self.objects)

    def test_present_and_approved_missing_are_distinct(self):
        self.assertEqual(self.history()["original_paths_matched"], 2)
        self.first.unlink()
        result = self.history()
        self.assertEqual(result["original_paths_matched"], 1)
        self.assertEqual(result["original_paths_missing"][0]["original_path"], str(self.first))
        self.assertTrue(result["original_paths_missing"][0]["bytes_verified"])
        self.assertFalse(result["complete_runtime_restoration_claimed"])
        self.assertFalse(self.first.exists())

    def test_same_hash_does_not_approve_another_missing_path(self):
        self.second.unlink()
        with self.assertRaisesRegex(gate.EvidenceMismatch, "Unapproved"):
            self.history()

    def test_changed_original_is_not_hidden_by_valid_copy(self):
        self.first.write_bytes(b"new bytes")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "original changed"):
            self.history()

    def test_wrong_original_type_and_broken_symlink_fail(self):
        self.first.unlink()
        self.first.mkdir()
        with self.assertRaisesRegex(gate.EvidenceMismatch, "wrong file type"):
            self.history()
        self.first.rmdir()
        self.first.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "wrong file type"):
            self.history()

    def test_missing_and_damaged_copy_fail(self):
        self.first.unlink()
        self.obj.unlink()
        with self.assertRaisesRegex(gate.EvidenceMismatch, "copy missing"):
            self.history()
        self.obj.write_bytes(b"corrupt")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "copy changed"):
            self.history()

    def test_wrong_copy_hash_and_location_fail(self):
        self.mapping[str(self.first)]["sha256"] = "0" * 64
        with self.assertRaisesRegex(gate.EvidenceMismatch, "differs from baseline"):
            self.history()
        self.mapping[str(self.first)]["sha256"] = self.digest
        self.mapping[str(self.first)]["private_copy"] = str(self.second)
        with self.assertRaisesRegex(gate.EvidenceMismatch, "location changed"):
            self.history()

    def test_copy_symlink_and_root_symlink_fail(self):
        self.obj.unlink()
        self.obj.symlink_to(self.second)
        with self.assertRaisesRegex(gate.EvidenceMismatch, "symlink"):
            self.history()
        self.obj.unlink()
        self.obj.write_bytes(self.second.read_bytes())
        alias = self.root / "objects-alias"
        alias.symlink_to(self.objects, target_is_directory=True)
        with self.assertRaisesRegex(gate.EvidenceMismatch, "root"):
            gate.historical_files(self.expected, self.mapping, copy_root=alias)

    def test_extra_approval_path_fails(self):
        self.mapping[str(self.root / "extra")] = dict(self.mapping[str(self.first)])
        with self.assertRaisesRegex(gate.EvidenceMismatch, "unlisted"):
            self.history()

    def test_shared_content_keeps_both_missing_paths(self):
        self.mapping[str(self.second)] = dict(self.mapping[str(self.first)])
        self.first.unlink()
        self.second.unlink()
        result = self.history()
        self.assertEqual(len(result["original_paths_missing"]), 2)
        self.assertEqual(result["unique_durable_objects_verified"], 1)

    def policy_fixture(self):
        policy = gate.read(GATE_DIR / "policy.json")
        path = self.root / "policy.json"
        path.write_bytes((GATE_DIR / "policy.json").read_bytes())
        for anchor in policy["anchors"].values():
            target = self.root / anchor["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / anchor["path"]).read_bytes())
        return path, policy

    def test_exact_policy_loads_only_the_fixed_157_paths(self):
        path, _ = self.policy_fixture()
        policy, docs, expected, mapping = gate.load_authorized_policy(path, self.root)
        self.assertEqual((len(expected), len(mapping)), (753, 157))
        old = docs["entry"]["prior_evidence_pins"]["missing"]
        self.assertEqual(len(set(mapping) - set(old)), 36)
        self.assertEqual(policy["stopped_control_files"], docs["previous_policy"]["stopped_control_files"])

    def test_policy_cannot_weaken_authority_scope_or_strict_checks(self):
        path, policy = self.policy_fixture()
        for key, value in [("decision", 278), ("user_answer", "ok and activate"),
                           ("approved_missing_count", 158), ("approved_path_hashes_sha256", "0" * 64),
                           ("copy_root", str(self.objects)), ("strict_metadata", {}),
                           ("stopped_control_files", {}), ("no_batch_activation", False),
                           ("no_frozen_allowance_restore", False), ("no_current_group_exceptions", False)]:
            with self.subTest(key=key):
                path.write_text(json.dumps(dict(policy, **{key: value})))
                with self.assertRaisesRegex(gate.EvidenceMismatch, "policy fingerprint"):
                    gate.load_authorized_policy(path, self.root)

    def test_changed_anchor_is_denied(self):
        path, policy = self.policy_fixture()
        target = self.root / policy["anchors"]["copies"]["path"]
        target.write_text("{}")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "reference changed"):
            gate.load_authorized_policy(path, self.root)

    def test_replacing_a_path_and_updating_all_declared_hashes_is_denied(self):
        path, policy = self.policy_fixture()
        target = self.root / policy["anchors"]["copies"]["path"]
        document = gate.read(target)
        approved = document["approved_missing"]
        old = next(iter(approved))
        approved[old + "-replacement"] = approved.pop(old)
        document["original_path_mapping"][old + "-replacement"] = document["original_path_mapping"].pop(old)
        target.write_text(json.dumps(document))
        policy["anchors"]["copies"]["sha256"] = gate.sha(target)
        policy["approved_path_hashes_sha256"] = hashlib.sha256(json.dumps(
            approved, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(gate.EvidenceMismatch, "policy fingerprint"):
            gate.load_authorized_policy(path, self.root)

    def test_current_groups_never_use_copies_and_report_every_problem(self):
        self.first.unlink()
        self.second.write_bytes(b"changed")
        for label in ["source", "formal data", "runtime", "dependencies"]:
            with self.subTest(label=label):
                result = gate.strict_file_report(self.expected, label=label)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["matched"], 0)
                self.assertEqual([r["state"] for r in result["failures"]], ["missing_or_wrong_type", "changed"])

    def test_runtime_missing_marker_stays_failed_even_with_matching_links(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        expected = {str(runtime / "STOP"): self.digest}
        result = gate.stopped_runtime_report(runtime, expected, {}, lambda p: {})
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["dependency_links_exact"])
        self.assertFalse(result["inventory_exact"])

    def test_runtime_added_file_or_changed_link_fails(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        link = runtime / "python"
        link.symlink_to(self.first)
        expected_links = {"python": str(self.first)}
        result = gate.stopped_runtime_report(runtime, {}, expected_links, lambda p: {"extra": self.digest})
        self.assertEqual(result["status"], "FAIL")
        link.unlink()
        link.symlink_to(self.second)
        result = gate.stopped_runtime_report(runtime, {}, expected_links, lambda p: {})
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["dependency_links_exact"])

    def test_absent_artifact_rejects_dangling_symlink(self):
        link = self.root / "quota.json"
        self.assertTrue(gate.absent(link))
        link.symlink_to(self.root / "missing")
        self.assertFalse(gate.absent(link))

    def test_failed_or_skipped_group_blocks_admission(self):
        groups = {name: dict(status="PASS") for name in entry.REQUIRED_GROUPS}
        self.assertTrue(entry.finish(groups)["ready_for_new_batch"])
        for status in ["FAIL", "SKIPPED"]:
            with self.subTest(status=status):
                groups["stopped_runtime"]["status"] = status
                result = entry.finish(groups)
                self.assertEqual(result["status"], "OFFLINE_PROTECTION_BLOCKED")
                self.assertFalse(result["ready_for_new_batch"])
                with patch.object(entry, "collect", return_value=result):
                    with self.assertRaisesRegex(gate.EvidenceMismatch, "stopped_runtime"):
                        entry.check()

    def test_every_required_group_must_be_present(self):
        groups = {name: dict(status="PASS") for name in entry.REQUIRED_GROUPS}
        for name in entry.REQUIRED_GROUPS:
            with self.subTest(missing=name):
                result = entry.finish({k: v for k, v in groups.items() if k != name})
                self.assertFalse(result["ready_for_new_batch"])
                self.assertEqual(result["missing_check_groups"], [name])
        self.assertFalse(entry.finish({})["ready_for_new_batch"])

    def test_formal_inventory_rejects_symlink_alias_of_same_bytes(self):
        alias = self.root / "formal-alias"
        alias.symlink_to(self.first)
        with self.assertRaisesRegex(gate.EvidenceMismatch, "Formal data contains a symlink"):
            entry.formal_inventory_matches(self.root, self.expected, lambda p: self.expected)

    def test_no_activation_cli_option_exists(self):
        result = subprocess.run([sys.executable, "-B", str(GATE_DIR / "entry.py"), "--activate"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_audit_denies_network_database_and_startup_in_imported_use(self):
        code = """
import sys, socket, sqlite3, subprocess
sys.path.insert(0, sys.argv[1])
import entry
entry.enforce_offline()
actions = [lambda: socket.socket().connect(('127.0.0.1', 9)),
           lambda: sqlite3.connect(':memory:'),
           lambda: subprocess.run(['open', '-a', 'Review Today'])]
for action in actions:
    try:
        action()
    except PermissionError:
        continue
    raise AssertionError('offline action was not blocked')
"""
        result = subprocess.run([sys.executable, "-B", "-c", code, str(GATE_DIR)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
