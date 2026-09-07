import {createCanvas,loadImage} from '@napi-rs/canvas';
import {SkeletonRenderer} from '@esotericsoftware/spine-canvas';
import {seamlessRenderer} from '../../../brand/refresh-2026-09/motion-rig/mesh-renderer.mjs';
const MeshRenderer=seamlessRenderer(SkeletonRenderer);
import * as spine from '@esotericsoftware/spine-core';
import {createVoiceState,advanceVoice,applyVoice,drawVoiceScene} from '../../../brand/refresh-2026-09/motion-rig/voice-scene.mjs';
import {loadRig,sample} from './runtime.mjs';
import {mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {workRoot} from './paths.mjs';
export const conversationMode=time=>time<3?'listening':time<6.8?'thinking':time<10.8?'speaking':'idle';
export async function renderer(json,size=640,dark=false,animation='recall'){
  const rig=await loadRig(json,loadImage);const canvas=createCanvas(size,size*.75),ctx=canvas.getContext('2d');
  const renderer=new MeshRenderer(ctx);renderer.triangleRendering=true;
  const voice=createVoiceState();let previous=0;
  return time=>{
    if(animation!=='recall'){
      for(let t=previous;t<time;t+=1/60)advanceVoice(voice,Math.min(1/60,time-t),animation==='conversation'?conversationMode(t):animation==='thinking'&&t>=4.8?'idle':animation,.85);previous=time;
      applyVoice(spine,rig,voice);ctx.setTransform(1,0,0,1,0,0);drawVoiceScene(ctx,renderer,rig,voice,size,size*.75,{dark});
      ctx.globalCompositeOperation='destination-over';ctx.fillStyle=dark?'#141918':'#f7f6f2';ctx.fillRect(0,0,size,size*.75);ctx.globalCompositeOperation='source-over';if(animation==='conversation'){ctx.fillStyle=dark?'#b4c8bb':'#476055';ctx.font='14px sans-serif';ctx.fillText({listening:'LISTENING / INWARD',thinking:'THINKING / BOUNCE',speaking:'SPEAKING / OUTWARD',idle:'STOP / SETTLE'}[conversationMode(time)],28,40);}return canvas.toBuffer('image/png');
    }
    sample(rig,time);ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle=dark?'#141918':'#f7f6f2';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.translate(size/2,size*.75/2);ctx.scale(size/440,-size/440);renderer.draw(rig.skeleton);return canvas.toBuffer('image/png');};
}
export async function renderFrame(json,time,size=640,dark=false,animation='recall'){const frame=await renderer(json,size,dark,animation);return frame(time);}
export async function renderClip(json,name='recall',animation='recall'){
  if(!/^[a-z0-9_-]{1,48}$/.test(name))throw Error('Invalid clip name');
  const dir=resolve(workRoot,'renders');await mkdir(dir,{recursive:true});
  const destination=resolve(dir,name+'-'+Date.now()+'.mp4'),fps=24,duration=animation==='recall'?json.animations.recall.slots.fragment.alpha.at(-1).time:animation==='conversation'?14:8;
  const draw=await renderer(json,640,false,animation),child=spawn('ffmpeg',['-v','error','-f','image2pipe','-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',destination],{stdio:['pipe','ignore','pipe']});
  child.stdin.on('error',()=>{});
  let stderr='';child.stderr.on('data',b=>stderr=(stderr+b).slice(-4000));
  const done=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',code=>code===0?resolve():reject(Error('ffmpeg: '+stderr)));});
  // Prevent an unhandled early executable error while frames are being written.
  done.catch(()=>{});
  try{for(let i=0;i<Math.ceil(duration*fps);i++){const data=draw(i/fps);await new Promise((resolve,reject)=>child.stdin.write(data,e=>e?reject(e):resolve()));}child.stdin.end();await done;}catch(e){child.kill();await done.catch(()=>{});throw e;}
  return {destination,duration,fps,renderer:'official Spine Canvas; offline render, not UI recording'};
}
