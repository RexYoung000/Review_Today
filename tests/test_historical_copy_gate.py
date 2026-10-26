"""Regression tests for the approved historical-copy admission boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "docs/evidence/2026-10-26-historical-copy-gate/evidence_gate.py"
spec = importlib.util.spec_from_file_location("historical_copy_gate", MODULE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class HistoricalCopyGateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="review-today-copy-gate-")
        self.addCleanup(self.fixture.cleanup)
        self.root = Path(self.fixture.name).resolve()
        self.copies = self.root / "objects"
        self.copies.mkdir()
        self.content = b"closed historical evidence"
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.first, self.second = self.root / "first", self.root / "second"
        self.first.write_bytes(self.content)
        self.second.write_bytes(self.content)
        self.copy = self.copies / self.digest
        self.copy.write_bytes(self.content)
        self.expected = {str(self.first): self.digest, str(self.second): self.digest}
        self.approved = {str(self.first): dict(sha256=self.digest, private_copy=str(self.copy))}

    def check(self):
        return gate.historical_files(self.expected, self.approved, copy_root=self.copies)

    def test_present_originals_stay_exact(self):
        result = self.check()
        self.assertEqual(result["original_paths_matched"], 2)
        self.assertEqual(result["original_paths_missing"], [])

    def test_approved_missing_original_keeps_gap_and_checks_copy(self):
        self.first.unlink()
        result = self.check()
        self.assertEqual(result["original_paths_matched"], 1)
        self.assertEqual(result["original_paths_missing"][0]["original_path"], str(self.first))
        self.assertTrue(result["original_paths_missing"][0]["bytes_verified"])
        self.assertFalse(result["complete_runtime_restoration_claimed"])
        self.assertFalse(self.first.exists())

    def test_unknown_missing_original_is_not_covered_by_same_hash(self):
        self.second.unlink()
        with self.assertRaisesRegex(gate.EvidenceMismatch, "Unapproved"):
            self.check()

    def test_changed_original_is_not_hidden_by_good_copy(self):
        self.first.write_bytes(b"changed original")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "original changed"):
            self.check()

    def test_original_directory_is_not_treated_as_missing(self):
        self.first.unlink()
        self.first.mkdir()
        with self.assertRaisesRegex(gate.EvidenceMismatch, "wrong file type"):
            self.check()

    def test_broken_original_symlink_is_not_treated_as_missing(self):
        self.first.unlink()
        self.first.symlink_to(self.root / "absent")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "wrong file type"):
            self.check()

    def test_missing_copy_is_denied(self):
        self.first.unlink()
        self.copy.unlink()
        with self.assertRaisesRegex(gate.EvidenceMismatch, "copy missing"):
            self.check()

    def test_changed_copy_is_denied(self):
        self.first.unlink()
        self.copy.write_bytes(b"changed archive bytes")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "copy changed"):
            self.check()

    def test_wrong_declared_hash_is_denied(self):
        self.approved[str(self.first)]["sha256"] = "0" * 64
        with self.assertRaisesRegex(gate.EvidenceMismatch, "differs from baseline"):
            self.check()

    def test_copy_outside_root_is_denied_even_if_bytes_match(self):
        outside = self.root / self.digest
        outside.write_bytes(self.content)
        self.approved[str(self.first)]["private_copy"] = str(outside)
        with self.assertRaisesRegex(gate.EvidenceMismatch, "location changed"):
            self.check()

    def test_copy_symlink_is_denied_even_if_bytes_match(self):
        self.copy.unlink()
        self.copy.symlink_to(self.second)
        with self.assertRaisesRegex(gate.EvidenceMismatch, "symlink"):
            self.check()

    def test_approval_cannot_add_a_path_outside_baseline(self):
        self.approved[str(self.root / "extra")] = self.approved[str(self.first)]
        with self.assertRaisesRegex(gate.EvidenceMismatch, "unlisted"):
            self.check()

    def test_shared_content_is_deduplicated_without_merging_paths(self):
        self.approved[str(self.second)] = dict(self.approved[str(self.first)])
        self.first.unlink()
        self.second.unlink()
        result = self.check()
        self.assertEqual(len(result["original_paths_missing"]), 2)
        self.assertEqual(result["unique_durable_objects_verified"], 1)

    def test_strict_current_groups_never_use_the_copy_exception(self):
        for category in ["source", "formal data", "runtime", "dependencies"]:
            with self.subTest(category=category, state="missing"):
                self.first.unlink(missing_ok=True)
                with self.assertRaisesRegex(gate.EvidenceMismatch, "missing original"):
                    gate.strict_files({str(self.first): self.digest}, label=category)
            with self.subTest(category=category, state="changed"):
                self.first.write_bytes(b"wrong current bytes")
                with self.assertRaisesRegex(gate.EvidenceMismatch, "changed original"):
                    gate.strict_files({str(self.first): self.digest}, label=category)

    def test_changed_runtime_dependency_link_is_denied(self):
        link = self.root / "python-link"
        link.symlink_to(self.first)
        expected = {"python-link": str(self.first)}
        self.assertEqual(gate.strict_links(self.root, expected), 1)
        link.unlink()
        link.symlink_to(self.second)  # Same bytes do not excuse a changed target.
        with self.assertRaisesRegex(gate.EvidenceMismatch, "dependency links changed"):
            gate.strict_links(self.root, expected)

    def test_missing_or_added_runtime_dependency_link_is_denied(self):
        expected = {"python-link": str(self.first)}
        with self.assertRaisesRegex(gate.EvidenceMismatch, "dependency links changed"):
            gate.strict_links(self.root, expected)
        (self.root / "python-link").symlink_to(self.first)
        (self.root / "extra-link").symlink_to(self.first)
        with self.assertRaisesRegex(gate.EvidenceMismatch, "dependency links changed"):
            gate.strict_links(self.root, expected)

    def make_policy(self):
        expected = {str(self.root / ("old-" + str(i))): self.digest for i in range(753)}
        approved = dict(list(expected.items())[:121])
        mapping = {p: dict(sha256=h, private_copy=str(self.copy)) for p, h in approved.items()}
        documents = dict(baseline=dict(prior_evidence_pins=expected), entry=dict(prior_evidence_pins=dict(missing=approved)),
                         copies=dict(original_path_mapping=mapping), prepared_setup={}, stop={})
        anchors = {}
        for label, document in documents.items():
            path = self.root / (label + ".json")
            path.write_text(json.dumps(document))
            anchors[label] = dict(path=path.name, sha256=gate.sha(path))
        scope = hashlib.sha256(json.dumps(approved, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        policy = dict(schema=1, decision=276, user_answer="用持久副本核验（推荐）", approved_missing_count=121,
            approved_path_hashes_sha256=scope, anchors=anchors, copy_root=str(self.copies),
            no_batch_activation=True, no_frozen_allowance_restore=True)
        path = self.root / "policy.json"
        path.write_text(json.dumps(policy))
        return path, policy, documents

    def test_exact_authorized_policy_loads(self):
        path, _, _ = self.make_policy()
        _, _, expected, mapping = gate.load_authorized_policy(path, self.root)
        self.assertEqual(len(expected), 753)
        self.assertEqual(len(mapping), 121)

    def test_changed_policy_reference_is_denied(self):
        path, _, _ = self.make_policy()
        (self.root / "entry.json").write_text("{}")
        with self.assertRaisesRegex(gate.EvidenceMismatch, "reference changed"):
            gate.load_authorized_policy(path, self.root)

    def test_scope_fingerprint_change_is_denied(self):
        path, policy, _ = self.make_policy()
        policy["approved_path_hashes_sha256"] = "0" * 64
        path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(gate.EvidenceMismatch, "path/hash set changed"):
            gate.load_authorized_policy(path, self.root)

    def test_extra_copy_mapping_is_denied_even_with_updated_reference(self):
        path, policy, docs = self.make_policy()
        docs["copies"]["original_path_mapping"][str(self.root / "old-121")] = dict(sha256=self.digest, private_copy=str(self.copy))
        target = self.root / "copies.json"
        target.write_text(json.dumps(docs["copies"]))
        policy["anchors"]["copies"]["sha256"] = gate.sha(target)
        path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(gate.EvidenceMismatch, "expands or omits"):
            gate.load_authorized_policy(path, self.root)

    def test_changed_baseline_hash_is_denied_even_with_updated_reference(self):
        path, policy, docs = self.make_policy()
        key = next(iter(docs["copies"]["original_path_mapping"]))
        docs["copies"]["original_path_mapping"][key]["sha256"] = "0" * 64
        target = self.root / "copies.json"
        target.write_text(json.dumps(docs["copies"]))
        policy["anchors"]["copies"]["sha256"] = gate.sha(target)
        path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(gate.EvidenceMismatch, "authoritative baseline"):
            gate.load_authorized_policy(path, self.root)

    def test_scope_count_and_startup_permission_cannot_expand(self):
        path, policy, _ = self.make_policy()
        for key, value in [("approved_missing_count", 122), ("no_batch_activation", False), ("no_frozen_allowance_restore", False)]:
            with self.subTest(key=key):
                changed = dict(policy, **{key: value})
                path.write_text(json.dumps(changed))
                with self.assertRaises(gate.EvidenceMismatch):
                    gate.load_authorized_policy(path, self.root)


if __name__ == "__main__":
    unittest.main()
