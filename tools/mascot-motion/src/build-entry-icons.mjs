// Small, reproducible Spine 4.2 overlays for the two Today entry icons.
// The native SF Symbols remain the resting artwork; these slots only draw on hover.
import {createCanvas} from '@napi-rs/canvas';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {root} from './paths.mjs';

const target=resolve(root,'brand/refresh-2026-09/motion-rig/entry-icons');
const duration=1.6;
const frame=(time,value)=>({time,value});
const fade=(a,b,c,d)=>[frame(0,0),frame(a,0),frame(b,1),frame(c,1),frame(d,0),frame(duration,0)];
const scale=(a,b,c,d)=>[
 {time:0,x:.65,y:.65},{time:a,x:.65,y:.65},{time:b,x:1.22,y:1.22},
 {time:c,x:1,y:1},{time:d,x:.7,y:.7},{time:duration,x:.65,y:.65}
];
const bones=[
 {name:'root'},
 {name:'star-main',parent:'root'},
 {name:'star-left',parent:'root',x:-11,y:9},
 {name:'star-right',parent:'root',x:12,y:6},
 {name:'star-bottom',parent:'root',x:6,y:-12},
 {name:'exam-line-top',parent:'root'},
 {name:'exam-line-middle',parent:'root'},
 {name:'exam-line-low',parent:'root'},
 {name:'exam-line-bottom',parent:'root'},
 {name:'exam-badge',parent:'root',x:-5.25,y:4.3},
 {name:'exam-tick',parent:'exam-badge'}
];
const definitions=[
 ['star-main','glint',20],
 ['star-left','glint',8],['star-right','glint',10],['star-bottom','glint',6],
 ['exam-line-top','exam-line-top',24],
 ['exam-line-middle','exam-line-middle',24],
 ['exam-line-low','exam-line-low',24],
 ['exam-line-bottom','exam-line-bottom',24],
 ['exam-badge','exam-badge',8],['exam-tick','exam-tick',6]
];
const slots=definitions.map(([name,path])=>({name,bone:name,attachment:path,color:'ffffff00'}));
const attachments=Object.fromEntries(definitions.map(([name,path,size])=>[
 name,{[path]:{type:'region',path,width:size,height:size}}
]));
const learningSlots=Object.fromEntries([
 ['star-main',fade(.05,.23,.34,.67)],
 ['star-left',fade(.06,.21,.26,.47)],
 ['star-right',fade(.39,.54,.60,.82)],
 ['star-bottom',fade(.74,.88,.94,1.17)]
].map(([name,alpha])=>[name,{alpha}]));
const linePulse=(start)=>[
 frame(0,.78),frame(start,.78),frame(start+.16,1),frame(start+.34,1),
 frame(start+.58,.78),frame(duration,.78)
];
const lineSlide=(start)=>[
 {time:0,x:-1.2,y:0},{time:start,x:-1.2,y:0},
 {time:start+.16,x:0,y:0},{time:start+.34,x:0,y:0},
 {time:start+.58,x:-1.2,y:0},{time:duration,x:-1.2,y:0}
];
const examSlots={
 'exam-line-top':{alpha:linePulse(.12)},
 'exam-line-middle':{alpha:linePulse(.28)},
 'exam-line-low':{alpha:linePulse(.44)},
 'exam-line-bottom':{alpha:linePulse(.60)},
 'exam-badge':{alpha:[frame(0,1),frame(duration,1)]},
 'exam-tick':{alpha:[frame(0,.68),frame(.14,.68),frame(.38,1),frame(.95,1),frame(1.25,.68),frame(duration,.68)]}
};
const animation=(slotAnimations,boneAnimations)=>({slots:slotAnimations,bones:boneAnimations});
const json={
 skeleton:{spine:'4.2.00',images:'./',audio:'./',x:-20,y:-20,width:40,height:40,fps:30},
 bones,slots,skins:[{name:'default',attachments}],
 animations:{
  learning:animation(learningSlots,{
   'star-main':{scale:scale(.05,.25,.40,.67)},
   'star-left':{scale:scale(.06,.23,.31,.47)},
   'star-right':{scale:scale(.39,.56,.64,.82)},
   'star-bottom':{scale:scale(.74,.90,.98,1.17)}
  }),
  exam:animation(examSlots,{
   'exam-line-top':{translate:lineSlide(.12)},
   'exam-line-middle':{translate:lineSlide(.28)},
   'exam-line-low':{translate:lineSlide(.44)},
   'exam-line-bottom':{translate:lineSlide(.60)},
   'exam-badge':{
    scale:[{time:0,x:1,y:1},{time:.16,x:.94,y:.94},{time:.42,x:1.12,y:1.12},{time:.65,x:1,y:1},{time:duration,x:1,y:1}],
    rotate:[frame(0,0),frame(.16,-5),frame(.42,3),frame(.65,0),frame(duration,0)]
   }
  })
 }
};

function paint(name){
 const canvas=createCanvas(64,64),ctx=canvas.getContext('2d');
 ctx.fillStyle='#fff';ctx.strokeStyle='#fff';
 if(name==='glint'){
  // Four tapered tips, matching the visual language of the native sparkle icon.
  ctx.beginPath();ctx.moveTo(32,3);ctx.quadraticCurveTo(36,27,61,32);
  ctx.quadraticCurveTo(36,37,32,61);ctx.quadraticCurveTo(27,37,3,32);
  ctx.quadraticCurveTo(27,27,32,3);ctx.fill();
 }else if(name==='exam-badge'){
  ctx.lineWidth=8;ctx.beginPath();ctx.arc(32,32,24,0,Math.PI*2);ctx.stroke();
 }else if(name==='exam-tick'){
  ctx.lineWidth=9;ctx.lineCap='round';ctx.lineJoin='round';
  ctx.beginPath();ctx.moveTo(9,32);ctx.lineTo(26,47);ctx.lineTo(55,17);ctx.stroke();
 }else{
  const lines={
   'exam-line-top':[33,17,56,17],
   'exam-line-middle':[33,28,56,28],
   'exam-line-low':[9,44,56,44],
   'exam-line-bottom':[9,55,56,55]
  };
  ctx.lineWidth=5;ctx.lineCap='round';ctx.beginPath();
  const [x1,y1,x2,y2]=lines[name];ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();
 }
 return canvas.toBuffer('image/png');
}

await mkdir(target,{recursive:true});
const imageNames=['glint',...definitions.map(([,path])=>path).filter(path=>path!=='glint')];
for(const name of imageNames)await writeFile(resolve(target,name+'.png'),paint(name));
const atlas=imageNames.map(name=>`${name}.png\nsize: 64,64\nfilter: Linear,Linear\npma: false\n${name}\n  bounds: 0,0,64,64\n`).join('\n');
await writeFile(resolve(target,'entry-icons.atlas'),atlas);
await writeFile(resolve(target,'entry-icons.json'),JSON.stringify(json,null,2)+'\n');
console.log('Built Today entry Spine overlays:',target);
