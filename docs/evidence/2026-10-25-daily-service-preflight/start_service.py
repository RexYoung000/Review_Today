"""One held service-only startup; never launches or replaces the daily App."""
from pathlib import Path
import os
import sys
from common import ROOT, OUT, PRIVATE, SUPPORT, read, write, sha
from approval import require_approved


def main():
    spec = require_approved()  # Must run before any SDK/service/database import.
    directory = PRIVATE / "activation"
    write(PRIVATE / "execution.json", dict(phase="startup_admitted", batch_id=spec["batch_id"]))
    sys.path.insert(0, str(ROOT / "agent-service"))
    sys.path.insert(0, str(ROOT / "docs/evidence/2026-10-22-local-app-preflight"))
    import quota_activation
    quota_activation.Quota(directory)
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(SUPPORT / "agent-harness.sqlite3"),
                      REVIEW_TODAY_REVIEW_DB=str(SUPPORT / "agent-harness.review.sqlite3"),
                      REVIEW_TODAY_SERVICE_PORT="8742", REVIEW_TODAY_JEV_TEST="0",
                      REVIEW_TODAY_BROWSER_FALLBACK="1")
    quota = quota_activation.install(directory)
    quota_activation.probes_only(quota)
    from agent_service import config
    assert Path(config.HARNESS_DB).resolve() == SUPPORT / "agent-harness.sqlite3"
    assert config.PORT == 8742
    from agent_service.main import run
    delta = read(OUT / "source-delta.json")["backend_delta"]
    loaded = {name: str(Path(sys.modules["agent_service." + Path(name).stem].__file__).resolve())
              for name in delta if "agent_service." + Path(name).stem in sys.modules}
    assert all(path == str((ROOT / name).resolve()) for name, path in loaded.items())
    write(directory / "bootstrap-ready.json", dict(pid=os.getpid(), batch_id=spec["batch_id"],
        model_limit=8, web_limit=0, probes_only=True, daily_app_will_remain_closed=True,
        loaded_repair_module_paths=loaded,
        repair_source_fingerprints={name: sha(ROOT / name) for name in delta}))
    write(PRIVATE / "execution.json", dict(phase="service_started", batch_id=spec["batch_id"]))
    run()


if __name__ == "__main__":
    main()
