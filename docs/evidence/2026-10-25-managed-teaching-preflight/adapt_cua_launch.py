"""Add fixed isolation environment for CUA launch; never launch the App."""
import plistlib
import shlex
import shutil
import subprocess
from pathlib import Path
from common import *


def main():
    unchanged()
    state = read(OUT / "setup.json")
    runtime, app = Path(state["directory"]), Path(state["native_app"])
    assert not any((runtime / n).exists() for n in ["quota.json", "startup-claim.json", "launch.json"])
    assert read(runtime / "authorization.json")["status"] == "pending" and (runtime / "HOLD").exists()
    prior = ARCHIVE / "before-cua-launch-adaptation"
    prior.mkdir(exist_ok=True)
    for name in ["setup.json", "plan.json", "source-pins.json", "checks.json"]:
        if not (prior / name).exists():
            shutil.copy2(OUT / name, prior / name)
    package = Path(state["native_zip"])
    if not (prior / "ManagedTeachingQA.zip").exists():
        shutil.copy2(package, prior / "ManagedTeachingQA.zip")
    assert sha(prior / "ManagedTeachingQA.zip") == state["native_zip_sha256"]
    if app.exists():
        failure = read(OUT / "initial-cua-signature-result.json")
        assert failure["actual_model_requests"] == 0 and sha(Path(failure["archive"])) == failure["sha256"]
        assert all(text_section(app / "Contents/MacOS" / name) == h for name, h in state["native_executable_text_sha256"].items())
    else:
        subprocess.run(["ditto", "-x", "-k", str(package), str(runtime)], check=True)
        assert inventory(app) == state["native_inventory"]
    wrapper = app / "Contents/MacOS/ManagedTeachingEntry"
    wrapper.write_text("#!/bin/sh\nset -eu\n" + "".join("export " + key + "=" + shlex.quote(str(value)) + "\n" for key, value in state["native_environment"].items())
        + "exec " + shlex.quote(str(app / "Contents/MacOS/Review_Today")) + ' "$@"\n')
    wrapper.chmod(0o755)
    subprocess.run(["/bin/sh", "-n", str(wrapper)], check=True)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    info["CFBundleExecutable"] = "ManagedTeachingEntry"
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    for name in state["native_executable_text_sha256"]:
        subprocess.run(["codesign", "--force", "--sign", "-", str(app / "Contents/MacOS" / name)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    assert all(text_section(app / "Contents/MacOS" / name) == h for name, h in state["native_executable_text_sha256"].items())
    inventory_after = inventory(app)
    # Preserve the old package before replacing this not-yet-approved candidate.
    package.unlink()
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(package)], check=True)
    extracted = runtime / "cua-archive-check.noindex"
    extracted.mkdir()
    subprocess.run(["ditto", "-x", "-k", str(package), str(extracted)], check=True)
    assert inventory(extracted / app.name) == inventory_after
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(extracted / app.name)], check=True)
    for target in [app, extracted / app.name]:
        result = subprocess.run([LS, "-u", str(target)], capture_output=True)
        assert result.returncode in {0, 1}
    listing = subprocess.check_output([LS, "-dump"], text=True)
    assert str(app) not in listing and str(extracted / app.name) not in listing
    state.update(native_zip_sha256=sha(package), native_inventory=inventory_after,
        fixed_environment_wrapper_sha256=sha(wrapper), cua_launch_required=True,
        launch_wrapper_only=True, original_three_executable_text_sections_unchanged=True,
        mac_locked_at_preparation=True, app_child_permissions_and_full_app_launch_not_verified=True)
    write(OUT / "setup.json", state)
    plan = read(OUT / "plan.json")
    plan["launch_method"] = "After approval restore only; CUA opens full-App clone once. A fixed environment wrapper execs the unchanged App executable; that App owns the guarded Python child."
    plan["ui_environment_blocker"] = "Mac is locked; user must manually unlock it before any native UI action. Do not auto-unlock or start around this condition."
    write(OUT / "plan.json", plan)
    write(OUT / "ui-channel.json", dict(status="MAC_LOCKED", native_inventory_queried=True,
        error="The Mac is locked and automatic unlock could not unlock it. Ask the user to unlock the Mac manually before continuing.",
        app_selected=False, app_launched=False, browser_operations=0, actual_model_requests=0,
        action_required="User manually unlocks Mac; verify CUA native availability again before launch"))
    shutil.rmtree(extracted)
    shutil.rmtree(app)
    pins = dict(state["protected_fingerprints"])
    for path in list(OUT.glob("*.py")) + [OUT / "plan.json", OUT / "setup.json", OUT / "ui-channel.json"]:
        pins[str(path.relative_to(ROOT))] = sha(path)
    write(OUT / "source-pins.json", pins)
    spec = read(runtime / "authorization.json")
    spec.update(plan_sha256=sha(OUT / "plan.json"), source_pins_sha256=sha(OUT / "source-pins.json"))
    write(runtime / "authorization.json", spec)
    write(PRIVATE / "runtime-pins.json", files(runtime))
    write(OUT / "launch-adaptation.json", dict(status="OFFLINE_PASS", prior_candidate_preserved=str(prior),
        old_package_sha256=read(prior / "setup.json")["native_zip_sha256"], new_package_sha256=sha(package),
        wrapper_syntax_checked=True, full_app_code_unchanged=True, native_app_not_launched=True,
        launch_requires_cua=True, native_mac_locked=True, real_requests=0))
    unchanged()
    print("CUA-only launch candidate prepared and strict-signed ZIP re-extracted; old candidate retained; real 0/0. Mac must be unlocked manually before native launch.")


if __name__ == "__main__":
    main()
