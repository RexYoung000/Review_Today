"""Run the real startup callback on fresh DB copies with the pinned fake SDK.

Uses no HTTP listener and no provider sockets. Does not alter the held real entry.
"""
from pathlib import Path
import json
import shutil
import sqlite3
import sys
import threading
import time
import tempfile
from common import ROOT, OUT, ARCHIVE, write, read, unchanged


def rows(path):
    assert path.is_file()
    with sqlite3.connect(str(path)) as db:
        db.execute("pragma query_only=on")
        db.row_factory = sqlite3.Row
        result = {}
        for name, in db.execute("select name from sqlite_master where type='table' order by name").fetchall():
            values = []
            for row in db.execute('select * from "' + name.replace('"', '""') + '"'):
                item = dict(row)
                for key, value in list(item.items()):
                    if isinstance(value, bytes):
                        item[key] = {"blob": value.hex()}
                    elif key == "payload":
                        item[key] = json.loads(value)
                values.append(item)
            result[name] = sorted(values, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
        return result


def main():
    unchanged()
    source = ROOT / "docs/evidence/2026-10-22-local-app-preflight/probe_checks.py"
    text = source.read_text()
    marker = "quota = install(directory)\n"
    assert text.count(marker) == 1
    # Reuse the exact fixture setup and MockTransport; exclude its test actions.
    # The strict fixture resolves DB filenames; choose its identical canonical
    # temp root first so macOS /var aliases do not look like an external store.
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
    namespace = dict(__file__=str(OUT / "rehearse_startup.py"), __name__="startup_fixture")
    sys.path.insert(0, str(source.parent))
    exec(compile(text.split(marker)[0], str(source), "exec"), namespace)
    directory = namespace["directory"]
    import os
    os.environ["REVIEW_TODAY_REVIEW_DB"] = str(directory / "review.sqlite3")
    os.environ["REVIEW_TODAY_JEV_TEST"] = "0"
    for name in ["checkpoint.sqlite3", "review.sqlite3", "app.store"]:
        shutil.copy2(ARCHIVE / "consistent-databases" / name, directory / name)
    before = {name: rows(directory / name) for name in ["checkpoint.sqlite3", "review.sqlite3", "app.store"]}
    quota = namespace["install"](directory)
    namespace["probes_only"](quota)
    from agent_service import main as actual, model_capabilities
    actual.check_model_capabilities()
    deadline = time.monotonic() + 25
    while (model_capabilities._probing or actual.conversation_harness._workers or actual.conversation_harness._summary_workers
           or any(t.is_alive() and t.name in {"review-today-task-recovery", "review-today-run-recovery", "review-today-model-capabilities"}
                  for t in threading.enumerate())):
        assert time.monotonic() < deadline, "Offline startup did not settle"
        time.sleep(0.1)
    assert len(namespace["wires"]) == 8 and not namespace["denied"]
    assert all(x["status"] == "ready" for x in model_capabilities.snapshot().values())
    after = {name: rows(directory / name) for name in before}
    changed = {name: [table for table in before[name] if before[name][table] != after[name][table]] for name in before}
    assert before["app.store"] == after["app.store"]
    assert before["review.sqlite3"] == after["review.sqlite3"]
    for table in before["checkpoint.sqlite3"]:
        if table != "agent_capability_batches":
            assert before["checkpoint.sqlite3"][table] == after["checkpoint.sqlite3"][table], table
    old = {r["batch_id"]: r for r in before["checkpoint.sqlite3"]["agent_capability_batches"]}
    new = {r["batch_id"]: r for r in after["checkpoint.sqlite3"]["agent_capability_batches"]}
    assert len(new) == len(old) + 1 and all(new[k] == value for k, value in old.items())
    held = read(OUT / "plan.json")
    assert quota.spec["batch_id"] == "offline-probe-only" and held["batch_id"] != quota.spec["batch_id"]
    write(ARCHIVE / "rehearsal-table-observation.json", dict(before=before, after=after, fixture_directory=str(directory)))
    unchanged()
    write(OUT / "startup-rehearsal.json", dict(status="PASS", fixture_directory=str(directory),
        real_startup_callback_executed=True, production_recovery_functions_unmodified=True,
        sdk_fake_requests=8, actual_model_requests=0, actual_web_operations=0,
        socket_attempts=0, app_launched=False, original_formal_databases_opened=False,
        native_and_review_rows_exact=True, all_existing_service_rows_logically_unchanged=True,
        changed_tables=changed, only_one_new_capability_batch=True,
        real_batch_authorization_untouched=True, raw_observation_private=True))
    print("PASS real startup on copied daily stores: 8 fake SDK requests, original rows unchanged, one new fake readiness batch; real 0/0.")


if __name__ == "__main__":
    main()
