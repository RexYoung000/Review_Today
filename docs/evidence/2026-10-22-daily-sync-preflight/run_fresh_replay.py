"""Reuse the pinned implementation check with only fresh input/output locations."""
import json
import shutil
from pathlib import Path
from prepare import ROOT, OUT, PRIVATE, sha, write

source = ROOT/'docs/evidence/2026-10-22-legacy-lifecycle-repair/verify_isolated.py'
manifest = json.loads((source.parent/'manifest.json').read_text())
assert sha(source)==manifest[source.name]
prior = json.loads((source.parent/'result.json').read_text())
driver = ROOT/'output/deletion-queue-audit-2026-10-22/NativeQueueAudit'
assert sha(driver)==prior['native_driver_sha256']
shutil.copy2(driver,PRIVATE/'fresh-input/NativeQueueAudit')
text = source.read_text()
old = "INPUT = ROOT/'output/deletion-queue-audit-2026-10-22'"
assert text.count(old)==1
text = text.replace(old,'INPUT = Path('+repr(str(PRIVATE/'fresh-input'))+')')
assert text.count('OUT = Path(__file__).parent')==1
text = text.replace('OUT = Path(__file__).parent','OUT = Path('+repr(str(OUT))+')')
assert not (OUT/'replay-result.json').exists()
exec(compile(text,str(source),'exec'),dict(__name__='__main__',__file__=str(source)))
(OUT/'result.json').rename(OUT/'replay-result.json')
write(OUT/'replay-adapter.json',dict(source=str(source.relative_to(ROOT)),source_sha256=sha(source),
    changed_assignments=['INPUT','OUT'],production_or_fixture_logic_changed=False))
