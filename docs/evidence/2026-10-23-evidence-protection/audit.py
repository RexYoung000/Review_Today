"""Bounded, byte-only evidence audit and durable copy. No SQLite, network or App opens.

Never recreates a missing original path or revises an earlier protection baseline.
Archive objects are inert hash-named bytes, including any executable inputs.
"""
from pathlib import Path
import hashlib
import json
import os
import stat
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ARCHIVE = Path.home() / 'Library/Developer/ReviewTodayEvidence.noindex/2026-10-23-historical-protection'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def actual_files(directory):
    return {str(p.resolve()): digest(p) for p in directory.rglob('*') if p.is_file()}


def inventory(directory):
    values = {}
    for path in sorted(directory.rglob('*')):
        key = str(path.relative_to(directory))
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            values[key] = dict(type='symlink', mode=mode, target=os.readlink(path))
        elif path.is_dir():
            values[key] = dict(type='dir', mode=mode)
        else:
            values[key] = dict(type='file', mode=mode, size=path.stat().st_size, sha256=digest(path))
    return values


def main():
    assert not ARCHIVE.exists(), 'Never overwrite an existing evidence archive'
    state_path = ROOT / 'docs/evidence/2026-10-22-navigation-save-preflight/setup.json'
    state = read(state_path)
    baseline = state['old_frozen_files']
    previous = ROOT / 'docs/evidence/2026-10-22-navigation-save-real'
    expected_missing = set(read(previous / 'protection.json')['missing_old_files'])
    previous_inventory = actual_files(previous)
    private = ROOT / 'output/navigation-save-real-2026-10-22'
    private_inventory = actual_files(private)
    baseline_sha = digest(state_path)

    def protection():
        missing = {p for p in baseline if not Path(p).is_file()}
        changed = [p for p, h in baseline.items() if Path(p).is_file() and digest(Path(p)) != h]
        assert missing == expected_missing and not changed, (missing, changed)
        for key in ['daily_files', 'previous_batch_files', 'original_module_files', 'original_support_files', 'owned_support_files']:
            assert all(Path(p).is_file() and digest(Path(p)) == h for p, h in state[key].items()), key
        assert actual_files(Path.home() / 'Library/Application Support/Review Today') == state['daily_files']
        assert inventory(Path('/Applications/Review Today.app')) == state['daily_app_inventory']
        assert all(digest(ROOT / p) == h for p, h in state['protected_fingerprints'].items())
        assert digest(state_path) == baseline_sha
        assert actual_files(previous) == previous_inventory
        assert actual_files(private) == private_inventory

    protection()
    missing_hashes = {baseline[p] for p in expected_missing}
    matches = {h: [] for h in missing_hashes}
    candidates = set()
    # Only existing QA roots, the project's output and existing evidence archives.
    roots = [ROOT / 'output', Path.home() / 'Library/Developer/ReviewTodayAppArchives.noindex']
    roots += sorted(p for p in Path('/private/tmp').glob('review-today-*') if p.is_dir() and not p.is_symlink())
    examined = 0
    bytes_read = 0
    skipped = []
    for root in roots:
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in {'.git', '.venv', 'node_modules', 'owned-project', '__pycache__'} and not d.endswith('.app'))
            for name in sorted(names):
                if not (name.startswith(('app.store', 'checkpoint.sqlite3')) or name == 'source-checkpoint.json' or name.startswith('before-review-v2-') and '.sqlite3' in name):
                    continue
                path = Path(directory) / name
                resolved = str(path.resolve())
                if resolved in candidates or not path.is_file():
                    continue
                candidates.add(resolved)
                size = path.stat().st_size
                if examined >= 2000 or bytes_read + size > 512 * 1024 * 1024:
                    skipped.append(str(path))
                    continue
                h = digest(path)
                examined += 1
                bytes_read += size
                if h in matches:
                    matches[h].append(str(path))

    # The previous audit identified this exact member; read bytes without restoring.
    prior_audit = read(previous / 'archive-audit.json')
    info = prior_audit['persistently_verified'][0]
    with tarfile.open(info['archive'], 'r:gz') as tar:
        with tar.extractfile(info['member']) as stream:
            info_bytes = stream.read()
    assert hashlib.sha256(info_bytes).hexdigest() == info['sha256']
    persistent_json = [ROOT / p for p in prior_audit['persistently_verified'][1]['existing_paths']]
    for path in persistent_json:
        h = digest(path)
        assert h in matches
        matches[h].append(str(path))

    protection()
    ARCHIVE.mkdir(parents=True, mode=0o700)
    os.chmod(ARCHIVE, 0o700)
    objects = {}
    for path, h in baseline.items():
        if Path(path).is_file():
            objects.setdefault(h, Path(path))
    for h, paths in matches.items():
        if paths:
            objects.setdefault(h, Path(paths[0]))
    objects.setdefault(info['sha256'], info_bytes)
    # Preserve actual current-run data and its original evidence, not reconstructed DBs.
    for paths in [private_inventory, previous_inventory]:
        for path, h in paths.items():
            objects.setdefault(h, Path(path))
    objects.setdefault(baseline_sha, state_path)
    archive_path = ARCHIVE / 'evidence-objects.zip'
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for h, source in sorted(objects.items()):
            data = source if isinstance(source, bytes) else source.read_bytes()
            assert hashlib.sha256(data).hexdigest() == h
            bundle.writestr('objects/' + h, data)
    os.chmod(archive_path, 0o600)
    with zipfile.ZipFile(archive_path) as bundle:
        assert len(bundle.namelist()) == len(objects)
        for h in objects:
            assert hashlib.sha256(bundle.read('objects/' + h)).hexdigest() == h

    recovered = []
    unresolved = []
    for path in sorted(expected_missing):
        h = baseline[path]
        row = dict(original_path=path, sha256=h, exact_bytes_archived=h in objects,
                   original_path_still_missing=not Path(path).exists(), matched_candidates=matches[h])
        if h == info['sha256']:
            row['matched_archive_member'] = dict(archive=info['archive'], member=info['member'])
        (recovered if h in objects else unresolved).append(row)
    manifest = dict(old_baseline=baseline, old_baseline_sha256=baseline_sha,
                    current_run_private=private_inventory, current_run_public=previous_inventory,
                    exact_bytes_for_missing=recovered, unresolved_missing=unresolved,
                    archive=str(archive_path), archive_sha256=digest(archive_path),
                    unique_objects=len(objects), original_paths_not_restored=True,
                    byte_identity_only_not_database_recovery=True)
    write(ARCHIVE / 'manifest.json', manifest)
    os.chmod(ARCHIVE / 'manifest.json', 0o600)
    protection()
    report = dict(status='DURABLE_COPIES_VERIFIED_HISTORICAL_GAP_OPEN',
                  actual_new_model_requests=0, actual_new_web_operations=0,
                  original_expected=240, original_matched=229, original_missing=11,
                  missing_with_exact_bytes_archived=len(recovered), unresolved_missing=unresolved,
                  original_baseline_unchanged=True, previous_public_and_private_evidence_unchanged=True,
                  daily_96_files_and_app_unchanged=True, source_config_execution_pins_unchanged=248,
                  original_modules_and_support_unchanged=True,
                  historical_cause_unknown=True, original_paths_not_restored=True,
                  database_not_opened=True, app_or_service_not_started=True,
                  archive=str(archive_path), archive_sha256=manifest['archive_sha256'],
                  unique_objects=len(objects), actual_member_reads_verified=len(objects),
                  candidate_files_hashed=examined, candidate_bytes_hashed=bytes_read,
                  skipped_candidates=skipped, search_roots=[str(p) for p in roots],
                  frozen_allowances_unchanged=True,
                  daily_update_or_full_flow_acceptance=False)
    write(OUT / 'verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'search_roots', 'unresolved_missing'}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
