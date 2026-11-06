"""Restore only after approval; launch must be a separate CUA UI action."""
import subprocess
import sys
from pathlib import Path
from common import ROOT, OUT, PRIVATE, unchanged, read, write, sha, inventory
from bootstrap import check_approved


def main():
    setup = read(OUT / "setup.json")
    directory = Path(setup["directory"])
    check_approved(directory, ROOT)  # Must refuse pending before mutation/UI.
    unchanged()
    expected = read(PRIVATE / "runtime-pins.json")
    current = __import__("common").files(directory)
    excluded = {str(directory / name) for name in ["authorization.json", "HOLD"]}
    assert {p: h for p, h in current.items() if p not in excluded} == {p: h for p, h in expected.items() if p not in excluded}
    assert not (directory / "launch.json").exists() and not (directory / "restored-app.json").exists()
    app = Path(setup["native_app"])
    assert not app.exists() and sha(Path(setup["native_zip"])) == setup["native_zip_sha256"]
    subprocess.run(["ditto", "-x", "-k", setup["native_zip"], str(directory)], check=True)
    assert inventory(app) == setup["native_inventory"]
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    write(directory / "restored-app.json", dict(batch_id=setup["batch_id"], app=str(app), app_launched=False))
    print("Restored only. After verifying the Mac is unlocked, launch this path once through cua.getApp; its fixed wrapper sets isolation before exec of the unchanged full App. Do not launch via this script or start Python separately.")


if __name__ == "__main__":
    main()
