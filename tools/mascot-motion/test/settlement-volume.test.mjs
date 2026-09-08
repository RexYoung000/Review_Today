import test from 'node:test';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {TextureAtlas,FakeTexture,AtlasAttachmentLoader,SkeletonJson,Skeleton,Physics,MixBlend,MixDirection} from '@esotericsoftware/spine-core';
import {scene,walking,stamping,bodySurface,project,spineData,applyScene,bakeStudy,studyDuration} from '../src/settlement-volume.mjs';
function load(json){const names=[...new Set(Object.values(json.skins[0].attachments).flatMap(a=>Object.values(a).map(x=>x.path)))],atlas=new TextureAtlas(names.map(name=>`${name}.png\nsize: 64,64\n${name}\nbounds: 0,0,64,64\n`).join('\n'));for(const page of atlas.pages)page.setTexture(new FakeTexture({width:64,height:64}));const data=new SkeletonJson(new AtlasAttachmentLoader(atlas)).readSkeletonData(json);return {data,skeleton:new Skeleton(data)};}
const area=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
test('new projected meshes reach the official Spine world vertices, not zero-offset geometry',()=>{
 for(const kind of Object.keys(studyDuration)){
  const rig=load(spineData(scene(kind,0)));
  for(const t of [0,1.8,3.7,studyDuration[kind]]){const f=scene(kind,t);applyScene(rig.skeleton,f);
   for(const name of ['bread_12_32','eye0_0_0',kind==='walk_study'?'source':'logo']){const p=f.patches.find(p=>p.id===name),slot=rig.skeleton.findSlot(name),v=new Float32Array(8);slot.getAttachment().computeWorldVertices(slot,0,8,v,0,2);assert.ok(v.every((x,i)=>Math.abs(x-p.points.flatMap(project)[i])<.001),`${kind} ${name} collapses`);}
  }
 }
});
test('walking deforms the lower edge locally while the upper body and face retain their orientation',()=>{
 let oldX=-1,maxWave=0;
 const rest=bodySurface('walk_study',0),top=rest(0,-.4),foot=rest(0,1.4);
 for(let t=.7;t<=5.1;t+=.07){const p=walking(t),fn=bodySurface('walk_study',t);assert.ok(p.x>=oldX);oldX=p.x;
  const upper=fn(0,-.4),lower=fn(0,1.4);
  assert.ok(Math.abs(upper[0]-p.x-(top[0]-118))<.0001,'Face rotates or drifts');
  assert.ok(Math.abs(upper[1]-top[1])<.0001,'Upper body waves with the foot');
  maxWave=Math.max(maxWave,Math.abs(lower[1]-foot[1]));
  for(let a=0;a<Math.PI*2;a+=.2)for(let v=-1.5;v<=1.5;v+=.2)assert.ok(fn(a,v).every(Number.isFinite)&&fn(a,v)[2]>=0);
 }
 assert.ok(maxWave>12,'Lower edge does not visibly undulate');
 const end=bodySurface('walk_study',6.4);assert.ok(Math.abs(end(0,1.4)[1]-foot[1])<.001,'Foot fails to return to original silhouette');
});
test('text disappears behind the body only after being covered, and no body or ground ink is generated',()=>{
 let oldCut=230,hadPartial=false;
 for(let t=0;t<=6.4;t+=.05){const f=scene('walk_study',t),p=walking(t);assert.ok(f.meta.erasedX>=oldCut);oldCut=f.meta.erasedX;
  assert.ok(f.meta.erasedX<=Math.max(230,p.x)+.001,'Text disappears before the covered contact band passes');
  assert.ok(!f.patches.some(p=>p.material==='ink'||p.id.startsWith('ink_')),'A transferred mark remains');
  if(oldCut>230&&oldCut<450)hadPartial=true;
 }
 assert.equal(oldCut,450);assert.ok(hadPartial);
 // For each erased portion, an earlier body position actually covered the
 // entire text height. Merely timing a fade without contact would fail here.
 const contains=(polygon,x,y)=>{let inside=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])inside=!inside;}return inside;};
 const samples=[];for(let t=.7;t<5.1;t+=.025){const fn=bodySurface('walk_study',t);samples.push({cut:walking(t).erasedX,polygon:Array.from({length:96},(_,i)=>{const a=i/96*Math.PI*2;return fn(Math.cos(a)>=0?Math.PI/2:-Math.PI/2,Math.asin(Math.sin(a)));})});}
 for(let x=230;x<=450;x+=5)for(const y of [216,225,234])assert.ok(samples.some(({cut,polygon})=>cut<x&&contains(polygon,x,y)),`Text at ${x},${y} disappears without earlier coverage`);

});
test('stamp stops above the card before normal descent, rubber contacts before R is imprinted',()=>{
 let oldHeight=Infinity;
 for(let t=4.15;t<=4.55;t+=.01){const p=stamping(t);assert.equal(p.stamp.x,281);assert.equal(p.stamp.y,207);assert.ok(p.stamp.z<=oldHeight);oldHeight=p.stamp.z;assert.ok(p.stamp.z-2>=p.card.z+2.2-.00001);assert.equal(p.imprinted,false);}
 const p=stamping(4.55);assert.ok(Math.abs(p.stamp.z-2-(p.card.z+2.2))<.00001);assert.equal(p.imprinted,true);assert.ok(stamping(5.3).stamp.z>p.stamp.z+60);
 for(const t of [0,.7,1.5,2.3,4.6,7.2]){const f=scene('stamp_study',t),logo=f.patches.find(p=>p.id==='logo');assert.equal(logo.enabled,t>=4.55);assert.ok(f.meta.card.z>=2);}
});
test('visible projected body surfaces are finite, face outward and remain inside fixed framing',()=>{
 for(const kind of Object.keys(studyDuration))for(let t=0;t<=studyDuration[kind];t+=.12){const f=scene(kind,t);
  for(const p of f.patches.filter(p=>p.visible&&p.enabled!==false)){const points=p.points.map(project);assert.ok(points.flat().every(Number.isFinite));assert.ok(points.every(([x,y])=>x>=0&&x<=760&&y>=0&&y<=400),`${kind} ${p.id} outside at ${t}`);
   if(p.id.startsWith('bread_'))assert.ok(area(points[0],points[1],points[2])>-.12&&area(points[2],points[3],points[0])>-.12,`Unexpected visible fold at ${kind} ${t} ${p.id}`);
  }
 }
});
test('exported deform and draw order timelines reproduce authored sample frames in official runtime',()=>{
 // Coarse sampling keeps this contract quick; distribution exports at 30 fps.
 for(const kind of Object.keys(studyDuration)){
  const json=bakeStudy(kind,5),rig=load(json),animation=rig.data.findAnimation(kind);assert.ok(animation);
  for(const t of [0,1,2,4,6]){rig.skeleton.setToSetupPose();animation.apply(rig.skeleton,0,t,false,[],1,MixBlend.replace,MixDirection.mixIn);rig.skeleton.updateWorldTransform(Physics.none);const f=scene(kind,t);
   for(const p of f.patches.filter(p=>p.visible&&p.enabled!==false).filter((_,i)=>i%53===0)){const slot=rig.skeleton.findSlot(p.id),a=slot.getAttachment(),v=new Float32Array(8);a.computeWorldVertices(slot,0,8,v,0,2);assert.ok(v.every((x,i)=>Math.abs(x-p.points.flatMap(project)[i])<.02),`${kind} export ${p.id} at ${t}`);assert.equal(slot.color.a,1);}
  }
 }
});

