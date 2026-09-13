#!/usr/bin/env python3
"""Build the real pages with isolated data and native paint probes, no service."""
import argparse
import pathlib
import plistlib
import shutil
import subprocess

p = argparse.ArgumentParser()
p.add_argument("directory", type=pathlib.Path)
p.add_argument("--configuration", choices=["Debug", "Release"], default="Release")
p.add_argument("--dataset", choices=["small", "stress"], default="small")
p.add_argument("--reuse-binary", type=pathlib.Path)
args = p.parse_args()
root = pathlib.Path(__file__).resolve().parents[2]
folder = args.directory.resolve()
assert folder.name.startswith("review-today-") and (str(folder).startswith("/tmp/") or str(folder).startswith("/private/tmp/"))
app = folder / "NavigationPerformanceQA.app"
contents = app / "Contents"
binary = contents / "MacOS/NavigationPerformanceQA"
resources = contents / "Resources"
binary.parent.mkdir(parents=True, exist_ok=True)
resources.mkdir(parents=True, exist_ok=True)
sources = sorted(str(s) for s in (root / "Review_Today").glob("*.swift") if s.name != "Review_TodayApp.swift")
with (folder / "build.log").open("w") as log:
    if args.reuse_binary:
        shutil.copy2(args.reuse_binary, binary)
    else:
        flags = ["-Onone", "-D", "DEBUG"] if args.configuration == "Debug" else ["-O", "-whole-module-optimization"]
        subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-D", "PERFORMANCE_QA", *flags,
            "-swift-version", "5", "-default-isolation", "MainActor", "-enable-upcoming-feature", "MemberImportVisibility", "-target", "arm64-apple-macos26.5",
            *sources, str(root / "tests/mac/NavigationPerformanceQA.swift"), "-o", str(binary)], stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run(["xcrun", "actool", str(root / "Review_Today/Assets.xcassets"), "--compile", str(resources), "--platform", "macosx",
        "--minimum-deployment-target", "26.5", "--target-device", "mac", "--app-icon", "AppIcon",
        "--output-partial-info-plist", str(folder / "asset-info.plist")], stdout=log, stderr=subprocess.STDOUT, check=True)
info = dict(CFBundleIdentifier="Rex." + folder.name.replace("-", ".") + ".PerformanceQA",
    CFBundleName="NavigationPerformanceQA", CFBundleExecutable=binary.name, CFBundlePackageType="APPL",
    LSMinimumSystemVersion="26.5", NSHighResolutionCapable=True,
    PerformanceDirectory=str(folder), PerformanceDataset=args.dataset, PerformanceConfiguration=args.configuration)
info.update(plistlib.loads((folder / "asset-info.plist").read_bytes()))
for source in (root / "Review_Today").glob("*.html"):
    shutil.copy2(source, resources / source.name)
for source in (root / "Review_Today/Fonts").iterdir():
    if source.is_file():
        shutil.copy2(source, resources / source.name)
for source in (root / "Review_Today").glob("*.lproj"):
    shutil.copytree(source, resources / source.name, dirs_exist_ok=True)
with (contents / "Info.plist").open("wb") as file:
    plistlib.dump(info, file)
subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
print(app)
