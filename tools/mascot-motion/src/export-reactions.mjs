// Offline editable data + clearly labelled authoring frames. Native recordings
// remain a separate evidence source; these renders never stand in for them.
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import * as core from '@esotericsoftware/spine-core';
import {CanvasTexture,SkeletonRenderer} from '@esotericsoftware/spine-canvas';
import {createCanvas,loadImage} from '@napi-rs/canvas';
import {createStudyPlayer} from './settlement-player.mjs';
import {bakeScene} from './settlement-scene.mjs';
import {root,previewRoot} from './paths.mjs';
import {createMaterials} from '../../../brand/refresh-2026-09/motion-rig/material.mjs';
import {reactionFrame,reactionKinds,reactionDuration} from './reaction-scene.mjs';
const folder=resolve(root,'output/mr-b-preview/answer-reactions');await mkdir(folder,{recursive:true});
const body=await loadImage(resolve(previewRoot,'data/images/body.png')),materials=createMaterials([['body.png',body]],createCanvas);
const canvas=createCanvas(350,340),ctx=canvas.getContext('2d'),player=await createStudyPlayer({...core,CanvasTexture,SkeletonRenderer},ctx,resolve(root,'brand/refresh-2026-09/masters/mark-alpha.png'),{createCanvas,loadImage,bodyTexture:dark=>materials('graphite',dark).get(body)});
const report={source:'Offline authoring frames, not native screenshots',clips:{}};
for(const kind of reactionKinds){
 const path=resolve(folder,kind);await mkdir(path,{recursive:true});
 for(const t of [0,.4,.9,1.4,1.8,2.4,3.2]){ctx.fillStyle='#f7f7f7';ctx.fillRect(0,0,350,340);player.draw(kind,t,350,340,{dark:false},reactionFrame(kind,t));await writeFile(resolve(path,`frame-${t}.png`),canvas.toBuffer('image/png'));}
 const textures=player.exportTextures();for(const [name,texture] of Object.entries(textures))await writeFile(resolve(path,name+'.png'),texture.toBuffer('image/png'));
 await writeFile(resolve(path,'study.atlas'),Object.keys(textures).map(name=>`${name}.png\nsize: ${textures[name].width},${textures[name].height}\nfilter: Linear,Linear\n${name}\nbounds: 0,0,${textures[name].width},${textures[name].height}\n`).join('\n'));
 const json=bakeScene(kind,reactionDuration,t=>reactionFrame(kind,t));await writeFile(resolve(path,'study.json'),JSON.stringify(json));
 report.clips[kind]={duration:reactionDuration,slots:json.slots.length,viewport:reactionFrame(kind,0).viewport,notes:'Real Spine deform timelines using existing contour, UVs and material. Facial attachments remain rigid. Editor import not manually verified.'};console.log('Exported',kind);
}
await writeFile(resolve(folder,'manifest.json'),JSON.stringify(report,null,2));
