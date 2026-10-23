"""Controlled filesystem/approval checks. No live authorization or App execution."""
from pathlib import Path
import copy
import json
import shutil
import subprocess
import sys
import types
import zipfile
from common import ROOT, OUT, PRIVATE, ARCHIVE, DAILY, read, write, sha, inventory, unchanged
import approval
import install_prepared as installer


def main():
    real_run = subprocess.run
    denied = []
    def audit(event, args):
        if event in {'socket.connect', 'sqlite3.connect'}:
            denied.append(event)
            raise AssertionError('No network or database may be opened by execution checks')
    sys.addaudithook(audit)
    unchanged()
    before_auth = {str(p): sha(p) for p in (PRIVATE / 'activation').iterdir()}
    baseline = read(PRIVATE / 'source-protection.json')['daily_app_inventory']
    case_root = ARCHIVE / 'execution-checks.noindex'; case_root.mkdir()
    authorization_checks = []
    auth_case = case_root / 'authorization'; (auth_case / 'activation').mkdir(parents=True)
    base = read(PRIVATE / 'activation/authorization.json'); base['status'] = 'approved'
    real_private, real_out = approval.PRIVATE, approval.OUT
    approval.PRIVATE, approval.OUT = auth_case, OUT
    def auth_case_check(label, change=None, marker=None):
        spec = copy.deepcopy(base)
        if change: spec.update(change)
        write(auth_case / 'activation/authorization.json', spec)
        if marker: (auth_case / 'activation' / marker).write_text('fixture marker\n')
        try:
            try: approval.require_approved()
            except PermissionError: blocked = True
            else: blocked = False
            assert blocked == (label != 'valid_fixture'), label
            authorization_checks.append(dict(case=label, blocked=blocked))
        finally:
            if marker: (auth_case / 'activation' / marker).unlink()
    for label, change, marker in [
        ('valid_fixture', None, None), ('pending', dict(status='pending'), None),
        ('hold', None, 'HOLD'), ('stop', None, 'STOP'),
        ('wrong_model_limit', dict(actual_model_request_limit=9), None),
        ('wrong_web_limit', dict(provider_web_operation_limit=1), None),
        ('wrong_batch', dict(batch_id='different-fixture'), None),
        ('wrong_app', dict(daily_app='/tmp/unreviewed.app'), None),
        ('wrong_database', dict(database_path='/tmp/unreviewed.sqlite3'), None),
        ('wrong_scope', dict(scope='unreviewed cleanup'), None)]:
        auth_case_check(label, change, marker)
    approval.PRIVATE, approval.OUT = real_private, real_out
    checks = []
    original_installer = {name: getattr(installer, name) for name in
        ['PRIVATE', 'OUT', 'ARCHIVE', 'DAILY', 'LS', 'require_approved', 'unchanged', 'prior_helpers']}
    original_argv = sys.argv
    helpers = installer.prior_helpers()
    registered = []
    def scoped_run(args, *pos, **kwargs):
        if args[0] == '__fixture_lsregister__':
            registered.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=b'', stderr=b'')
        return real_run(args, *pos, **kwargs)
    for failure in [False, True]:
        case = case_root / ('rollback' if failure else 'success'); case.mkdir()
        private = case / 'private'; private.mkdir()
        fixture_out = case / 'public'; fixture_out.mkdir()
        for name in ['candidate.json', 'backup.json']:
            shutil.copy2(OUT / name, fixture_out / name)
        archive = case / 'archive'; archive.mkdir()
        daily_parent = case / 'canonical'; daily_parent.mkdir()
        old_zip = read(OUT / 'backup.json')['daily_app_archive']
        real_run(['ditto', '-x', '-k', old_zip, str(daily_parent)], check=True)
        daily = daily_parent / DAILY.name
        assert inventory(daily) == baseline
        write(private / 'source-protection.json', dict(daily_app_inventory=baseline))
        write(private / 'backup-pins.json', read(PRIVATE / 'backup-pins.json'))
        installer.PRIVATE, installer.OUT, installer.ARCHIVE, installer.DAILY = private, fixture_out, archive, daily
        installer.LS = '__fixture_lsregister__'
        installer.require_approved = lambda: dict(batch_id='controlled-filesystem-fixture')
        def check_current():
            unchanged()
            assert inventory(daily) == baseline
        installer.unchanged = check_current
        def check_signature(path):
            if failure and path == daily:
                raise RuntimeError('Controlled signature failure after replacement')
            return helpers.signature(path)
        installer.prior_helpers = lambda: types.SimpleNamespace(signature=check_signature)
        sys.argv = ['install_prepared.py', '--install-approved']
        subprocess.run = scoped_run
        try:
            installer.main()
            assert not failure
            assert inventory(daily) == read(OUT / 'candidate.json')['inventory']
            assert read(private / 'execution.json')['phase'] == 'installed_not_started'
        except RuntimeError as error:
            assert failure and str(error).startswith('Controlled signature failure')
            assert inventory(daily) == baseline
            assert read(private / 'execution.json')['phase'] == 'replacement_failed_old_app_restored'
        finally:
            subprocess.run = real_run
        checks.append(dict(case='failure_rollback' if failure else 'success', real_ditto_and_signature=True,
                           daily_target_replaced_with_owned_fixture=True, registration_stubbed=True, passed=True))
    for name, value in original_installer.items(): setattr(installer, name, value)
    sys.argv = original_argv
    assert not denied and all(sha(Path(p)) == h for p, h in before_auth.items())
    assert not (PRIVATE / 'execution.json').exists() and not (OUT / 'installation.json').exists()
    unchanged()
    # Keep fixture evidence inert; no extra raw Apps remain after these checks.
    fingerprints = {str(p.relative_to(case_root)): sha(p) for p in case_root.rglob('*') if p.is_file()}
    bundle = ARCHIVE / 'execution-checks.zip'
    with zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_DEFLATED) as stream:
        for name in fingerprints: stream.write(case_root / name, name)
    with zipfile.ZipFile(bundle) as stream:
        import hashlib
        for name, h in fingerprints.items(): assert hashlib.sha256(stream.read(name)).hexdigest() == h
    shutil.rmtree(case_root)
    report = dict(status='PASS_CONTROLLED_EXECUTION_NOT_APPLIED', authorization_cases=authorization_checks,
        filesystem_cases=checks, actual_authorization_unchanged=True, actual_daily_app_and_data_unchanged=True,
        actual_installation_not_performed=True, no_execution_or_quota_created=True,
        fake_registration_calls=len(registered), fixture_archive_members_verified=len(fingerprints),
        archive=str(bundle), archive_sha256=sha(bundle), actual_new_model_requests=0, actual_new_web_operations=0)
    write(OUT / 'execution-checks.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
