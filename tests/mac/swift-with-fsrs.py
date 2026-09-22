#!/usr/bin/env python3
"""Keep direct swiftc QA/preview runners linked to the same pinned FSRS package."""
import pathlib, subprocess, sys, tempfile
root=pathlib.Path(__file__).resolve().parents[2]
build=pathlib.Path(tempfile.mkdtemp(prefix='review-today-fsrs-link.',dir='/tmp'))
sources=sorted(str(p) for p in (root/'Vendor/SwiftFSRS/Sources').rglob('*.swift'))
subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-emit-library','-emit-module','-module-name','FSRS','-emit-module-path',str(build/'FSRS.swiftmodule'),*sources,'-o',str(build/'libFSRS.dylib')],check=True)
raise SystemExit(subprocess.call(['xcrun','swiftc','-I',str(build),'-L',str(build),'-lFSRS','-Xlinker','-rpath','-Xlinker',str(build),*sys.argv[1:]]))
