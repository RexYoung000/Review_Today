"""Do not open the original daily stores or import the service while pending."""
from common import OUT, PRIVATE, ROOT, DAILY, SUPPORT, read, sha, inventory, stopped


def require_approved():
    directory = PRIVATE / "activation"
    spec = read(directory / "authorization.json")
    if spec.get("status") != "approved" or (directory / "HOLD").exists() or (directory / "STOP").exists():
        raise PermissionError("New service-only 8/0 startup is pending explicit approval")
    plan = read(OUT / "plan.json")
    expected = dict(batch_id=plan["batch_id"], actual_model_request_limit=8,
                    provider_web_operation_limit=0, daily_app=str(DAILY),
                    database_path=str(SUPPORT / "agent-harness.sqlite3"), scope=plan["scope"])
    if any(spec.get(k) != v for k, v in expected.items()):
        raise PermissionError("Startup scope, paths, batch or limits differ from the reviewed plan")
    if spec.get("plan_sha256") != sha(OUT / "plan.json"):
        raise PermissionError("Reviewed plan changed")
    pins = read(OUT / "source-pins.json")
    if not all(sha(ROOT / p) == h for p, h in pins.items()):
        raise PermissionError("Prepared source, configuration or execution input changed")
    state = read(OUT / "setup.json")
    stopped()
    if inventory(DAILY) != state["daily_app_inventory"]:
        raise PermissionError("The unchanged daily App differs from preparation")
    from common import files
    if files(SUPPORT) != state["daily_files"]:
        raise PermissionError("Daily data changed; do not use the old prepared backup")
    if (PRIVATE / "execution.json").exists():
        raise PermissionError("This single-start batch has already been started")
    return spec
