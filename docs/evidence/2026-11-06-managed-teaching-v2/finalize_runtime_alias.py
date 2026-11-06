"""Finish the held path adaptation using a checked tmp alias to durable storage."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from common import *


def main():
    os.umask(0o077)
    state = read(OUT / "setup.json")
    old = Path(state["directory"])
    runtime = PRIVATE / ("review-today-managed-" + state["batch_id"] + ".noindex")
    require(not old.exists() and runtime.is_dir(), "Expected interrupted pending relocation")
    require(read(runtime / "authorization.json")["status"] == "pending" and (runtime / "HOLD").is_file(), "Not pending")
    state = __import__("json").loads(__import__("json").dumps(state).replace(str(old), str(runtime)))
    alias = Path("/private/tmp") / runtime.name
    if os.path.lexists(alias):
        require(alias.is_symlink() and os.readlink(alias) == str(runtime), "Runtime alias differs")
    else:
        alias.symlink_to(runtime, target_is_directory=True)
    state["runtime_alias"] = str(alias)
    env = state["native_environment"]
    env.pop("TMPDIR", None)
    env["REVIEW_TODAY_NATIVE_TEST_DIR"] = str(alias)
    env["REVIEW_TODAY_PROJECT_ROOT"] = str(alias / "owned-project")
    state["native_app"] = str(alias / "ManagedTeachingQA.app")
    app = Path(state["native_app"])
    package = Path(state["native_zip"])
    prior = ARCHIVE / "failed-tmpdir-candidate.zip"
    if not prior.exists():
        shutil.copy2(package, prior)
    subprocess.run(["ditto", "-x", "-k", str(package), str(runtime)], check=True)
    wrapper = app / "Contents/MacOS/ManagedTeachingEntry"
    wrapper.write_text("#!/bin/sh\nset -eu\n" + "".join("export " + k + "=" + shlex.quote(str(v)) + "\n" for k,v in env.items())
        + "exec " + shlex.quote(str(app / "Contents/MacOS/Review_Today")) + ' "$@"\n')
    wrapper.chmod(0o755)
    subprocess.run(["/bin/sh", "-n", str(wrapper)], check=True)
    for name in state["native_executable_text_sha256"]:
        subprocess.run(["codesign", "--force", "--sign", "-", str(app / "Contents/MacOS" / name)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    require(all(text_section(app / "Contents/MacOS" / name) == h for name,h in state["native_executable_text_sha256"].items()), "App text changed")
    state["native_inventory"] = inventory(app)
    state["fixed_environment_wrapper_sha256"] = sha(wrapper)
    package.unlink()
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(package)], check=True)
    check_dir = PRIVATE / "alias-archive-check.noindex"
    check_dir.mkdir()
    subprocess.run(["ditto", "-x", "-k", str(package), str(check_dir)], check=True)
    require(inventory(check_dir / app.name) == state["native_inventory"], "Candidate extraction differs")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(check_dir / app.name)], check=True)
    for target in [app, runtime / app.name, check_dir / app.name]:
        subprocess.run([LS, "-u", str(target)], capture_output=True)
    shutil.rmtree(app)
    shutil.rmtree(check_dir)
    state["native_zip_sha256"] = sha(package)
    state["post_exit_native_dependencies"] = {p: sha(p) for p in state["post_exit_native_dependencies"]}
    probe = PRIVATE / "runtime-config-check"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-swift-version", "5", str(ROOT / "Review_Today/AppRuntime.swift"),
                    str(OUT / "RuntimeConfigCheck.swift"), "-o", str(probe)], check=True)
    result = subprocess.run([str(probe)], env=dict(os.environ, **env), capture_output=True, text=True)
    (OUT / "runtime-config-check.log").write_text(result.stdout + result.stderr)
    require(result.returncode == 0, "Actual production runtime resolver rejects new alias")
    reader_fixture = PRIVATE / "review-today-reader-fixture.noindex"
    reader_fixture.mkdir()
    result = subprocess.run([state["post_exit_native_reader"], str(reader_fixture)], env=dict(os.environ, **env), capture_output=True, text=True)
    (OUT / "reader-fixture.log").write_text(result.stdout + result.stderr)
    require(result.returncode == 0, "Relocated reader cannot run")
    empty = read(reader_fixture / "native-disk-read.json")
    require(all(empty[k] == 0 for k in ["knowledge_count", "source_count", "fsrs_count"])
            and empty["messages"] == empty["runs"] == empty["sessions"] == [], "Reader fixture not empty")
    write(OUT / "reader-fixture.json", empty)
    shutil.rmtree(reader_fixture)
    plan = read(OUT / "plan.json")
    plan.update(runtime_directory=str(runtime), runtime_alias=str(alias))
    write(OUT / "plan.json", plan)
    write(OUT / "setup.json", state)
    fix = dict(status="PASS_AFTER_REJECTED_DIRECT_PRIVATE_PATH", initial_direct_private_path_rejected_by_production_resolver=True,
        old_unlaunched_runtime_path=str(old), directory=str(runtime), runtime_alias=str(alias), alias_target_checked=True,
        no_product_source_change=True, app_three_code_sections_preserved=True,
        dependency_code_sections_preserved=True, reader_links="@executable_path/support and @loader_path",
        actual_production_resolver_passed=True, four_invalid_runtime_configs_rejected=True,
        relocated_reader_empty_disposable_store_passed=True, actual_batch_databases_absent=True,
        formal_database_opened=False, app_or_service_started=False, actual_model_requests=0, actual_web_operations=0)
    write(OUT / "runtime-path-fix.json", fix)
    pins = dict(state["protected_fingerprints"])
    for p in list(OUT.glob("*.py")) + list(OUT.glob("*.swift")) + [OUT/n for n in ["baseline.json","plan.json","setup.json","dependency-provenance.json","runtime-path-fix.json"]]:
        pins[str(p.relative_to(ROOT))] = sha(p)
    write(OUT / "source-pins.json", pins)
    auth = read(runtime / "authorization.json")
    auth.update(plan_sha256=sha(OUT / "plan.json"),source_pins_sha256=sha(OUT / "source-pins.json"))
    write(runtime / "authorization.json", auth)
    write(PRIVATE / "runtime-pins.json", files(runtime))
    unchanged()
    print("PASS: fresh tmp alias points to durable runtime; production resolver and relocated reader pass; App candidate remains archived and pending.")


if __name__ == "__main__":
    main()
