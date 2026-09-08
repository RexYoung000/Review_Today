// Offline editable data + clearly labelled authoring frames. Native recordings
// remain a separate evidence source; these renders never stand in for them.
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import * as core from '@esotericsoftware/spine-core';
import {CanvasTexture} from '@esotericsoftware/spine-canvas';
import {createCanvas,loadImage,GlobalFonts} from '@napi-rs/canvas';
import {createStudyPlayer} from './settlement-player.mjs';
import {bakeStudy} from './settlement-volume.mjs';
import {root,previewRoot} from './paths.mjs';
import {createMaterials} from '../../../brand/refresh-2026-09/motion-rig/material.mjs';
GlobalFonts.registerFromPath('/System/Library/Fonts/STHeiti Medium.ttc','PingFang SC');
const folder=resolve(root,'output/mr-b-preview/contact-studies');await mkdir(folder,{recursive:true});
const body=await loadImage(resolve(previewRoot,'data/images/body.png')),materials=createMaterials([['body.png',body]],createCanvas);
const canvas=createCanvas(760,400),ctx=canvas.getContext('2d'),player=await createStudyPlayer({...core,CanvasTexture},ctx,resolve(root,'brand/refresh-2026-09/masters/mark-alpha.png'),{createCanvas,loadImage,bodyTexture:dark=>materials('graphite',dark).get(body)});
const frames={walk_study:[0,1.5,2.6,3.5,4.4,6.4],stamp_study:[0,1.5,2.3,3.8,4.55,5.3,7.2]};
const report={source:'offline authoring renders, not native screenshots',fps:30,studies:{}};
for(const [kind,times] of Object.entries(frames)){
 const path=resolve(folder,kind);await mkdir(path,{recursive:true});
 for(const time of times){ctx.fillStyle='#f7f7f7';ctx.fillRect(0,0,760,400);player.draw(kind,time,760,400,{dark:false,language:'zh'});await writeFile(resolve(path,`frame-${time}.png`),canvas.toBuffer('image/png'));}
 const textures=player.exportTextures();for(const [name,texture] of Object.entries(textures))await writeFile(resolve(path,name+'.png'),texture.toBuffer('image/png'));
 await writeFile(resolve(path,'study.atlas'),Object.keys(textures).map(name=>`${name}.png\nsize: ${textures[name].width},${textures[name].height}\nfilter: Linear,Linear\n${name}\nbounds: 0,0,${textures[name].width},${textures[name].height}\n`).join('\n'));
 const json=bakeStudy(kind);await writeFile(resolve(path,'study.json'),JSON.stringify(json));
 report.studies[kind]={slots:json.slots.length,frames:times,notes:'Spine 4.2 mesh/deform, alpha/rgb and drawOrder; original character contour/material and local walking deformation. Native renderer adds per-pixel depth, prop shading and contact shadows; editor playback is not claimed identical or manually verified.'};console.log('Exported',kind,json.slots.length,'Spine mesh slots');
}
await writeFile(resolve(folder,'manifest.json'),JSON.stringify(report,null,2));