test('the body edge supports the card underside and conforms to the middle of the stamp handle',()=>{
 for(const t of [1.85,2.05,2.3]){const p=stamping(t),contact=bodySurface('stamp_study',t)(-Math.PI/2,0);assert.ok(Math.abs(contact[2]-p.card.z)<.001);assert.ok(Math.abs(contact[0]-p.card.x)<81 && Math.abs(contact[1]-p.card.y)<52);}
 for(const t of [3.9,4.3,4.55,5.2]){const p=stamping(t),point=bodySurface('stamp_study',t)(-Math.PI/2,0),r=Math.hypot(point[0]-p.stamp.x,point[1]-p.stamp.y);assert.ok(r>=10.6&&r<=11,'Side is not wrapping the shaft');assert.ok(point[2]>p.stamp.z+20&&point[2]<p.stamp.z+38,'Grip obscures cap or floats below handle');}
});

// Visual identity is a runtime contract too: use the actual existing texture,
// and make sure the final renderer does not apply a new body lighting model.
test('study body reuses the daily contour and material without an extra highlight',async()=>{
 const {createCanvas,loadImage}=await import('@napi-rs/canvas');
 const {CanvasTexture}=await import('@esotericsoftware/spine-canvas');
 const core=await import('@esotericsoftware/spine-core');
 const {createMaterials}=await import('../../../brand/refresh-2026-09/motion-rig/material.mjs');
 const {createStudyPlayer}=await import('../src/settlement-player.mjs');
 const {contour,referencePoint}=await import('../src/settlement-character.mjs');
 for(const p of contour){const a=Math.atan2(-p.y,p.x),q=referencePoint(Math.cos(a)>=0?Math.PI/2:-Math.PI/2,Math.asin(Math.sin(a)));assert.ok(Math.abs(q.x-p.x*.7)<.001&&Math.abs(q.y+p.y*.7)<.001,'Silhouette no longer matches original');}
 const body=await loadImage(fileURLToPath(new URL('../../../brand/refresh-2026-09/motion-rig/data/images/body.png',import.meta.url))),material=createMaterials([['body.png',body]],createCanvas);
 const canvas=createCanvas(760,400),ctx=canvas.getContext('2d');
 const player=await createStudyPlayer({...core,CanvasTexture},ctx,fileURLToPath(new URL('../../../brand/refresh-2026-09/masters/mark-alpha.png',import.meta.url)),{createCanvas,loadImage,bodyTexture:dark=>material('graphite',dark).get(body)});
 for(const dark of [false,true]){ctx.clearRect(0,0,760,400);player.draw('walk_study',0,760,400,{dark,language:'zh'});
  const p=project(bodySurface('walk_study',0)(0,0)),actual=ctx.getImageData(Math.round(p[0]),Math.round(p[1]),1,1).data,original=material('graphite',dark).get(body).getContext('2d').getImageData(629,614,1,1).data;
  assert.ok(Math.abs(actual[0]-original[0])<4,'New lighting changed body material');assert.equal(actual[0],actual[1]);assert.equal(actual[1],actual[2]);
 }
});
