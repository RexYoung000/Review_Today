"""Prepare a new empty QA after verified restoration; preserve the stopped batch."""
from common import *
_source=PRIOR/'prepare.py'
_text=_source.read_text()
def replace_once(old,new):
    global _text
    assert _text.count(old)==1,old
    _text=_text.replace(old,new,1)
replace_once("    assert files(SUPPORT)==read(ROOT/'output/daily-update-preflight-2026-10-23/after-source-files.json')",
    "    restored=read(ROOT/'docs/evidence/2026-10-23-daily-data-recovery/post-restore-verification.json')\n"
    "    assert restored['status']=='POST_RESTORE_VERIFIED_APP_CLOSED'\n"
    "    assert files(SUPPORT)=={str(SUPPORT/p):h for p,h in restored['files'].items()}")
replace_once("    missing=read(ROOT/'docs/evidence/2026-10-22-navigation-save-real/protection.json')['missing_old_files']",
    "    original_missing=read(ROOT/'docs/evidence/2026-10-22-navigation-save-real/protection.json')['missing_old_files']\n"
    "    gaps=read(OUT/'continuity.json')['additional_missing_old_files']\n"
    "    missing=sorted(set(original_missing)|set(gaps))")
replace_once("    assert len(frozen)==229 and", "    assert len(frozen)==229-len(gaps) and")
replace_once("    runtime=Path(tempfile.mkdtemp(",
    "    legacy=read(PRIOR/'setup.json');continuity=read(OUT/'continuity.json')\n"
    "    gaps=continuity['additional_missing_old_files']\n"
    "    assert {p for p in legacy['frozen_existing_files'] if not Path(p).is_file()}==set(gaps)\n"
    "    for p,h in legacy['frozen_existing_files'].items():\n"
    "        if p not in gaps:assert sha(Path(p))==h;frozen[p]=h\n"
    "    missing=sorted(set(missing)|set(gaps))\n"
    "    for folder in [PRIOR,ROOT/'docs/evidence/2026-10-23-fullflow-real',ROOT/'docs/evidence/2026-10-23-daily-data-recovery',ROOT/'output/fullflow-preflight-2026-10-23']:\n"
    "        frozen.update(files(folder))\n"
    "    runtime=Path(tempfile.mkdtemp(")
replace_once("    state=dict(status='PREPARING_HOLD'",
    "    for p in PRIOR.glob('*.py'):pins[str(p.relative_to(ROOT))]=sha(p)\n"
    "    pins[str((OUT/'continuity.json').relative_to(ROOT))]=sha(OUT/'continuity.json')\n"
    "    state=dict(status='PREPARING_HOLD'")
exec(compile(_text,str(_source),'exec'),globals())
