// Offline editable data + clearly labelled authoring frames. Native recordings
// remain a separate evidence source; these renders never stand in for them.
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import * as core from '@esotericsoftware/spine-core';
import {CanvasTexture,SkeletonRenderer} from '@esotericsoftware/spine-canvas';
import {createCanvas,loadImage} from '@napi-rs/canvas';
import {createStudyPlayer} from './settlement-player.mjs';
import {bakeStudy} from './settlement-scene.mjs';
import {root,previewRoot} from './paths.mjs';
import {createMaterials} from '../../../brand/refresh-2026-09/motion-rig/material.mjs';
const folder=resolve(root,'output/mr-b-preview/line-beats-2d');await mkdir(folder,{recursive:true});
const body=await loadImage(resolve(previewRoot,'data/images/body.png')),materials=createMaterials([['body.png',body]],createCanvas);
const canvas=createCanvas(760,400),ctx=canvas.getContext('2d'),player=await createStudyPlayer({...core,CanvasTexture,SkeletonRenderer},ctx,resolve(root,'brand/refresh-2026-09/masters/mark-alpha.png'),{createCanvas,loadImage,bodyTexture:dark=>materials('graphite',dark).get(body)});
const frames={walk_study:[0,.5,.85,1.35,2.05,3.25,4.6],stamp_study:[0,.5,.7,1.2,1.8,2.12,2.4,3.4,4.8]};
const report={source:'offline authoring renders, not native screenshots',fps:30,studies:{}};
for(const [kind,times] of Object.entries(frames)){
 const path=resolve(folder,kind);await mkdir(path,{recursive:true});
 for(const time of times){ctx.fillStyle='#f7f7f7';ctx.fillRect(0,0,760,400);player.draw(kind,time,760,400,{dark:false,language:'zh'});await writeFile(resolve(path,`frame-${time}.png`),canvas.toBuffer('image/png'));}
 const textures=player.exportTextures();for(const [name,texture] of Object.entries(textures))await writeFile(resolve(path,name+'.png'),texture.toBuffer('image/png'));
 await writeFile(resolve(path,'study.atlas'),Object.keys(textures).map(name=>`${name}.png\nsize: ${textures[name].width},${textures[name].height}\nfilter: Linear,Linear\n${name}\nbounds: 0,0,${textures[name].width},${textures[name].height}\n`).join('\n'));
 const json=bakeStudy(kind);await writeFile(resolve(path,'study.json'),JSON.stringify(json));
 report.studies[kind]={slots:json.slots.length,frames:times,notes:'Spine 4.2 flat mesh/deform, alpha and drawOrder. The same official Canvas renderer and original daily contour/material are used in native and offline rendering. No literal text, body ink, perspective depth or custom lighting. 30 fps export is runtime-tested; Spine editor import is not manually verified.'};console.log('Exported',kind,json.slots.length,'Spine mesh slots');
}
await writeFile(resolve(folder,'manifest.json'),JSON.stringify(report,null,2));
