#!/usr/bin/env python3
"""Package Rex's confirmed native icon. Preserve archived green assets and menu template."""
from pathlib import Path
import hashlib,json,shutil,subprocess,struct
root=Path(__file__).resolve().parent.parent
source=root/'brand/refresh-2026-09/monochrome-preview/ReviewToday-Confirmed-BlackWhite.icon'
renderer='/Applications/Xcode.app/Contents/Applications/Icon Composer.app/Contents/Executables/ictool'
assets=root/'Review_Today/Assets.xcassets'
exports=root/'brand/exports'
records=[]
for size in [16,32,64,128,256,512,1024]:
 dest=assets/f'AppIcon.appiconset/icon_{size}.png'
 subprocess.run([renderer,str(source),'--export-image','--output-file',str(dest),'--platform','macOS','--rendition','Default','--width',str(size),'--height',str(size),'--scale','1'],check=True,capture_output=True)
 assert struct.unpack('>II',dest.read_bytes()[16:24])==(size,size)
 records.append({'size':size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
logo=assets/'BrandDefaultLogo.imageset';logo.mkdir(exist_ok=True)
for size,name in [(128,'logo.png'),(256,'logo@2x.png')]: shutil.copy2(assets/f'AppIcon.appiconset/icon_{size}.png',logo/name)
(logo/'Contents.json').write_text(json.dumps({'images':[{'filename':'logo.png','idiom':'mac','scale':'1x'},{'filename':'logo@2x.png','idiom':'mac','scale':'2x'}],'info':{'author':'xcode','version':1},'properties':{'template-rendering-intent':'original'}},indent=2)+'\n')
shutil.copy2(assets/'AppIcon.appiconset/icon_1024.png',exports/'app-icon-1024.png')
(exports/'default-logo-validation.json').write_text(json.dumps({'source':str(source.relative_to(root)),'source_sha256':hashlib.sha256((source/'icon.json').read_bytes()).hexdigest(),'exports':records},indent=2)+'\n')
print('PASS: seven native AppIcon sizes, original-rendering brand logo, confirmed source recorded')
