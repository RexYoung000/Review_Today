import {rowTime,rowSpec,rowOffset} from '../src/paragraph-rows.mjs';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {TextureAtlas,FakeTexture,AtlasAttachmentLoader,SkeletonJson,Skeleton,Physics,MixBlend,MixDirection} from '@esotericsoftware/spine-core';
import {scene,walking,stamping,bodyMesh,project,spineData,applyScene,bakeStudy,studyDuration,stepStarts,contactTime,studyLayout} from '../src/settlement-scene.mjs';
import {contour} from '../src/settlement-character.mjs';
function load(json){const names=[...new Set(Object.values(json.skins[0].attachments).flatMap(a=>Object.values(a).map(x=>x.path)))],atlas=new TextureAtlas(names.map(name=>`${name}.png\nsize: 64,64\n${name}\nbounds: 0,0,64,64\n`).join('\n'));for(const page of atlas.pages)page.setTexture(new FakeTexture({width:64,height:64}));const data=new SkeletonJson(new AtlasAttachmentLoader(atlas)).readSkeletonData(json);return {data,skeleton:new Skeleton(data)};}
const area=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
const mesh=(f,id)=>f.patches.find(p=>p.id===id);
function vertices(skeleton,id){const slot=skeleton.findSlot(id),a=slot.getAttachment(),v=new Float32Array(a.worldVerticesLength);a.computeWorldVertices(slot,0,v.length,v,0,2);return v;}

test('2D meshes reach official Spine vertices; layer changes never change projection',()=>{
 assert.deepEqual(project([20,30,0]),project([20,30,90]));
 for(const kind of Object.keys(studyDuration)){
  const rig=load(spineData(scene(kind,0)));
  for(const t of [0,.85,2.12,3.3,studyDuration[kind]]){const f=scene(kind,t);applyScene(rig.skeleton,f);
   for(const p of f.patches){const v=vertices(rig.skeleton,p.id);assert.ok(v.every((x,i)=>Math.abs(x-p.points.flatMap(project)[i])<.001));}
  }
 }
});

test('three step beats erase one abstract line each, then feed remaining lines; never erase on lift',()=>{
 let previous=[0,0,0];
 for(let t=0;t<=4.6;t+=.01){const p=walking(t),f=scene('walk_study',t);
  assert.equal(f.patches.filter(p=>p.material==='line').length,4);
  assert.ok(!f.patches.some(p=>/text|ink/.test(p.material)));
  p.lines.forEach((line,i)=>{
   assert.ok(line.erase>=previous[i]);
   if(line.erase>previous[i]+.00001&&line.erase<1)assert.ok(p.steps[i].contact,'Line clears without a planted step');
   if(p.steps[i].lift>0)assert.equal(line.erase,0,'Erasing while gathering/lifting');
   for(let k=0;k<i;k++)if(p.steps[k].feed>0)assert.equal(p.lines[k].erase,1,'Feeding before the removed row clears');
   assert.ok(Math.abs(line.y-(234+rowOffset(0,i)-p.steps.slice(0,i).reduce((y,s)=>y+s.gap*s.feed,0)))<1e-8);
   if(line.erase>0&&i>0)assert.equal(p.lines[i-1].erase,1);
  });previous=p.lines.map(s=>s.erase);
 }
 assert.deepEqual(previous,[1,1,1]);
 for(let i=0;i<3;i++){assert.equal(walking(rowTime(i,.44)).steps[i].erase,0);assert.equal(walking(rowTime(i,.81)).steps[i].erase,1);}
 assert.deepEqual(scene('walk_study',4.6),scene('walk_study',20));
});

