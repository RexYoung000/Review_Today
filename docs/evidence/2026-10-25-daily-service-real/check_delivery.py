"""Offline delivery checks and a small recoverable public evidence snapshot."""
import ast
from collections import Counter
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit
import zipfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(OUT))
from verify import protected, ACTIVATION, ACTUAL, ARCHIVE, PRIVATE, read, write, sha, files


def anchors(path):
    text = path.read_text()
    values = set(re.findall(r'<(?:a|span)\s+[^>]*id=["\']([^"\']+)', text))
    counts = Counter()
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        number = counts[slug]
        counts[slug] += 1
        values.add(slug + ("-" + str(number) if number else ""))
    return values


def main():
    state, pins = protected()
    assert read(OUT / "verification.json")["status"] == "PASS_SERVICE_ONLY_STARTUP_CLOSED"
    archive = read(OUT / "archive.json")
    assert archive["every_member_stream_read_and_matched"] and archive["member_count"] == 27
    assert sha(Path(archive["archive"])) == archive["sha256"]
    quota = read(ACTIVATION / "quota.json")
    assert quota == read(OUT / "quota-final.json")
    assert quota["closed"] and quota["model_requests"] == 8 and quota["web_operations"] == 0
    batch = read(OUT / "capability-batch.json")
    assert all(c["status"] == "returned" for c in batch["calls"])
    assert files(Path.home() / "Library/Application Support/Review Today") == read(ACTUAL / "after-file-pins.json")
    assert sha(ROOT / "Review_Today.xcodeproj/project.pbxproj") == "ab9f204e3bd83a413ba1f9ff684e9359f187ee3188cd3ebca807b4966fb48cca"
    parsed_py = list(OUT.glob("*.py"))
    for path in parsed_py:
        ast.parse(path.read_text(), filename=str(path))
    parsed_json = list(OUT.glob("*.json"))
    for path in parsed_json:
        read(path)
    documents = [ROOT / p for p in ["README.md", "docs/work-status.md", "docs/agent-iteration.md",
                 "docs/decision-log.md", "docs/design-references/zcode-agent.md"]] + [OUT / "README.md"]
    errors, checked = [], 0
    for path in documents:
        for target in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)", path.read_text()):
            target = target.strip().strip("<>")
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                continue
            dest = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            checked += 1
            if not dest.exists():
                errors.append(str(path.relative_to(ROOT)) + ": missing " + target)
            elif parts.fragment and dest.suffix == ".md" and unquote(parts.fragment) not in anchors(dest):
                errors.append(str(path.relative_to(ROOT)) + ": missing anchor " + target)
    assert not errors, errors
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
    write(OUT / "document-check.json", dict(status="PASS", local_links_and_anchors_checked=checked,
        errors=errors, python_files_parsed=len(parsed_py), json_files_parsed=len(parsed_json),
        source_config_execution_pins_unchanged=len(pins), old_evidence_pins_unchanged=len(state["prior_evidence_pins"]),
        formal_files_match_post_close_observation=True, all_eight_call_statuses_returned=True,
        user_project_diff_and_file_preserved=True, private_runtime_members_read=archive["member_count"],
        actual_model_requests=8, actual_web_operations=0, additional_provider_requests=0,
        app_and_service_remain_closed=True))
    artifacts = {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact-sha256.json"}
    write(OUT / "artifact-sha256.json", artifacts)
    package = ARCHIVE / "actual-public-records.zip"
    assert not package.exists()
    public = {p.name: sha(p) for p in OUT.iterdir() if p.is_file()}
    with zipfile.ZipFile(package, "x", zipfile.ZIP_DEFLATED) as z:
        for name in public:
            z.write(OUT / name, name)
    with zipfile.ZipFile(package) as z:
        assert set(z.namelist()) == set(public)
        for name, digest in public.items():
            with z.open(name) as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    write(ARCHIVE / "actual-public-records-manifest.json", dict(archive=str(package), sha256=sha(package), members=public,
          every_member_stream_read_and_matched=True))
    print(f"PASS: {checked} local links/anchors, {len(parsed_py)} Python and {len(parsed_json)} JSON files; source/old evidence/data preserved; public snapshot {len(public)} members read-verified; real 8/0 closed.")


if __name__ == "__main__":
    main()
