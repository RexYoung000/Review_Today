// Reproducible Spine 4.2 entry rigs. The exam's static and animated artwork
// comes from the same macOS SF Symbol raster, so hover cannot change its shape.
import {createCanvas,loadImage} from '@napi-rs/canvas';
import {execFileSync} from 'node:child_process';
import {mkdir,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {root} from './paths.mjs';

const target=resolve(root,'brand/refresh-2026-09/motion-rig/entry-icons');
const imageSet=resolve(root,'Review_Today/Assets.xcassets/TodayExamIcon.imageset');
const duration=1.6;
const frame=(time,value)=>({time,value});
const fade=(a,b,c,d)=>[frame(0,0),frame(a,0),frame(b,1),frame(c,1),frame(d,0),frame(duration,0)];
const scale=(a,b,c,d)=>[
 {time:0,x:.65,y:.65},{time:a,x:.65,y:.65},{time:b,x:1.22,y:1.22},
 {time:c,x:1,y:1},{time:d,x:.7,y:.7},{time:duration,x:.65,y:.65}
];
const examParts=['exam-badge','exam-line-top','exam-line-middle','exam-line-low','exam-line-bottom'];
const bones=[
 {name:'root'},
 {name:'star-main',parent:'root'},
 {name:'star-left',parent:'root',x:-11,y:9},
 {name:'star-right',parent:'root',x:12,y:6},
 {name:'star-bottom',parent:'root',x:6,y:-12},
 // The badge pivot matches its visual center. Its attachment offsets cancel
 // that rest translation so the assembled pixels remain exactly unchanged.
 {name:'exam-badge',parent:'root',x:-5.5,y:4.25},
 ...examParts.slice(1).map(name=>({name,parent:'root'}))
];
const definitions=[
 ['star-main','glint',20],
 ['star-left','glint',8],['star-right','glint',10],['star-bottom','glint',6],
 ...examParts.map(name=>[name,name,44])
];
const slots=definitions.map(([name,path])=>({name,bone:name,attachment:path,color:'ffffff00'}));
const attachments=Object.fromEntries(definitions.map(([name,path,size])=>[
 name,{[path]:{type:'region',path,width:size,height:size,
               ...(name==='exam-badge'?{x:5.5,y:-4.25}:{})}}
]));
const learningSlots=Object.fromEntries([
 ['star-main',fade(.05,.23,.34,.67)],
 ['star-left',fade(.06,.21,.26,.47)],
 ['star-right',fade(.39,.54,.60,.82)],
 ['star-bottom',fade(.74,.88,.94,1.17)]
].map(([name,alpha])=>[name,{alpha}]));
const lineSlide=start=>[
 {time:0,x:0,y:0},{time:start,x:0,y:0},
 {time:start+.16,x:.85,y:0},{time:start+.29,x:.85,y:0},
 {time:start+.48,x:0,y:0},{time:duration,x:0,y:0}
];
const examSlots=Object.fromEntries(examParts.map(name=>[
 name,{alpha:[frame(0,1),frame(duration,1)]}
]));
const examBones=Object.fromEntries([
 ['exam-badge',{
  scale:[{time:0,x:1,y:1},{time:.16,x:1,y:1},{time:.38,x:1.06,y:1.06},
         {time:.66,x:1,y:1},{time:duration,x:1,y:1}],
  rotate:[frame(0,0),frame(.16,0),frame(.38,2),frame(.66,0),frame(duration,0)]
 }],
 ...examParts.slice(1).map((name,index)=>[name,{translate:lineSlide(.12+index*.17)}])
]);
const animation=(slotAnimations,boneAnimations)=>({slots:slotAnimations,bones:boneAnimations});
const json={
 skeleton:{spine:'4.2.00',images:'./',audio:'./',x:-22,y:-22,width:44,height:44,fps:30},
 bones,slots,skins:[{name:'default',attachments}],
 animations:{
  learning:animation(learningSlots,{
   'star-main':{scale:scale(.05,.25,.40,.67)},
   'star-left':{scale:scale(.06,.23,.31,.47)},
   'star-right':{scale:scale(.39,.56,.64,.82)},
   'star-bottom':{scale:scale(.74,.90,.98,1.17)}
  }),
  exam:animation(examSlots,examBones)
 }
};

function glint(){
 const canvas=createCanvas(64,64),ctx=canvas.getContext('2d');
 ctx.fillStyle='#fff';ctx.beginPath();ctx.moveTo(32,3);ctx.quadraticCurveTo(36,27,61,32);
 ctx.quadraticCurveTo(36,37,32,61);ctx.quadraticCurveTo(27,37,3,32);
 ctx.quadraticCurveTo(27,27,32,3);ctx.fill();
 return canvas.toBuffer('image/png');
}

function examPart(x,y){
 if(y<47)return x<44?'exam-badge':y<36?'exam-line-top':'exam-line-middle';
 return y<56?'exam-line-low':'exam-line-bottom';
}

async function renderExamArt(){
 const scratch=await mkdtemp(resolve(tmpdir(),'review-today-exam-icon-'));
 try{
  const source=resolve(scratch,'symbol.png');
  execFileSync('swift',[resolve(root,'tools/mascot-motion/src/render-entry-symbol.swift'),source],{stdio:'pipe'});
  const image=await loadImage(source),canvas=createCanvas(88,88),ctx=canvas.getContext('2d');
  ctx.drawImage(image,0,0);
  const pixels=ctx.getImageData(0,0,88,88),parts=Object.fromEntries(examParts.map(name=>[
   name,ctx.createImageData(88,88)
  ]));
  for(let y=0;y<88;y++)for(let x=0;x<88;x++){
   const i=(y*88+x)*4,a=pixels.data[i+3];
   if(!a)continue;
   pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=255;
   const part=parts[examPart(x,y)].data;
   part[i]=part[i+1]=part[i+2]=255;part[i+3]=a;
  }
  ctx.putImageData(pixels,0,0);
  await mkdir(imageSet,{recursive:true});
  await writeFile(resolve(imageSet,'exam.png'),canvas.toBuffer('image/png'));
  await writeFile(resolve(imageSet,'Contents.json'),JSON.stringify({
   images:[{filename:'exam.png',idiom:'universal',scale:'2x'}],
   info:{author:'xcode',version:1}
  },null,2)+'\n');
  for(const [name,data] of Object.entries(parts)){
   const partCanvas=createCanvas(88,88);
   partCanvas.getContext('2d').putImageData(data,0,0);
   await writeFile(resolve(target,name+'.png'),partCanvas.toBuffer('image/png'));
  }
 }finally{await rm(scratch,{recursive:true,force:true});}
}

await mkdir(target,{recursive:true});
await renderExamArt();
await writeFile(resolve(target,'glint.png'),glint());
const imageNames=['glint',...examParts],atlas=imageNames.map(name=>{
 const size=name==='glint'?64:88;
 return `${name}.png\nsize: ${size},${size}\nfilter: Linear,Linear\npma: false\n${name}\n  bounds: 0,0,${size},${size}\n`;
}).join('\n');
await writeFile(resolve(target,'entry-icons.atlas'),atlas);
await writeFile(resolve(target,'entry-icons.json'),JSON.stringify(json,null,2)+'\n');
console.log('Built Today entry Spine icons and shared resting symbol:',target);
