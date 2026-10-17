"""Restore only the already backed-up QA app after its normal exit."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    assert not subprocess.run(["pgrep", "-fl", "/ContinuousResumeQA.app/Contents/MacOS/"], capture_output=True, text=True).stdout.strip()
    listener = subprocess.run(["lsof", "-nP", f"-iTCP:{setup['port']}", "-sTCP:LISTEN"], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    count = json.loads((directory / "request-count.json").read_text())
    assert count["limit"] == 30 and 26 <= count["actual_requests"] <= 30
    assert (directory / "STOP").exists()
    app, backup = Path(setup["native_app"]), Path(setup["prior_native_app_backup"])
    assert digest(app / "Contents/MacOS/ContinuousResumeQA") == setup["native_binary_sha256"]
    shutil.move(str(app / "Contents"), str(directory / "used-native-contents"))
    shutil.copytree(backup / "Contents", app / "Contents")
    subprocess.run(["codesign", "--verify", "--strict", str(app)], check=True)
    restored = {str(p.relative_to(app)): digest(p) for p in app.rglob("*") if p.is_file()}
    original = {str(p.relative_to(backup)): digest(p) for p in backup.rglob("*") if p.is_file()}
    assert restored == original
    assert digest(app / "Contents/MacOS/ContinuousResumeQA") == setup["prior_native_binary_sha256"]
    result = dict(native_app_closed=True, service_closed=True, restored_prior_test_app=True,
                  prior_binary_sha256=setup["prior_native_binary_sha256"],
                  request_count=count, unused_allowance=30-count["actual_requests"],
                  daily_app_replaced=False)
    (EVIDENCE / "cleanup.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
