"""Decision 277: fixed historical copies; no exception for current strict groups."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "2026-10-26-historical-copy-gate/evidence_gate.py"
V1_SHA256 = "41fd297dab3b2ded276b7b20affa1ac34e669251f647ffe5ae5f20e99a21eb16"
POLICY_SHA256 = "4af757e47b7f05b5050f4f3e61f4f6c7d238d67fbf98336cd4fc265ec4a57bdb"
SCOPE_SHA256 = "73e31be9a5fd5a01f54787d3fdf1eaba4a31a960938cc9957187cc57002a589f"

if hashlib.sha256(V1.read_bytes()).hexdigest() != V1_SHA256:
    raise RuntimeError("Frozen decision-276 primitives changed")
spec = importlib.util.spec_from_file_location("decision_276_primitives", V1)
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)
read, sha, require = v1.read, v1.sha, v1.require
strict_files, strict_links = v1.strict_files, v1.strict_links
EvidenceMismatch = v1.EvidenceMismatch


def historical_files(expected, copies, *, copy_root):
    root = Path(copy_root)
    require(root.is_dir() and not root.is_symlink() and root == root.resolve(),
            "Historical copy root missing, redirected or symlinked")
    return v1.historical_files(expected, copies, copy_root=root)


def load_authorized_policy(path, root):
    # Pin the policy itself, so editing both a mapping and its declared scope
    # cannot silently authorize a different same-sized set of missing paths.
    require(sha(path) == POLICY_SHA256, "Decision-277 policy fingerprint changed")
    policy = read(path)
    require(policy["decision"] == 277 and policy["schema"] == 1 and policy["user_answer"] == "ok",
            "Unrecognized offline authority")
    require(all(policy[k] is True for k in ["no_batch_activation", "no_frozen_allowance_restore",
                                           "no_current_group_exceptions"]), "Offline boundary changed")
    documents = {}
    for label, anchor in policy["anchors"].items():
        target = Path(root) / anchor["path"]
        require(target.is_file() and sha(target) == anchor["sha256"], f"Policy reference changed: {label}")
        documents[label] = read(target)
    previous = documents["previous_policy"]
    require(policy["strict_metadata"] == previous["strict_metadata"] and
            policy["stopped_control_files"] == previous["stopped_control_files"], "Strict groups changed")
    expected = documents["baseline"]["prior_evidence_pins"]
    approved = documents["copies"]["approved_missing"]
    mapping = documents["copies"]["original_path_mapping"]
    old = documents["entry"]["prior_evidence_pins"]["missing"]
    scope = hashlib.sha256(json.dumps(approved, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    require(len(expected) == 753 and len(approved) == policy["approved_missing_count"] == 157,
            "Historical baseline or approved count changed")
    require(scope == policy["approved_path_hashes_sha256"] == SCOPE_SHA256, "Approved path/hash set changed")
    require(len(old) == 121 and all(approved.get(p) == h for p, h in old.items()), "Decision-276 scope changed")
    require(set(approved) - set(old) == set(documents["copies"]["new_paths"]), "New path scope changed")
    require(set(mapping) == set(approved) and set(approved).issubset(expected), "Copy mapping expands or omits scope")
    require(all(expected[p] == h == mapping[p]["sha256"] for p, h in approved.items()),
            "Copy mapping differs from authoritative baseline")
    return policy, documents, expected, mapping


def strict_file_report(expected, *, label):
    """Gather every mismatch without changing the original strict-file rule."""
    matched, failures = 0, []
    for name, digest in expected.items():
        try:
            strict_files({name: digest}, label=label)
            matched += 1
        except (EvidenceMismatch, OSError) as error:
            path = Path(name)
            failures.append(dict(path=name, expected_sha256=digest,
                                 state="changed" if path.is_file() else "missing_or_wrong_type",
                                 error=str(error)))
    return dict(status="FAIL" if failures else "PASS", expected=len(expected), matched=matched, failures=failures)


def stopped_runtime_report(runtime, expected, links, files):
    """Missing old controls remain a failure, even when no process is listening."""
    result = strict_file_report(expected, label="Current stopped runtime")
    actual = files(runtime)
    result["inventory_exact"] = actual == expected
    result["extra_paths"] = sorted(set(actual) - set(expected))
    try:
        result["dependency_links_matched"] = strict_links(runtime, links)
        result["dependency_links_exact"] = True
    except EvidenceMismatch as error:
        result["dependency_links_exact"] = False
        result["dependency_link_error"] = str(error)
    if not result["inventory_exact"] or not result["dependency_links_exact"]:
        result["status"] = "FAIL"
    return result


def absent(path):
    # A dangling marker symlink is still an unexpected artifact.
    return not os.path.lexists(path)
