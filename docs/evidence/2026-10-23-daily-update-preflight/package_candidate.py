"""Verify and archive the normal signed build; do not install or execute it."""
from pathlib import Path
import re
import shutil
import subprocess
from common import ROOT, OUT, PRIVATE, ARCHIVE, BUILD, DAILY, LS, write, sha, inventory, stopped, prior_helpers, unchanged


def main():
    stopped(); unchanged()
    assert '** BUILD SUCCEEDED **' in (PRIVATE / 'build.log').read_text()
    assert not (OUT / 'candidate.json').exists()
    app = BUILD / 'Build/Products/Debug/Review_Today.app'
    contents = inventory(app)
    helpers = prior_helpers(); signature = helpers.signature(app)
    bundle = ARCHIVE / 'ReviewToday-candidate.zip'
    assert not bundle.exists()
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(bundle)], check=True)
    check = ARCHIVE / 'candidate-check.noindex'; check.mkdir()
    subprocess.run(['ditto', '-x', '-k', str(bundle), str(check)], check=True)
    restored = check / app.name
    assert inventory(restored) == contents and helpers.signature(restored) == signature
    subprocess.run([LS, '-u', str(app)], capture_output=True)
    shutil.rmtree(check); shutil.rmtree(app)
    dump = subprocess.check_output([LS, '-dump'], text=True)
    (PRIVATE / 'registrations-before-update.txt').write_text(dump)
    identifiers = re.findall(r'^identifier:\s*(.*)$', dump, re.M)
    registered = sum(bool(re.search(r'review[-_]?today', value, re.I)) for value in identifiers)
    assert registered == 1
    unchanged()
    write(OUT / 'candidate.json', dict(status='SIGNED_NORMAL_BUILD_ARCHIVED_NOT_INSTALLED', zip=str(bundle),
        zip_sha256=sha(bundle), signature=signature, inventory=contents, actual_extract_permissions_and_signature_verified=True,
        raw_candidate_removed=True, related_registered_entries=registered, app_source_delta=['Review_Today/KnowledgeLexicon.swift'],
        backend_source_delta=subprocess.check_output(['git', 'diff', '--name-only', '049aa41', 'HEAD', '--', 'agent-service/agent_service'], text=True).splitlines(),
        daily_app_updated=False, daily_app_started=False, actual_new_model_requests=0, actual_new_web_operations=0))
    print('Signed candidate verified by actual extraction; no App execution or installation.')


if __name__ == '__main__': main()
