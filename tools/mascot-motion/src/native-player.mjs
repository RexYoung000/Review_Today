import {createMaterials} from '@review-motion/material.mjs';
import {seamlessRenderer} from '@review-motion/mesh-renderer.mjs';
import {createReturnState} from '@review-motion/return-state.mjs';
import {createVoiceState,advanceVoice,applyVoice,drawVoiceScene,contactGeometry,contactMoving} from '@review-motion/voice-scene.mjs';
const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d'),Renderer=seamlessRenderer(spine.SkeletonRenderer),renderer=new Renderer(ctx);
renderer.triangleRendering=true;
let config={surface:'recall',mode:'idle',level:0,reduced:false,dark:false,visible:true,rate:1,material:'current'},rig,materials,voice,configured=false,raf=0,last=0,time=0,returnState,returnElapsed=0,frames=0;
const send=(type,detail='')=>window.webkit?.messageHandlers.mascot?.postMessage({type,detail});
function poseRecall(dt){
 const s=rig.skeleton;s.setToSetupPose();
 if(config.reduced){time=0;returnState=null;}
 else if(returnState){returnState.update(dt);returnState.apply(s);returnElapsed+=dt;if(returnElapsed>=.24){returnState=null;time=0;s.setToSetupPose();}}
 else if(config.mode==='thinking'){time=(time+dt)%rig.data.findAnimation('recall').duration;rig.data.findAnimation('recall').apply(s,0,time,false,[],1,spine.MixBlend.replace,spine.MixDirection.mixIn);}
 s.updateWorldTransform(spine.Physics.none);
}
function paint(dt){
 const {width,height}=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2);
 if(canvas.width!==Math.round(width*d)||canvas.height!==Math.round(height*d)){canvas.width=Math.round(width*d);canvas.height=Math.round(height*d);}
 ctx.setTransform(d,0,0,d,0,0);
 renderer.materialImages=materials?.(config.material,config.dark,config.surface==='recall'&&(config.mode==='thinking'||!!returnState),config.palette);
 if(config.surface==='voice'){
   advanceVoice(voice,dt,config.mode,config.level,config.reduced);applyVoice(spine,rig,voice);
   drawVoiceScene(ctx,renderer,rig,voice,width,height,{dark:config.dark,compact:width<300,material:config.material,palette:config.palette});
 }else{
   poseRecall(dt);ctx.clearRect(0,0,width,height);ctx.save();ctx.translate(width/2,height*.49);const scale=Math.min(width/410,height/340);ctx.scale(scale,-scale);renderer.draw(rig.skeleton);ctx.restore();
 }
 frames++;
}
function moving(){return config.surface==='recall'?(config.mode==='thinking'||!!returnState):(config.mode==='thinking'||(['listening','speaking'].includes(config.mode)&&config.level>0)||contactMoving(voice.contact));}
function frame(now){raf=0;if(!rig)return;const dt=Math.min(.05,(now-(last||now))/1000)*config.rate;last=now;paint(config.visible?dt:0);if(config.visible&&!config.reduced&&moving())raf=requestAnimationFrame(frame);else last=0;}
function wake(){if(!raf&&rig&&configured)raf=requestAnimationFrame(frame);}
window.mascotMotion={
 setState(next){
   configured=true;
   const previous=config;
   config={surface:next.surface==='voice'?'voice':'recall',mode:['listening','thinking','speaking','idle'].includes(next.mode)?next.mode:'idle',level:Math.max(0,Math.min(1,Number(next.level)||0)),reduced:!!next.reduced,dark:!!next.dark,visible:!!next.visible,rate:next.rate===.5?.5:1,material:next.material==='graphite'?'graphite':'current',palette:next.palette};
   if(rig&&previous.surface!==config.surface){returnState=null;time=0;voice=createVoiceState(contactGeometry(spine,rig));}
   if(rig&&config.surface==='recall'&&previous.mode==='thinking'&&config.mode!=='thinking'&&!config.reduced){returnState=createReturnState(spine,rig,time);returnElapsed=0;}
   if(config.mode==='thinking'&&previous.mode!=='thinking'&&returnState){returnState=null;time=0;}
   if(!config.visible){cancelAnimationFrame(raf);raf=0;last=0;if(rig)paint(0);return;}
   if(previous.visible!==config.visible||previous.reduced!==config.reduced||previous.surface!==config.surface)last=0;
   wake();
 },
 inspect(){return {ready:!!rig,frames,animating:!!raf,config,time,voice:voice?{elapsed:voice.time,quiet:voice.contact.quiet,barResidual:Math.max(...voice.contact.bars.map((h,i)=>Math.max(Math.abs(h-10),Math.abs(voice.contact.velocities[i])))),height:voice.contact.height,phase:voice.contact.phase,area:voice.contact.soft.areaRatio,contacts:voice.contact.soft.contacts.length}:null};}
};
new ResizeObserver(wake).observe(canvas);
try{
 const asset=JSON.parse(document.getElementById('rig-data').textContent),atlas=new spine.TextureAtlas(asset.atlas);
 const materialSources=[];
 await Promise.all(atlas.pages.map(async page=>{const image=new Image();image.src=asset.images[page.name];await image.decode();page.setTexture(new spine.CanvasTexture(image));materialSources.push([page.name,image]);}));
 materials=createMaterials(materialSources,(w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h;return c;});
 const data=new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(asset.json);rig={data,skeleton:new spine.Skeleton(data)};voice=createVoiceState(contactGeometry(spine,rig));send('ready');wake();
}catch(e){send('failed',String(e));}
