"""Byte checks for the specifically approved historical-copy exception.

This module grants no startup or provider permission and imports no service.
"""
import hashlib
import json
import os
from pathlib import Path


class EvidenceMismatch(RuntimeError):
    pass


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise EvidenceMismatch(message)


def strict_files(expected, *, label):
    """No durable-copy fallback exists for any current/strict file group."""
    for name, digest in expected.items():
        path = Path(name)
        require(path.is_file(), f"{label}: missing original file: {path}")
        require(sha(path) == digest, f"{label}: changed original file: {path}")
    return len(expected)


def strict_links(directory, expected):
    directory = Path(directory)
    actual = {str(p.relative_to(directory)): os.readlink(p) for p in directory.rglob("*") if p.is_symlink()}
    require(actual == expected, "Current runtime dependency links changed, missing or added")
    return len(actual)


def historical_files(expected, approved_copies, *, copy_root):
    """Only callers' policy-verified paths may use the exact pinned objects."""
    require(set(approved_copies).issubset(expected), "Exception includes an unlisted historical path")
    root = Path(copy_root).resolve()
    verified = {}
    for name, receipt in approved_copies.items():
        digest = expected[name]
        require(receipt["sha256"] == digest, f"Approved copy hash differs from baseline: {name}")
        target = Path(receipt["private_copy"])
        require(target == root / digest, f"Approved copy location changed: {name}")
        require(not target.is_symlink(), f"Approved copy is a symlink: {name}")
        require(target.is_file(), f"Approved durable copy missing: {name}")
        require(target.resolve().parent == root, f"Approved copy outside fixed root: {name}")
        if digest not in verified:
            require(sha(target) == digest, f"Approved durable copy changed: {name}")
            verified[digest] = str(target)
    matched, missing = 0, []
    for name, digest in expected.items():
        path = Path(name)
        if path.exists() or path.is_symlink():
            # A bad original must never be hidden by a good archive copy.
            require(path.is_file(), f"Historical original has wrong file type: {name}")
            require(sha(path) == digest, f"Historical original changed: {name}")
            matched += 1
        else:
            require(name in approved_copies, f"Unapproved historical original missing: {name}")
            missing.append(dict(original_path=name, sha256=digest, durable_copy=verified[digest],
                                original_path_missing=True, bytes_verified=True))
    return dict(expected_paths=len(expected), original_paths_matched=matched,
        original_paths_missing=missing, durable_paths_verified=len(approved_copies),
        unique_durable_objects_verified=len(verified),
        original_missing_fact_retained=True, complete_runtime_restoration_claimed=False)


def load_authorized_policy(path, root):
    policy = read(path)
    require(policy.get("schema") == 1 and policy.get("decision") == 276, "Unrecognized policy authority")
    require(policy.get("user_answer") == "用持久副本核验（推荐）", "Approval answer changed")
    require(policy.get("approved_missing_count") == 121, "Approved exception count changed")
    require(policy.get("no_batch_activation") is True and policy.get("no_frozen_allowance_restore") is True,
            "Policy must not grant startup or restore a frozen allowance")
    documents = {}
    for label, anchor in policy["anchors"].items():
        target = Path(root) / anchor["path"]
        require(target.is_file() and sha(target) == anchor["sha256"], f"Policy reference changed: {label}")
        documents[label] = read(target)
    expected = documents["baseline"]["prior_evidence_pins"]
    approved = documents["entry"]["prior_evidence_pins"]["missing"]
    mapping = documents["copies"]["original_path_mapping"]
    scope = hashlib.sha256(json.dumps(approved, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    require(len(expected) == 753 and len(approved) == 121, "Historical baseline or exception scope changed")
    require(scope == policy["approved_path_hashes_sha256"], "Approved path/hash set changed")
    require(set(mapping) == set(approved), "Copy mapping expands or omits the approved paths")
    require(all(expected.get(p) == h and mapping[p]["sha256"] == h for p, h in approved.items()),
            "Copy mapping differs from authoritative baseline")
    return policy, documents, expected, mapping
