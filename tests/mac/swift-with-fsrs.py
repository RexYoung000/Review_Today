#!/usr/bin/env python3
"""Keep direct swiftc QA/preview runners linked to the same pinned FSRS package."""
import pathlib, shutil, subprocess, sys, tempfile
root=pathlib.Path(__file__).resolve().parents[2]
build=pathlib.Path(tempfile.mkdtemp(prefix='review-today-fsrs-link.',dir='/tmp'))
# A dependency must target the same OS floor as its preview executable.
arguments = sys.argv[1:]
target = arguments[arguments.index('-target') + 1] if '-target' in arguments else None
platform_flags = ['-target', target] if target else []
sources=sorted(str(p) for p in (root/'Vendor/SwiftFSRS/Sources').rglob('*.swift'))
subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-emit-library','-emit-module','-module-name','FSRS',*platform_flags,'-emit-module-path',str(build/'FSRS.swiftmodule'),'-Xlinker','-install_name','-Xlinker','@rpath/libFSRS.dylib',*sources,'-o',str(build/'libFSRS.dylib')],check=True)
# App previews must remain launchable after temporary build directories are gone.
output = pathlib.Path(arguments[arguments.index('-o') + 1]) if '-o' in arguments else None
runtime_path = str(build)
if output and output.parent.name == 'MacOS' and output.parent.parent.name == 'Contents':
    frameworks = output.parent.parent / 'Frameworks'
    frameworks.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / 'libFSRS.dylib', frameworks / 'libFSRS.dylib')
    runtime_path = '@executable_path/../Frameworks'
raise SystemExit(subprocess.call(['xcrun','swiftc','-I',str(build),'-L',str(build),'-lFSRS','-Xlinker','-rpath','-Xlinker',runtime_path,*sys.argv[1:]]))
