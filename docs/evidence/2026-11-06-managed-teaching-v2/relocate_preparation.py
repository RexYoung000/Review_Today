"""Correct a pending candidate's isolation name/TMPDIR and relocated reader links."""
import os
from pathlib import Path
import plistlib
import py_compile
import shlex
import shutil
import subprocess
import sys
from common import *


def main():
    os.umask(0o077)
    unchanged()
    state = read(OUT / "setup.json")
    old = Path(state["directory"])
    require(read(old / "authorization.json")["status"] == "pending" and (old / "HOLD").is_file(), "Not pending")
    require(not any((old / p).exists() for p in ["quota.json", "app.store", "checkpoint.sqlite3", "startup-claim.json"]), "Runtime activity exists")
    previous = ARCHIVE / "before-runtime-path-fix"
    previous.mkdir()
    for name in ["setup.json", "source-pins.json", "plan.json", "dependency-provenance.json", "checks.json"]:
        shutil.copy2(OUT / name, previous / name)
    package = Path(state["native_zip"])
    shutil.copy2(package, previous / package.name)
    new = PRIVATE / ("review-today-managed-" + state["batch_id"] + ".noindex")
    require(not new.exists(), "New runtime already exists")
    old.rename(new)
    state = __import__("json").loads(__import__("json").dumps(state).replace(str(old), str(new)))
    plan = read(OUT / "plan.json")
    plan["runtime_directory"] = str(new)
    state["native_environment"]["TMPDIR"] = str(PRIVATE) + "/"
    state["isolation_temporary_root_is_private_durable_directory"] = True
    site = new / "owned-project/agent-service/sitecustomize.py"
    site.write_text(site.read_text().replace(str(old), str(new)))
    py_compile.compile(str(site), doraise=True)
    fixes = []
    for target in [new / "native-disk-reader", new / "support/libReviewTodayContractSupport.dylib"]:
        before = text_section(target)
        lines = subprocess.check_output(["otool", "-l", str(target)], text=True).splitlines()
        rpaths = [lines[i + 2].strip().split("path ", 1)[1].rsplit(" (offset", 1)[0]
                  for i, line in enumerate(lines) if line.strip() == "cmd LC_RPATH"]
        for path in rpaths:
            replacement = "@executable_path/support" if target.name == "native-disk-reader" else "@loader_path"
            subprocess.run(["install_name_tool", "-rpath", path, replacement, str(target)], check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=True)
        require(text_section(target) == before, "Dependency machine code changed")
        fixes.append(dict(path=str(target), old_rpaths=rpaths, code_text_preserved=True, sha256=sha(target)))
    state["post_exit_native_dependencies"] = {p: sha(p) for p in state["post_exit_native_dependencies"]}
    app = Path(state["native_app"])
    subprocess.run(["ditto", "-x", "-k", str(package), str(new)], check=True)
    wrapper = app / "Contents/MacOS/ManagedTeachingEntry"
    wrapper.write_text("#!/bin/sh\nset -eu\n" + "".join("export " + k + "=" + shlex.quote(str(v)) + "\n" for k,v in state["native_environment"].items())
        + "exec " + shlex.quote(str(app / "Contents/MacOS/Review_Today")) + ' "$@"\n')
    wrapper.chmod(0o755)
    subprocess.run(["/bin/sh", "-n", str(wrapper)], check=True)
    for name in state["native_executable_text_sha256"]:
        subprocess.run(["codesign", "--force", "--sign", "-", str(app / "Contents/MacOS" / name)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    require(all(text_section(app / "Contents/MacOS" / name) == h for name,h in state["native_executable_text_sha256"].items()), "App code changed")
    state["fixed_environment_wrapper_sha256"] = sha(wrapper)
    state["native_inventory"] = inventory(app)
    package.unlink()
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(package)], check=True)
    extracted = PRIVATE / "runtime-path-archive-check.noindex"
    extracted.mkdir()
    subprocess.run(["ditto", "-x", "-k", str(package), str(extracted)], check=True)
    require(inventory(extracted / app.name) == state["native_inventory"], "Extracted candidate differs")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(extracted / app.name)], check=True)
    for target in [app, extracted / app.name]:
        result = subprocess.run([LS, "-u", str(target)], capture_output=True)
        require(result.returncode in {0,1}, "Unregister failed")
    shutil.rmtree(app)
    shutil.rmtree(extracted)
    state["native_zip_sha256"] = sha(package)
    probe = PRIVATE / "runtime-config-check"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-swift-version", "5", str(ROOT / "Review_Today/AppRuntime.swift"),
                    str(OUT / "RuntimeConfigCheck.swift"), "-o", str(probe)], check=True)
    env = dict(os.environ, **state["native_environment"])
    result = subprocess.run([str(probe)], env=env, capture_output=True, text=True, check=True)
    (OUT / "runtime-config-check.log").write_text(result.stdout + result.stderr)
    # Fresh disposable empty store proves the relocated reader loads both libraries.
    reader_fixture = PRIVATE / "review-today-reader-fixture.noindex"
    reader_fixture.mkdir()
    reader = subprocess.run([state["post_exit_native_reader"], str(reader_fixture)], env=env, capture_output=True, text=True, check=True)
    empty = read(reader_fixture / "native-disk-read.json")
    require(all(empty[k] == 0 for k in ["knowledge_count", "source_count", "fsrs_count"])
            and empty["messages"] == empty["runs"] == empty["sessions"] == [], "Reader fixture not empty")
    write(OUT / "reader-fixture.json", empty)
    shutil.rmtree(reader_fixture)
    write(OUT / "runtime-path-fix.json", dict(status="PASS", previous_candidate_preserved=str(previous),
        old_unlaunched_runtime_path=str(old), new_runtime_path=str(new), dependency_relocations=fixes,
        production_runtime_resolver_passed=True, reader_empty_disposable_fixture_passed=True,
        actual_batch_databases_absent=True, formal_database_opened=False, app_or_service_started=False,
        actual_model_requests=0, actual_web_operations=0))
    write(OUT / "setup.json", state)
    write(OUT / "plan.json", plan)
    pins = dict(state["protected_fingerprints"])
    for p in list(OUT.glob("*.py")) + list(OUT.glob("*.swift")) + [OUT/n for n in ["baseline.json","plan.json","setup.json","dependency-provenance.json","runtime-path-fix.json"]]:
        pins[str(p.relative_to(ROOT))] = sha(p)
    write(OUT / "source-pins.json", pins)
    auth = read(new / "authorization.json")
    auth.update(plan_sha256=sha(OUT / "plan.json"),source_pins_sha256=sha(OUT / "source-pins.json"))
    write(new / "authorization.json",auth)
    write(PRIVATE / "runtime-pins.json", files(new))
    unchanged()
    print("PASS: private TMPDIR and review-today name accepted; relative reader paths load; candidate reverified and archived; still pending real 0/0.")


if __name__ == "__main__":
    main()