test('the moving planted lobe covers the active erase boundary while upper body stays stable',()=>{
 let deformation=0;
 const base=bodyMesh('walk_study',0);
 for(let i=0;i<3;i++)for(let local=.49;local<.80;local+=.012){const t=rowTime(i,local),p=walking(t),b=bodyMesh('walk_study',t);
  // Locate the lower silhouette where the erasure cursor crosses it.
  const edge=b.points.slice(0,b.hull),ys=[];
  for(let i=0;i<edge.length;i++){const a=edge[i],q=edge[(i+1)%edge.length];if((a[0]<=p.contactX&&q[0]>=p.contactX)||(q[0]<=p.contactX&&a[0]>=p.contactX)){const ratio=(p.contactX-a[0])/(q[0]-a[0]);if(Number.isFinite(ratio))ys.push(a[1]+ratio*(q[1]-a[1]));}}
  assert.ok(Math.max(...ys)>=236.5,`Erase boundary outside planted lobe at ${t}: ${Math.max(...ys)}`);
  b.points.forEach((v,i)=>{const dy=v[1]-base.points[i][1]-(p.y-154);if(base.points[i][1]<162)assert.ok(Math.abs(dy)<.001,'Face-bearing body deforms independently of weight shift');deformation=Math.max(deformation,Math.abs(dy));});
 }
 assert.ok(deformation>10);
 assert.deepEqual(bodyMesh('walk_study',4.6).points,base.points);
});

test('stamp is rigid and body stays unchanged; behind/front handoff is outside the silhouette',()=>{
 const rest=bodyMesh('stamp_study',0).points;
 for(let t=0;t<=4.8;t+=.025){const f=scene('stamp_study',t),s=mesh(f,'stamp'),p=stamping(t);
  assert.deepEqual(mesh(f,'body').points,rest);
  assert.ok(Math.abs(Math.hypot(s.points[1][0]-s.points[0][0],s.points[1][1]-s.points[0][1])-72)<.0001);
  assert.ok(Math.abs(Math.hypot(s.points[2][0]-s.points[1][0],s.points[2][1]-s.points[1][1])-90)<.0001);
  assert.equal(s.layer,t<.7||t>=3.6?5:15);
  assert.deepEqual(mesh(f,'paper').points,mesh(scene('stamp_study',0),'paper').points);
  assert.equal(s.alpha,p.stamp.visible?1:0);
 }
 for(const t of [.7,3.6]){const f=scene('stamp_study',t);assert.ok(Math.min(...mesh(f,'stamp').points.map(p=>p[0]))>Math.max(...rest.map(p=>p[0])),'Painter switch intersects the body');}
 assert.equal(mesh(scene('stamp_study',0),'stamp').alpha,0);assert.equal(mesh(scene('stamp_study',4.8),'stamp').alpha,0);
});

test('stamp settles, lifts, presses straight down; R and the small puff only follow contact',()=>{
 assert.ok(stamping(1.8).stamp.y<stamping(1.35).stamp.y-35);
 let lastY=-Infinity;
 for(let t=2;t<contactTime;t+=.005){const p=stamping(t);assert.equal(p.stamp.x,studyLayout.stampContact.x);assert.ok(Math.abs(p.stamp.angle)<.0001);assert.ok(p.stamp.y>=lastY);lastY=p.stamp.y;assert.equal(p.imprinted,false);assert.equal(p.puff,0);assert.equal(mesh(scene('stamp_study',t),'logo').alpha,0);}
 assert.equal(stamping(contactTime).stamp.y,studyLayout.stampContact.y);assert.equal(stamping(contactTime).imprinted,true);
 assert.ok(stamping(2.3).puff>0);assert.equal(stamping(2.8).puff,0);
 assert.ok(stamping(2.72).stamp.y<studyLayout.stampContact.y-50);assert.equal(mesh(scene('stamp_study',4.8),'logo').alpha,1);
});

test('all flat body triangles preserve winding and stay inside the fixed frame',()=>{
 for(const kind of Object.keys(studyDuration)){
  const base=bodyMesh(kind,0);
  for(let t=0;t<=studyDuration[kind];t+=.025){const f=scene(kind,t),b=mesh(f,'body');
   for(const p of f.patches){assert.ok(p.points.flat().every(Number.isFinite));assert.ok(p.points.every(([x,y])=>x>=0&&x<=760&&y>=0&&y<=400));}
   for(let i=0;i<b.triangles.length;i+=3){const indices=b.triangles.slice(i,i+3),a=area(...indices.map(j=>b.points[j])),a0=area(...indices.map(j=>base.points[j]));assert.ok(a*a0>0,`Fold at ${kind} ${t} triangle ${i}`);}
  }
 }
});

