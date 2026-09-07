import {createCanvas,loadImage} from '@napi-rs/canvas';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {root} from './paths.mjs';
import {renderer} from './render.mjs';
const json=JSON.parse(await readFile(resolve(root,'brand/refresh-2026-09/motion-rig/data/mascot.json')));
const out=resolve(root,'brand/refresh-2026-09/monochrome-ui/evidence');await mkdir(out,{recursive:true});
const draws={};for(const kind of ['current','graphite'])for(const mode of ['recall','conversation'])draws[kind+mode]=await renderer(json,640,false,mode,kind);
const canvas=createCanvas(1280,550),ctx=canvas.getContext('2d');
const target=resolve(out,'material-motion-comparison.mp4'),fps=24;
const child=spawn('ffmpeg',['-y','-v','error','-f','image2pipe','-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',target],{stdio:['pipe','ignore','pipe']});
let errors='';child.stderr.on('data',b=>errors+=b);child.stdin.on('error',()=>{});
const done=new Promise((r,j)=>{child.on('error',j);child.on('close',code=>code?j(Error(errors)):r());});done.catch(()=>{});
for(let i=0;i<20*fps;i++){
 const t=i/fps,mode=t<6?'recall':'conversation',time=t<6?t:t-6;
 ctx.fillStyle='#f6f6f6';ctx.fillRect(0,0,1280,550);
 for(const [n,kind] of ['current','graphite'].entries())ctx.drawImage(await loadImage(draws[kind+mode](time)),n*640,60);
 ctx.fillStyle='#252525';ctx.font='22px sans-serif';ctx.fillText('CURRENT',28,36);ctx.fillText('TRIAL / BLACK + WHITE',668,36);
 ctx.font='14px sans-serif';ctx.fillText('Offline render · Shared geometry and timing · No audio input',28,539);
 const data=canvas.toBuffer('image/png');if([68,288,455].includes(i))await writeFile(resolve(out,`comparison-${i}.png`),data);
 await new Promise((r,j)=>child.stdin.write(data,e=>e?j(e):r()));
}
child.stdin.end();await done;console.log(target);
