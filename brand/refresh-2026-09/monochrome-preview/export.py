"""Render saved, editable native variants; never overwrite the accepted originals."""
import hashlib,json,subprocess,struct
from pathlib import Path
p=Path(__file__).resolve().parent
renderer='/Applications/Xcode.app/Contents/Applications/Icon Composer.app/Contents/Executables/ictool'
def digest(f): return hashlib.sha256(f.read_bytes()).hexdigest()
master=p.parent/'masters/mark-alpha.png'
report={'renderer':renderer,'variants':[],'preserved':{}}
for name,h in json.loads((p/'original-preserved/sha256.json').read_text()).items():
 assert digest(p/'original-preserved'/name)==h
 report['preserved'][name]=h
for kind in ['Original','Glass']:
 d=p/f'ReviewToday-Monochrome-{kind}.icon'; out=p/kind.lower(); out.mkdir(exist_ok=True)
 assert digest(d/'Assets/mark-alpha.png')==digest(master)
 def neutral(v):
  if isinstance(v,dict):
   for a in v.values(): neutral(a)
  elif isinstance(v,list):
   for a in v: neutral(a)
  elif isinstance(v,str) and v.startswith('extended-srgb:'):
   r,g,b,a=map(float,v.split(':')[1].split(',')); assert r==g==b,v
 neutral(json.loads((d/'icon.json').read_text()))
 files=[]
 for rendition in ['Default','Dark','Mono']:
  for size in [16,32,64,128,256,512,1024]:
   f=out/f'{rendition.lower()}-{size}.png'
   subprocess.run([renderer,str(d),'--export-image','--output-file',str(f),'--platform','macOS','--rendition',rendition,'--width',str(size),'--height',str(size),'--scale','1'],check=True,capture_output=True)
   assert struct.unpack('>II',f.read_bytes()[16:24])==(size,size)
   files.append({'file':str(f.relative_to(p)),'sha256':digest(f)})
 report['variants'].append({'kind':kind,'document_sha256':digest(d/'icon.json'),'master_sha256':digest(master),'neutral_color_parameters':True,'exports':files})
(p/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS: originals preserved, identical R master, neutral material colors, 42 native PNG sizes')
