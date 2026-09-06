import {createCanvas,loadImage} from '@napi-rs/canvas';
import {SkeletonRenderer} from '@esotericsoftware/spine-canvas';
import {seamlessRenderer} from '../../../brand/refresh-2026-09/motion-rig/mesh-renderer.mjs';
const MeshRenderer=seamlessRenderer(SkeletonRenderer);
import {loadRig,sample} from './runtime.mjs';
import {mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {workRoot} from './paths.mjs';
export async function renderer(json,size=640,dark=false){
  const rig=await loadRig(json,loadImage);const canvas=createCanvas(size,size*.75),ctx=canvas.getContext('2d');
  const renderer=new MeshRenderer(ctx);renderer.triangleRendering=true;
  return time=>{sample(rig,time);ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle=dark?'#141918':'#f7f6f2';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.translate(size/2,size*.75/2);ctx.scale(size/440,-size/440);renderer.draw(rig.skeleton);return canvas.toBuffer('image/png');};
}
export async function renderFrame(json,time,size=640,dark=false){const frame=await renderer(json,size,dark);return frame(time);}
export async function renderClip(json,name='recall'){
  if(!/^[a-z0-9_-]{1,48}$/.test(name))throw Error('Invalid clip name');
  const dir=resolve(workRoot,'renders');await mkdir(dir,{recursive:true});
  const destination=resolve(dir,name+'-'+Date.now()+'.mp4'),fps=24,duration=json.animations.recall.slots.fragment.alpha.at(-1).time;
  const draw=await renderer(json,640),child=spawn('ffmpeg',['-v','error','-f','image2pipe','-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',destination],{stdio:['pipe','ignore','pipe']});
  child.stdin.on('error',()=>{});
  let stderr='';child.stderr.on('data',b=>stderr=(stderr+b).slice(-4000));
  const done=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',code=>code===0?resolve():reject(Error('ffmpeg: '+stderr)));});
  // Prevent an unhandled early executable error while frames are being written.
  done.catch(()=>{});
  try{for(let i=0;i<Math.ceil(duration*fps);i++){const data=draw(i/fps);await new Promise((resolve,reject)=>child.stdin.write(data,e=>e?reject(e):resolve()));}child.stdin.end();await done;}catch(e){child.kill();await done.catch(()=>{});throw e;}
  return {destination,duration,fps,renderer:'official Spine Canvas; offline render, not UI recording'};
}
