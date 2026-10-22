"""Replace the stopped local Debug App only after the specific activation approval."""
import json
from pathlib import Path
import shutil
import sys

from prepare import DAILY, DATABASES, OUT, PRIVATE, ROOT, SUPPORT, digest, files, signature, stopped, summary, write, command, PROJECT_DIFF


def main():
    assert sys.argv[1:] == ['--install-approved']
    authorization = json.loads((PRIVATE/'activation/authorization.json').read_text())
    assert authorization['status'] == 'approved' and not (PRIVATE/'activation/HOLD').exists()
    assert (authorization['actual_model_request_limit'], authorization['provider_web_operation_limit']) == (8, 0)
    assert not (PRIVATE/'activation/STOP').exists()
    stopped()
    pins = json.loads((OUT/'source-pins.json').read_text())
    assert all(digest((ROOT/name).read_bytes()) == value for name,value in pins.items())
    assert digest(command(['git','diff','--','Review_Today.xcodeproj/project.pbxproj']).stdout.encode()) == PROJECT_DIFF
    backup = json.loads((OUT/'backup.json').read_text())
    candidate = json.loads((OUT/'candidate.json').read_text())
    assert signature(DAILY) == backup['daily_signature']
    assert signature(Path(candidate['app'])) == candidate['signature']
    assert {name:summary(SUPPORT/name) for name in DATABASES} == json.loads((PRIVATE/'before.json').read_text())
    stage = DAILY.with_name('Review_Today.activation-stage.app')
    previous = DAILY.with_name('Review_Today.before-2026-10-22.app')
    assert not stage.exists() and not previous.exists() and not (OUT/'installation.json').exists()
    shutil.copytree(candidate['app'], stage, symlinks=True)
    assert signature(stage) == candidate['signature']
    assert files(stage) == files(Path(candidate['app']))
    stopped()
    DAILY.rename(previous)
    try:
        stage.rename(DAILY)
        assert signature(DAILY) == candidate['signature']
    except BaseException:
        if DAILY.exists():
            DAILY.rename(stage)
        previous.rename(DAILY)
        raise
    write(OUT/'installation.json', dict(status='INSTALLED_NOT_LAUNCHED', installed=str(DAILY),
        previous=str(previous), private_backup=backup['backup'], signature=signature(DAILY),
        copied_files_match=True, actual_model_requests=0, actual_web_operations=0))


if __name__ == '__main__':
    main()
