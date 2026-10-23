"""Exercise actual macOS exclusive rename on disposable fixture directories."""
import errno
import tempfile
from restore import *

spec=check()  # The actual daily target remains absent; no writes there.
fixture=Path(tempfile.mkdtemp(prefix='exclusive-rename-',dir=DURABLE))
source,target=fixture/'source',fixture/'existing'
source.mkdir();target.mkdir();(source/'data').write_text('prepared fixture');(target/'data').write_text('existing fixture')
try:rename_exclusive(source,target)
except OSError as error:assert error.errno in {errno.EEXIST,errno.ENOTEMPTY}
else:raise AssertionError('Existing target was replaced')
assert (source/'data').read_text()=='prepared fixture' and (target/'data').read_text()=='existing fixture'
empty=fixture/'empty';empty.mkdir()
try:rename_exclusive(source,empty)
except OSError as error:assert error.errno in {errno.EEXIST,errno.ENOTEMPTY}
else:raise AssertionError('Existing empty target was replaced')
assert source.exists() and empty.exists()
fresh=fixture/'fresh';rename_exclusive(source,fresh)
assert not source.exists() and (fresh/'data').read_text()=='prepared fixture'
assert not SUPPORT.exists()
write(OUT/'restore-checks.json',dict(status='PASS',actual_macos_exclusive_rename_exercised=True,
    existing_nonempty_target_preserved=True,existing_empty_target_preserved=True,fresh_target_success=True,
    actual_daily_preflight_ready=True,daily_target_not_created=True,app_or_service_not_started=True,actual_model_requests=0,actual_web_operations=0))
print('PASS exclusive rename existing/nonempty, existing/empty and fresh target; daily target untouched.')