test('30 fps Spine exports reproduce deform, alpha and draw order when seeking both directions',()=>{
 for(const kind of Object.keys(studyDuration)){
  const rig=load(bakeStudy(kind)),animation=rig.data.findAnimation(kind);
  for(const frameIndex of [0,15,26,42,63,70,99,118,137,138,139,204,282,139,138,137,15,0]){const t=Math.min(frameIndex/30,studyDuration[kind]);rig.skeleton.setToSetupPose();animation.apply(rig.skeleton,0,t,false,[],1,MixBlend.replace,MixDirection.mixIn);rig.skeleton.updateWorldTransform(Physics.none);const f=scene(kind,t);
   for(const p of f.patches){const v=vertices(rig.skeleton,p.id);assert.ok(v.every((x,i)=>Math.abs(x-p.points.flatMap(project)[i])<.002),`${kind} ${p.id} ${t}`);assert.ok(Math.abs(rig.skeleton.findSlot(p.id).color.a-p.alpha)<.001,`${kind} ${p.id} alpha at ${t}: ${rig.skeleton.findSlot(p.id).color.a} expected ${p.alpha}`);}
   assert.deepEqual(rig.skeleton.drawOrder.map(s=>s.data.name),[...f.patches].sort((a,b)=>a.layer-b.layer).map(p=>p.id));
  }
 }
});

test('daily contour/material are reused and study pixels are identical in Chinese and English',async()=>{
 const {createCanvas,loadImage}=await import('@napi-rs/canvas');
 const {CanvasTexture,SkeletonRenderer}=await import('@esotericsoftware/spine-canvas');
 const core=await import('@esotericsoftware/spine-core');
 const {createMaterials}=await import('../../../brand/refresh-2026-09/motion-rig/material.mjs');
 const {createStudyPlayer}=await import('../src/settlement-player.mjs');
 const rest=bodyMesh('walk_study',0).points;
 contour.forEach((p,i)=>{assert.ok(Math.abs(rest[i][0]-380-p.x*.7)<.001);assert.ok(Math.abs(rest[i][1]-154+p.y*.7)<.001);});
 const body=await loadImage(fileURLToPath(new URL('../../../brand/refresh-2026-09/motion-rig/data/images/body.png',import.meta.url))),material=createMaterials([['body.png',body]],createCanvas);
 const canvas=createCanvas(760,400),ctx=canvas.getContext('2d'),player=await createStudyPlayer({...core,CanvasTexture,SkeletonRenderer},ctx,fileURLToPath(new URL('../../../brand/refresh-2026-09/masters/mark-alpha.png',import.meta.url)),{createCanvas,loadImage,bodyTexture:dark=>material('graphite',dark).get(body)});
 for(const dark of [false,true]){
  ctx.clearRect(0,0,760,400);player.draw('walk_study',0,760,400,{dark,language:'zh'});
  const actual=ctx.getImageData(380,154,1,1).data,original=material('graphite',dark).get(body).getContext('2d').getImageData(629,614,1,1).data;assert.ok(Math.abs(actual[0]-original[0])<4,'New lighting changed material');
  for(const kind of Object.keys(studyDuration))for(const t of [.85,2.3,studyDuration[kind]]){
   ctx.clearRect(0,0,760,400);player.draw(kind,t,760,400,{dark,language:'zh'});const zh=ctx.getImageData(0,0,760,400).data;
   ctx.clearRect(0,0,760,400);player.draw(kind,t,760,400,{dark,language:'en'});assert.deepEqual(ctx.getImageData(0,0,760,400).data,zh);
  }
  for(const [w,h] of [[760,400],[502,320]]){
   const render=(kind,t)=>{ctx.clearRect(0,0,760,400);player.draw(kind,t,w,h,{dark,language:'zh'});return ctx.getImageData(0,0,760,400).data;};
   const end=render('walk_study',4.6);
   assert.deepEqual(render('stamp_study',0),end,'Clip boundary changes visible pixels');
   for(const t of [4.6-1/30,4.6,4.6+1/30])assert.deepEqual(render('continuity_study',t),end,'Joined seam flashes or jumps');
   assert.deepEqual(render('continuity_study',9.4),render('stamp_study',4.8),'Reduced joined result differs');
  }
  assert.ok(!Object.keys(player.exportTextures()).some(k=>/text|ink/.test(k)));
 }
});


