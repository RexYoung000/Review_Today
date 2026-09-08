import {createStudyPlayer} from '@review-motion/settlement-player.mjs';
import {studyDuration} from '@review-motion/settlement-volume.mjs';
import {createMaterials} from '@review-motion/material.mjs';
import {seamlessRenderer} from '@review-motion/mesh-renderer.mjs';
import {durations,createSequence,ingestion,ease} from '@review-motion/mr-b-state.mjs';
const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d');
const Renderer=seamlessRenderer(spine.SkeletonRenderer),renderer=new Renderer(ctx);renderer.triangleRendering=true;
let studyPlayer,studyInfo,lastTick=-1,rig,materials,raf=0,last=0,elapsed=0,clipTime=0,clip='',wait=0,done=false,frames=0,sequence=createSequence(),returnPose=null,runtimeError='';
let config={kind:'thinking',stage:'answer',token:0,dark:false,reduced:false,visible:true,lines:[],count:1,title:'知识卡片'};
const send=(type,value={})=>window.webkit?.messageHandlers.mrB?.postMessage({type,token:config.token,...value});
function choose(){const next=sequence.next(config.kind,config.stage==='organize');clip=next.clip;wait=next.wait;clipTime=0;}
function reset(){elapsed=clipTime=0;done=false;sequence=createSequence();clip=config.kind==='thinking'?'mr_receive':config.kind==='idle'?'idle_look':config.kind;wait=1;returnPose=null;}
function duration(){return studyDuration[clip]??durations[clip]??rig.data.findAnimation(clip)?.duration??1;}
function apply(dt){
 if(studyDuration[config.kind]){if(!config.paused&&!done&&!config.reduced){clipTime=Math.min(duration(),clipTime+dt);if(clipTime>=duration())finish();}return;}
 const s=rig.skeleton;s.setToSetupPose();
 if(config.reduced||config.kind==='rest'){s.updateWorldTransform(spine.Physics.none);return;}
 if(config.kind==='settle'&&returnPose){
  elapsed=Math.min(.24,elapsed+dt);const mix=1-ease(elapsed/.24);
  for(let i=0;i<s.bones.length;i++){const b=s.bones[i],p=returnPose.bones[i];for(const key of ['x','y','rotation','scaleX','scaleY'])b[key]+=(p[key]-b[key])*mix;}
  s.drawOrder=returnPose.order.slice();for(let i=0;i<s.slots.length;i++){s.slots[i].color.a+=(returnPose.alpha[i]-s.slots[i].color.a)*mix;s.slots[i].deform=returnPose.deform[i].map(v=>v*mix);}if(elapsed>=.24)finish();s.updateWorldTransform(spine.Physics.none);return;
 }
 elapsed+=dt;
 if(!done){clipTime+=dt;if(['thinking','idle'].includes(config.kind)&&clipTime>=duration()+wait)choose();}
 rig.data.findAnimation(clip)?.apply(s,0,Math.min(clipTime,duration()),false,[],1,spine.MixBlend.replace,spine.MixDirection.mixIn);
 if(!['thinking','idle','settle'].includes(config.kind)&&clipTime>=duration())finish();
 s.updateWorldTransform(spine.Physics.none);
}
function finish(){if(!done){done=true;send('finished');}}
function rounded(x,y,w,h,r,fill,stroke){ctx.beginPath();ctx.roundRect(x,y,w,h,r);if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.stroke();}}
function drawScene(w,h){
 if(studyDuration[config.kind]){const t=config.reduced?duration():clipTime;studyInfo=studyPlayer.draw(config.kind,t,w,h,config);if(Math.abs(t-lastTick)>=.09){lastTick=t;send('studyTime',{time:t});}return;}
 const settlement=config.kind.startsWith('mr_ingest'),review=config.kind==='mr_review';
 const ink=config.dark?'#ededed':'#242424',muted=config.dark?'#aaaaaa':'#777777';
 let x=w/2,y=h*.49,scale=config.framing==='ambient'?Math.min(w/410,h/460):Math.min(w/390,h/340);
 let p;
 if(settlement||review){
  const fit=Math.min(w/520,h/268);ctx.save();ctx.translate((w-520*fit)/2,(h-268*fit)/2);ctx.scale(fit,fit);ctx.translate(0,24);
  const t=config.reduced?6:Math.min(clipTime,duration());
  p=ingestion(t,config.kind==='mr_ingest_short');
  if(settlement){
   ctx.font='14px -apple-system, sans-serif';
   const lines=(config.lines.length?config.lines:[config.title]).slice(0,3);
   lines.forEach((line,i)=>{
    const letters=Array.from(line).slice(0,22),reverse=i%2===1,n=letters.length;
    letters.forEach((c,j)=>{const position=(j+.5)/n;ctx.globalAlpha=(reverse?1-position:position)<p.removed[i]?0:1;ctx.fillStyle=muted;ctx.fillText(c,125+j*12,58+i*42);});
   });ctx.globalAlpha=1;
   x=p.x;y=p.y;scale=.57;
   if(p.card>0||config.reduced){
    const k=config.reduced?1:p.card;ctx.save();ctx.globalAlpha=k;ctx.translate(0,(1-k)*18);
    rounded(92,60,248,110,18,config.dark?'#323232':'#ffffff',config.dark?'#565656':'#dddddd');
    ctx.fillStyle=muted;ctx.font='12px -apple-system';ctx.fillText(config.language==='en'?`${config.count} knowledge cards`:config.count>1?`${config.count} 张知识卡片`:'知识卡片',112,87);
    ctx.fillStyle=ink;ctx.font='600 17px -apple-system';let title=config.title;if(ctx.measureText(title).width>208){let letters=Array.from(title);while(letters.length&&ctx.measureText(letters.join('')+'…').width>208)letters.pop();title=letters.join('')+'…';}ctx.fillText(title,112,117);
    ctx.fillStyle=muted;ctx.font='12px -apple-system';ctx.fillText(config.language==='en'?'Saved for review':'已整理 · 可随时复习',112,145);ctx.restore();
   }
  }else{
   const t=config.reduced?3:Math.min(clipTime,3),gather=ease((t-.2)/.9);
   for(let i=2;i>=0;i--)rounded(132+i*(18-14*gather),72+i*(18-14*gather),176,105,12,config.dark?'#343434':'#fff',config.dark?'#666':'#ddd');
   x=380;y=112;scale=.52;
   const press=ease((t-1.28)/.28),release=ease((t-1.72)/.35),stampX=338-118*press+118*release,stampY=63+47*press-47*release;
   if(t>.9&&t<2.25){ctx.save();ctx.globalAlpha=ease((t-.9)/.2)*(1-ease((t-2.08)/.17));ctx.translate(stampX,stampY);rounded(-8,-19,16,22,5,ink);rounded(-23,0,46,10,4,ink);ctx.restore();}
   // The native label below supplies localized semantics; this is an unlettered stamp.
   if(t>=1.65){ctx.save();ctx.translate(220,123);ctx.rotate(-.09);ctx.strokeStyle=ink;ctx.lineWidth=2;ctx.beginPath();ctx.roundRect(-26,-22,52,44,9);ctx.stroke();ctx.beginPath();ctx.moveTo(-11,0);ctx.lineTo(-2,9);ctx.lineTo(13,-10);ctx.stroke();ctx.restore();}
  }
 }
 ctx.save();ctx.translate(x,y);ctx.scale(scale,-scale);renderer.draw(rig.skeleton);ctx.restore();
 if(settlement&&p.ink>0&&!config.reduced){
  // Small transferred glyphs follow the actual body bone matrix, including roll.
  const b=rig.skeleton.findBone('body');ctx.save();ctx.translate(x+scale*b.worldX,y-scale*b.worldY);ctx.transform(b.a*scale,-b.c*scale,-b.b*scale,b.d*scale,0,0);ctx.globalAlpha=p.ink*.72;ctx.fillStyle=config.dark?'#444':'#ddd';ctx.font='12px -apple-system';
  const chars=Array.from(config.lines.join('')).slice(0,12);chars.forEach((c,i)=>ctx.fillText(c,-52+(i%6)*18,22+Math.floor(i/6)*17));ctx.restore();
 }
 if(settlement||review)ctx.restore();
}
function paint(dt){
 const {width:w,height:h}=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2);
 if(canvas.width!==Math.round(w*d)||canvas.height!==Math.round(h*d)){canvas.width=Math.round(w*d);canvas.height=Math.round(h*d);}
 ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,w,h);renderer.pixelRatio=d;renderer.eyeOutline=config.dark;
 renderer.materialImages=materials('graphite',config.dark,clip==='recall');apply(dt);drawScene(w,h);frames++;
}
function frame(now){raf=0;if(!rig)return;const gap=(now-(last||now))/1000,dt=studyDuration[config.kind]?gap:Math.min(.05,gap);last=now;try{paint(config.visible?dt:0);}catch(error){runtimeError=String(error);done=true;send('failed',{message:runtimeError});return;}if(config.visible&&!config.reduced&&!config.paused&&!done&&config.kind!=='rest')raf=requestAnimationFrame(frame);else last=0;}
function wake(){if(rig&&!raf)raf=requestAnimationFrame(frame);}
window.mrB={setState(next){
 const old=config,changed=old.token!==next.token||old.kind!==next.kind;
 if(next.kind==='settle'&&old.kind!=='settle'&&rig)returnPose={bones:rig.skeleton.bones.map(b=>Object.fromEntries(['x','y','rotation','scaleX','scaleY'].map(k=>[k,b[k]]))),alpha:rig.skeleton.slots.map(s=>s.color.a),deform:rig.skeleton.slots.map(s=>Array.from(s.deform)),order:rig.skeleton.drawOrder.slice()};
 config={...old,...next};
 if(changed){if(config.kind==='settle'){elapsed=0;done=false;}else reset();}
 if(studyDuration[config.kind]&&next.seekToken!==old.seekToken&&next.seekTime!=null){clipTime=Math.max(0,Math.min(duration(),next.seekTime));done=clipTime>=duration();lastTick=-1;}
 if(config.reduced)done=false;
 if(!config.visible){cancelAnimationFrame(raf);raf=0;last=0;if(rig)paint(0);return;}
 if(old.visible!==config.visible||old.reduced!==config.reduced||old.paused!==config.paused)last=0;wake();
},inspect(){return {study:studyInfo,runtimeError,ready:!!rig,frames,animating:!!raf,clip,clipTime,done,config};}};
new ResizeObserver(wake).observe(canvas);
try{
 const asset=JSON.parse(document.getElementById('rig-data').textContent),atlas=new spine.TextureAtlas(asset.atlas),sources=[];
 await Promise.all(atlas.pages.map(async page=>{const image=new Image();image.src=asset.images[page.name];await image.decode();page.setTexture(new spine.CanvasTexture(image));sources.push([page.name,image]);}));
 materials=createMaterials(sources,(w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h;return c;});
 studyPlayer=await createStudyPlayer(spine,ctx,JSON.parse(document.getElementById('study-logo').textContent),{bodyTexture:dark=>materials('graphite',dark).get(sources.find(([name])=>name==='body.png')[1])});
 const data=new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(asset.json);rig={data,skeleton:new spine.Skeleton(data)};reset();send('ready');wake();
}catch(error){send('failed',{message:String(error)});}
