"""Prepare a fresh held full-App clone on the approved current baseline; never launch."""
import os
from pathlib import Path
import platform
import plistlib
import py_compile
import shlex
import shutil
import socket
import subprocess
import sys
import uuid
import zipfile
from common import (ROOT, OUT, PRIVATE, ARCHIVE, DAILY, LS, read, write, sha, files, inventory,
                    unchanged, require, source_files, text_section)


def main():
    os.umask(0o077)
    require(not (OUT / "setup.json").exists() and not PRIVATE.exists(), "A preparation already exists")
    initial, pins = unchanged()
    PRIVATE.mkdir(mode=0o700)
    ARCHIVE.mkdir(mode=0o700)
    batch = str(uuid.uuid4())
    runtime = PRIVATE / ("runtime-" + batch + ".noindex")
    runtime.mkdir(mode=0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    require(port != 8742, "Invalid isolated port")
    original_plan = read(ROOT / "docs/evidence/2026-11-06-managed-teaching-preflight/plan.json")
    plan = {k: original_plan[k] for k in ["scope", "model_request_limit", "provider_web_operation_limit", "startup_estimate",
        "path_estimate", "reserve_within_limit", "first_input", "required_concepts", "gates", "counting", "stop_conditions",
        "excluded", "expected_environment", "launch_method"]}
    plan.update(status="PREPARED_PENDING_NEW_20_0", decision=278, batch_id=batch, runtime_directory=str(runtime),
                all_old_allowances_frozen=True, actual_execution_authorized=False, actual_model_requests=0, actual_web_operations=0,
                new_baseline_approved=True, current_desktop_state="not_checked; inspect before any native launch")
    plan["expected_environment"].update(version=platform.mac_ver()[0], architecture=platform.machine())
    write(OUT / "plan.json", plan)
    service = runtime / "owned-project/agent-service"
    (service / ".venv/bin").mkdir(parents=True)
    real = ROOT / "agent-service"
    (service / ".venv/bin/python").symlink_to(real / ".venv/bin/python")
    shutil.copy2(real / ".venv/pyvenv.cfg", service / ".venv/pyvenv.cfg")
    (service / ".venv/lib").symlink_to(real / ".venv/lib", target_is_directory=True)
    site = service / "sitecustomize.py"
    site.write_text("import os,sys\nsys.dont_write_bytecode=True\n_admitted=False\n"
        "def _audit(event,args):\n    if not _admitted and event in {'sqlite3.connect','socket.connect'}:raise PermissionError('Pending runtime access')\n"
        "sys.addaudithook(_audit)\ntry:\n" +
        f"    os.environ['REVIEW_TODAY_REVIEW_DB']={str(runtime / 'review.sqlite3')!r}\n" +
        f"    sys.path.insert(0,{str(real)!r})\n    sys.path.insert(0,{str(OUT)!r})\n" +
        f"    import bootstrap\n    bootstrap.check_approved({str(runtime)!r},{str(ROOT)!r})\n" +
        f"    _admitted=True\n    bootstrap.install({str(runtime)!r},{str(ROOT)!r})\n" +
        "except BaseException as error:\n    print('QA_BOOTSTRAP_FAILED:'+type(error).__name__,flush=True)\n    os._exit(74)\n")
    py_compile.compile(str(site), doraise=True)
    baseline = read(OUT / "baseline.json")
    old_setup = read(ROOT / baseline["anchors"]["old_setup"]["path"])
    candidates = read(ROOT / baseline["anchors"]["strict_candidates"]["path"])["mapping"]
    dependencies, dependency_provenance = {}, {}
    for old_path, digest in old_setup["post_exit_native_dependencies"].items():
        target = runtime / ("support/" + Path(old_path).name if "/support/" in old_path else Path(old_path).name)
        receipt = candidates[old_path]["candidate"]
        require(sha(receipt["archive"]) == receipt["archive_sha256"], "Dependency archive changed")
        with zipfile.ZipFile(receipt["archive"]) as archive:
            data = archive.read(receipt["member"])
        require(__import__("hashlib").sha256(data).hexdigest() == digest, "Dependency bytes changed")
        target.parent.mkdir(mode=0o700, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o700 if target.name == "native-disk-reader" or target.suffix == ".dylib" else 0o600)
        dependencies[str(target)] = digest
        dependency_provenance[str(target)] = dict(original_missing_path=old_path, sha256=digest, **receipt)
    # No database is opened: only inspect the relocated reader's dynamic links.
    linkage = subprocess.check_output(["otool", "-L", str(runtime / "native-disk-reader")], text=True)
    write(OUT / "dependency-provenance.json", dict(files=dependency_provenance, reader_linkage=linkage,
        original_missing_paths_restored=False, database_opened=False))
    app = runtime / "ManagedTeachingQA.app"
    shutil.copytree(DAILY, app)
    info_path = app / "Contents/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    original_id = info["CFBundleIdentifier"]
    info.update(CFBundleIdentifier="Rex.Review-Today.ManagedTeaching278.NativeQA", CFBundleExecutable="ManagedTeachingEntry",
                CFBundleName="Review Today 托管首启隔离", CFBundleDisplayName="Review Today 托管首启隔离")
    info_path.write_bytes(plistlib.dumps(info))
    native_home = runtime / "native-home"
    native_home.mkdir(mode=0o700)
    environment = dict(REVIEW_TODAY_NATIVE_TEST_DIR=str(runtime), REVIEW_TODAY_NATIVE_TEST_PORT=str(port),
        REVIEW_TODAY_PROJECT_ROOT=str(runtime / "owned-project"), REVIEW_TODAY_JEV_TEST="0", CFFIXED_USER_HOME=str(native_home))
    wrapper = app / "Contents/MacOS/ManagedTeachingEntry"
    wrapper.write_text("#!/bin/sh\nset -eu\n" + "".join("export " + key + "=" + shlex.quote(str(value)) + "\n" for key, value in environment.items())
        + "exec " + shlex.quote(str(app / "Contents/MacOS/Review_Today")) + ' "$@"\n')
    wrapper.chmod(0o755)
    subprocess.run(["/bin/sh", "-n", str(wrapper)], check=True)
    code = {p.name: text_section(p) for p in (DAILY / "Contents/MacOS").iterdir() if p.is_file()}
    for name in code:
        subprocess.run(["codesign", "--force", "--sign", "-", str(app / "Contents/MacOS" / name)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    require(all(text_section(app / "Contents/MacOS" / name) == h for name, h in code.items()), "Full-App code changed")
    resources = {str(p.relative_to(DAILY)): sha(p) for p in (DAILY / "Contents/Resources").rglob("*") if p.is_file()}
    require(all(sha(app / p) == h for p, h in resources.items()), "Resources changed")
    package = ARCHIVE / "ManagedTeachingQA.zip"
    app_inventory = inventory(app)
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(package)], check=True)
    extracted = runtime / "archive-check.noindex"
    extracted.mkdir(mode=0o700)
    subprocess.run(["ditto", "-x", "-k", str(package), str(extracted)], check=True)
    require(inventory(extracted / app.name) == app_inventory, "Extracted app differs")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(extracted / app.name)], check=True)
    wrapper_hash = sha(wrapper)
    for target in [app, extracted / app.name]:
        result = subprocess.run([LS, "-u", str(target)], capture_output=True)
        require(result.returncode in {0, 1}, "Unregister candidate failed")
    listing = subprocess.check_output([LS, "-dump"], text=True)
    require(str(app) not in listing and str(extracted / app.name) not in listing, "Candidate remains registered")
    shutil.rmtree(extracted)
    shutil.rmtree(app)
    state = dict(status="PREPARED_HOLD_ARCHIVED", decision=278, directory=str(runtime), port=port, batch_id=batch,
        scope=plan["scope"], baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        native_app=str(app), native_zip=str(package), native_zip_sha256=sha(package), native_inventory=app_inventory,
        native_environment=environment, native_executable_text_sha256=code, original_bundle_id=original_id,
        native_bundle_id=info["CFBundleIdentifier"], fixed_environment_wrapper_sha256=wrapper_hash,
        protected_fingerprints=pins, daily_files=baseline["formal_files"], daily_app_inventory=inventory(DAILY),
        user_project_diff_sha256=old_setup["user_project_diff_sha256"], post_exit_native_reader=str(runtime / "native-disk-reader"),
        post_exit_native_dependencies=dependencies, dependency_links={str(p.relative_to(runtime)): os.readlink(p) for p in runtime.rglob("*") if p.is_symlink()},
        exact_full_app_not_custom_qa_shell=True, native_resources_matched=len(resources), raw_qa_app_removed=True,
        actual_model_requests=0, actual_web_operations=0, app_launched=False, service_started=False,
        authorization_confirmed=False, original_277_result_preserved=True)
    write(OUT / "setup.json", state)
    for path in list(OUT.glob("*.py")) + [OUT / n for n in ["baseline.json", "plan.json", "setup.json", "dependency-provenance.json"]]:
        pins[str(path.relative_to(ROOT))] = sha(path)
    write(OUT / "source-pins.json", pins)
    write(runtime / "authorization.json", dict(status="pending", batch_id=batch, actual_model_request_limit=20,
        provider_web_operation_limit=0, scope=state["scope"], plan_sha256=sha(OUT / "plan.json"), source_pins_sha256=sha(OUT / "source-pins.json")))
    (runtime / "HOLD").write_text("Preparation only. New 20/0 App-managed batch requires explicit execution approval. Old allowances remain frozen.\n")
    write(PRIVATE / "runtime-pins.json", files(runtime))
    final, _ = unchanged()
    write(OUT / "preparation-result.json", dict(status="OFFLINE_CANDIDATE_PREPARED_PENDING_EXECUTION", initial=initial, final=final,
        native_code_sections_matched=len(code), native_signature_and_archive_inventory_verified=True,
        no_app_or_service_launch=True, real_model_requests=0, real_web_operations=0))
    print("Prepared and archived independent full-App candidate; pending/HOLD, real 0/0.")


if __name__ == "__main__":
    main()