test('weight settles before erasing, holds the cleared row, unloads before feeding and has one small rebound',()=>{
 for(let i=0;i<3;i++){
  const at=beat=>rowTime(i,beat);
  const poised=walking(at(.42)),planted=walking(at(.60)),hold=walking(at(.84)),unload=walking(at(.98)),rebound=walking(at(1.04)),rest=walking(at(1.17));
  assert.equal(poised.steps[poised.active].erase,0);assert.ok(poised.plant>.6);
  assert.ok(planted.y>154+2);assert.equal(hold.steps[hold.active].erase,1);assert.equal(hold.plant,1);assert.equal(hold.steps[hold.active].feed,0);
  assert.equal(unload.plant,0);assert.equal(unload.steps[unload.active].feed,0);
  assert.ok(rebound.y<154&&rebound.y>152);assert.equal(rest.y,154);
  const shadow=t=>mesh(scene('walk_study',t),'body_shadow');
  assert.ok(shadow(at(.20)).alpha<shadow(at(.60)).alpha);
  assert.ok(shadow(at(.20)).points[2][1]-shadow(at(.20)).points[1][1]>shadow(at(.60)).points[2][1]-shadow(at(.60)).points[1][1]);
 }
});

test('stamp has distinct aim, raised, pressure and result holds; gaze follows the work within the eyes',()=>{
 for(const [a,b] of [[1.23,1.38],[1.8,1.98],[2.18,2.40],[2.74,3.08]])assert.deepEqual(stamping(a).stamp,stamping(b).stamp);
 const slow=stamping(2.02).stamp.y-stamping(2).stamp.y,fast=stamping(2.16).stamp.y-stamping(2.14).stamp.y;
 assert.ok(fast>slow*4,'Press lacks acceleration into contact');
 assert.ok(stamping(.69).gaze[0]>2);assert.ok(stamping(1.3).gaze[0]>2);assert.ok(stamping(2.25).gaze[1]>1);
 for(const kind of Object.keys(studyDuration))for(let t=0;t<=studyDuration[kind];t+=.03){const f=scene(kind,t);
  for(const i of [0,1]){const eye=mesh(f,'eye'+i).points,pupil=mesh(f,'pupil'+i).points;assert.ok(pupil[0][0]>=eye[0][0]&&pupil[1][0]<=eye[1][0]);assert.ok(pupil[0][1]>=eye[0][1]&&pupil[2][1]<=eye[2][1]);}
 }
});


test('one sheet, body, gaze and shadow survive the clip boundary and reverse seeking',()=>{
 const end=scene('walk_study',4.6),start=scene('stamp_study',0);
 assert.deepEqual(start.patches,end.patches,'Stamp resets the settled walk pose');
 for(const kind of Object.keys(studyDuration))for(let t=0;t<=studyDuration[kind];t+=.025){
  const f=scene(kind,t);assert.deepEqual(mesh(f,'paper'),mesh(end,'paper'),'Paper changes geometry or material');
  assert.equal(f.patches.filter(p=>['paper','card'].includes(p.material)).length,1);
 }
 for(const t of [4.6-1/30,4.6,4.6+1/30,6.78,9.4,4.6,4.6-1/30]){
  const f=scene('continuity_study',t),expected=t<4.6?scene('walk_study',t):scene('stamp_study',t-4.6);
  assert.deepEqual(f.patches,expected.patches);
 }
});

test('R fits the shared paper, the stamp covers it at contact and avoids the eyes while raised',()=>{
 const press=scene('stamp_study',contactTime),paper=mesh(press,'paper').points,logo=mesh(press,'logo').points;
 for(const [x,y] of logo)assert.ok(x>paper[0][0]&&x<paper[1][0]&&y>paper[0][1]&&y<paper[2][1]);
 const stamp=mesh(press,'stamp').points;
 for(const [x,y] of logo)assert.ok(x>=stamp[0][0]&&x<=stamp[1][0]&&y>=stamp[0][1]&&y<=stamp[2][1],'R escapes the pressing prop');
 for(let t=1.2;t<=3.1;t+=.02){const f=scene('stamp_study',t),s=mesh(f,'stamp').points;
  for(const i of [0,1])assert.ok(s[0][0]>mesh(f,'eye'+i).points[1][0],'Raised prop covers the face');
 }
});
