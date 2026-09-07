import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {createCanvas,loadImage} from '@napi-rs/canvas';
import * as spine from '@esotericsoftware/spine-core';
import {SkeletonRenderer} from '@esotericsoftware/spine-canvas';
import {loadRig} from './runtime.mjs';
import {createMaterials} from '../../../brand/refresh-2026-09/motion-rig/material.mjs';
import {createIdlePlayer,idleDurations} from '../../../brand/refresh-2026-09/motion-rig/idle-player.mjs';
import {seamlessRenderer} from '../../../brand/refresh-2026-09/motion-rig/mesh-renderer.mjs';
import {root,previewRoot} from './paths.mjs';
const folder=resolve(root,'brand/refresh-2026-09/idle-motion/evidence');await mkdir(folder,{recursive:true});
const json=JSON.parse(await readFile(resolve(previewRoot,'data/mascot.json')));
const rig=await loadRig(json,loadImage),canvas=createCanvas(640,480),ctx=canvas.getContext('2d'),Renderer=seamlessRenderer(SkeletonRenderer),renderer=new Renderer(ctx);renderer.triangleRendering=true;
const sources=rig.atlas.pages.map(p=>[p.name,p.texture.getImage()]),materials=createMaterials(sources,createCanvas);
function draw(player,dark){
 ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle=dark?'#131313':'#f6f6f6';ctx.fillRect(0,0,640,480);
 player.apply(spine,rig);rig.skeleton.updateWorldTransform(spine.Physics.none);renderer.materialImages=materials('graphite',dark);renderer.eyeOutline=dark;
 ctx.save();ctx.translate(320,235);ctx.scale(1.4,-1.4);renderer.draw(rig.skeleton);ctx.restore();return canvas.toBuffer('image/png');
}
for(const [clip,duration] of [...Object.entries(idleDurations),['random',36]]){
 let seed=68;const player=createIdlePlayer(()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;},clip);
 const ff=spawn('ffmpeg',['-v','error','-y','-f','image2pipe','-framerate','24','-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',resolve(folder,clip+'.mp4')],{stdio:['pipe','ignore','pipe']});
 let error='';ff.stderr.on('data',b=>error+=b);const finished=new Promise((ok,no)=>{ff.on('error',no);ff.on('close',n=>n?no(Error(error)):ok());});
 for(let i=0;i<Math.ceil((duration+1.5)*24);i++){
  const image=draw(player,clip==='random'||clip==='idle_book');
  if(!ff.stdin.write(image))await new Promise(r=>ff.stdin.once('drain',r));
  if(i===48&&clip==='idle_book')await writeFile(resolve(folder,'notebook-dark.png'),image);
  player.advance(1/24);
 }
 ff.stdin.end();await finished;
}
for(const dark of [false,true]){const player=createIdlePlayer(()=>0,'idle_look');player.advance(2);await writeFile(resolve(folder,dark?'eyes-dark.png':'eyes-light.png'),draw(player,dark));}
console.log(folder);
