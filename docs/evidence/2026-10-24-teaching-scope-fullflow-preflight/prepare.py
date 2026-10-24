"""Prepare a new held QA using current verified source and closed-daily observation."""
from common import *

_source = ROOT / 'docs/evidence/2026-10-23-fullflow-preflight/prepare.py'
_text = _source.read_text()


def replace_once(old, new):
    global _text
    assert _text.count(old) == 1, old
    _text = _text.replace(old, new, 1)


replace_once("    assert not (OUT/'setup.json').exists() and not DURABLE.exists(),'Never reset an existing QA'",
    "    assert not (OUT/'setup.json').exists() and (DURABLE/'entry-baseline.json').exists(),'Never reset an existing QA'")
replace_once("    stopped();PRIVATE.mkdir(mode=0o700);DURABLE.mkdir(parents=True,mode=0o700)",
    "    stopped();assert PRIVATE.is_dir() and DURABLE.is_dir()\n    entry=read(OUT/'entry-baseline.json')")
replace_once("    baseline=read(ROOT/'docs/evidence/2026-10-23-daily-update-preflight/source-pins.json')",
    "    baseline=entry['source_config_pins']")
replace_once("    assert files(SUPPORT)==read(ROOT/'output/daily-update-preflight-2026-10-23/after-source-files.json')",
    "    assert files(SUPPORT)==entry['daily_files']")
_start = _text.index("    old=read(")
_end = _text.index("    runtime=Path(tempfile.mkdtemp(")
_text = _text[:_start] + """    legacy=read(PRIOR/'setup.json')
    frozen=dict(legacy['frozen_existing_files'])
    missing=entry['known_missing_old_paths']
    assert all(not Path(p).exists() for p in missing)
    assert all(Path(p).is_file() and sha(Path(p))==h for p,h in frozen.items())
    for folder in [PRIOR,ROOT/'docs/evidence/2026-10-24-fullflow-real',ROOT/'docs/evidence/2026-10-24-teaching-scope-repair']:
        frozen.update(files(folder))
    prior_durable=Path(read(ROOT/'docs/evidence/2026-10-24-fullflow-real/archive.json')['archive']).parent
    frozen.update(files(prior_durable))
    for p in [Path(legacy['directory'])/'authorization.json',Path(legacy['directory'])/'quota.json',Path(legacy['directory'])/'STOP']:
        frozen[str(p)]=sha(p)
    frozen[str(DURABLE/'daily-closed-observation.zip')]=sha(DURABLE/'daily-closed-observation.zip')
""" + _text[_end:]
replace_once("prefix='review-today-fresh-fullflow-'", "prefix='review-today-teaching-scope-fullflow-'")
replace_once("    state=dict(status='PREPARING_HOLD'",
    "    for p in [OUT/'entry-baseline.json',OUT/'environment.json']:pins[str(p.relative_to(ROOT))]=sha(p)\n"
    "    state=dict(status='PREPARING_HOLD'")
exec(compile(_text, str(_source), 'exec'), globals())
