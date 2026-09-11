import {rowStart,rowTime,paragraphPeriod} from '../src/paragraph-rows.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createSettlementFlow,processingPose,flowTiming} from '../src/settlement-flow.mjs';
import {scene,contactTime,spineData,applyScene,project} from '../src/settlement-scene.mjs';
import * as core from '@esotericsoftware/spine-core';
const patch=(f,id)=>f.patches.find(p=>p.id===id);
const rows=f=>f.patches.filter(p=>p.material==='line');

test('A repeats for long processing without a completion mark or false progress',()=>{
 const flow=createSettlementFlow();assert.equal(flow.duration(),Infinity);
 for(let t=0;t<121;t+=.047){const f=flow.frame(t);
  assert.equal(f.meta.flowPhase,'A');assert.equal(patch(f,'logo').alpha,0);assert.equal(patch(f,'stamp').alpha,0);
  assert.ok(rows(f).filter(r=>r.alpha>0).length>=2);assert.ok(rows(f).filter(r=>r.alpha>0).length<=3);
  assert.deepEqual(patch(f,'paper'),patch(scene('walk_study',0),'paper'));
 }
 for(let n=0;n<30;n++){const a=processingPose(rowTime(n,.6)),b=processingPose(rowTime(n,.6)+paragraphPeriod);
  assert.ok(Math.abs(a.y-b.y)<1e-8);assert.ok(Math.abs(a.steps[0].erase-b.steps[0].erase)<1e-8);assert.deepEqual(a.lines.map(r=>r.width),b.lines.map(r=>r.width));
 }
});

test('success at lift, erase, hold or feed keeps the exact pose and finishes only existing rows',()=>{
 for(const time of [.1,.43,.87,1.13,1.29,1.37,4.7,9.98,120.37]){
  const flow=createSettlementFlow(),before=flow.frame(time);
  assert.ok(flow.signal('saved',time));assert.deepEqual(flow.frame(time).patches,before.patches,'Success restarts the pose');
  const e=flow.inspect();assert.equal(e.lastRow,processingPose(time).cycle+(processingPose(time).steps[0].feed>0?3:2));
  assert.equal(flow.frame(time).meta.flowPhase,'B');
  assert.ok(!flow.signal('saved',time+1));assert.ok(!flow.signal('failed',time+2));assert.deepEqual(flow.inspect(),e);
  for(let t=time;t<e.stampAt;t+=.017){const f=flow.frame(t);assert.equal(patch(f,'logo').alpha,0);assert.equal(patch(f,'stamp').alpha,0);
   const p=processingPose(t);rows(f).forEach((row,i)=>{if(p.cycle+i>e.lastRow)assert.equal(row.alpha,0,'B introduced another row');});
  }
  assert.equal(rows(flow.frame(e.clearAt)).filter(p=>p.alpha>0).length,0);
  assert.deepEqual(flow.frame(e.stampAt).patches,scene('stamp_study',0).patches);
  assert.equal(patch(flow.frame(e.stampAt+contactTime-.001),'logo').alpha,0);
  assert.equal(patch(flow.frame(e.stampAt+contactTime+.001),'logo').alpha,1);
  assert.deepEqual(flow.frame(flow.duration()).patches,scene('stamp_study',4.8).patches);
  assert.equal(flow.frame(flow.duration()).meta.flowPhase,'done');
  assert.equal(flow.frame(flow.duration()-1e-10).meta.flowPhase,'done','Floating endpoint retains stamp phase');
 }
});

test('failure and cancellation freeze the rows, settle the body and cannot become a success',()=>{
 for(const outcome of ['failed','cancelled'])for(const time of [.5,.91,1.31,6.04]){
  const flow=createSettlementFlow(),before=flow.frame(time);flow.signal(outcome,time);
  assert.deepEqual(flow.frame(time).patches,before.patches);
  for(const t of [time+.05,flow.duration(),time+10]){const f=flow.frame(t);
   assert.deepEqual(rows(f),rows(before));assert.equal(patch(f,'logo').alpha,0);assert.equal(patch(f,'stamp').alpha,0);
  }
  assert.deepEqual(patch(flow.frame(flow.duration()+.001),'body').points,patch(scene('walk_study',4.6),'body').points);
  assert.ok(!flow.signal('saved',time+1));
 }
});

test('reduced motion distinguishes processing, saved, failed and cancelled, and seeking preserves event order',()=>{
 const flow=createSettlementFlow();assert.deepEqual(flow.frame(18,true).patches,flow.frame(0,true).patches);
 flow.signal('saved',8.1);
 assert.equal(flow.frame(8.0).meta.flowPhase,'A');assert.equal(flow.frame(8.1).meta.flowPhase,'B');
 assert.deepEqual(flow.frame(8.1,true).patches,scene('stamp_study',4.8).patches);
 for(const t of [8.05,9,flow.duration(),8.05,9])assert.equal(flow.frame(t).meta.outcome,t<8.1?'processing':'saved');
 for(const outcome of ['failed','cancelled']){const f=createSettlementFlow();f.signal(outcome,2);assert.equal(patch(f.frame(2,true),'logo').alpha,0);assert.equal(f.frame(2,true).meta.flowPhase,outcome);}
 const next=createSettlementFlow();assert.equal(next.inspect(),null);assert.equal(next.frame(0).meta.flowPhase,'A');
});

test('A and B geometry reaches official Spine vertices without folds and alpha matches when seeking',()=>{
 const flow=createSettlementFlow();flow.signal('saved',5.31);
 const first=flow.frame(0),json=spineData(first),names=[...new Set(first.patches.map(p=>p.material))];
 const atlas=new core.TextureAtlas(names.map(n=>`${n}.png\nsize: 64,64\n${n}\nbounds: 0,0,64,64\n`).join('\n'));for(const page of atlas.pages)page.setTexture(new core.FakeTexture({width:64,height:64}));
 const skeleton=new core.Skeleton(new core.SkeletonJson(new core.AtlasAttachmentLoader(atlas)).readSkeletonData(json));
 const area=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
 for(const t of [...Array.from({length:Math.ceil(flow.duration()*30)},(_,i)=>i/30),5.32,5.30,1.45,0]){
  const f=flow.frame(t);applyScene(skeleton,f);
  for(const p of f.patches){const slot=skeleton.findSlot(p.id),att=slot.getAttachment(),v=new Float32Array(att.worldVerticesLength);att.computeWorldVertices(slot,0,v.length,v,0,2);
   assert.ok(v.every((x,i)=>Math.abs(x-p.points.flatMap(project)[i])<.001));assert.equal(slot.color.a,p.alpha);
  }
  const b=patch(f,'body'),base=patch(first,'body');for(let i=0;i<b.triangles.length;i+=3){const ids=b.triangles.slice(i,i+3);assert.ok(area(...ids.map(i=>b.points[i]))*area(...ids.map(i=>base.points[i]))>0);}
 }
});

test('rendered A wraps continuously; success adds no jump and both themes/languages share geometry',async()=>{
 const {createCanvas,loadImage}=await import('@napi-rs/canvas');
 const {CanvasTexture,SkeletonRenderer}=await import('@esotericsoftware/spine-canvas');
 const {createMaterials}=await import('../../../brand/refresh-2026-09/motion-rig/material.mjs');
 const {createStudyPlayer}=await import('../src/settlement-player.mjs');
 const body=await loadImage(fileURLToPath(new URL('../../../brand/refresh-2026-09/motion-rig/data/images/body.png',import.meta.url))),material=createMaterials([['body.png',body]],createCanvas);
 const canvas=createCanvas(760,400),ctx=canvas.getContext('2d'),player=await createStudyPlayer({...core,CanvasTexture,SkeletonRenderer},ctx,fileURLToPath(new URL('../../../brand/refresh-2026-09/masters/mark-alpha.png',import.meta.url)),{createCanvas,loadImage,bodyTexture:dark=>material('graphite',dark).get(body)});
 for(const dark of [false,true]){
  const render=(f,language='zh')=>{ctx.clearRect(0,0,760,400);player.draw('flow_study',f.time,760,400,{dark,language},f);return ctx.getImageData(0,0,760,400).data;};
  for(const time of [1,2,3,5,8,10].map(rowStart)){const flow=createSettlementFlow();assert.deepEqual(render(flow.frame(time-1e-6)),render(flow.frame(time+1e-6)),'A loop jumps');}
  for(const time of [.85,1.31]){const flow=createSettlementFlow(),before=render(flow.frame(time));flow.signal('saved',time);assert.deepEqual(render(flow.frame(time)),before);assert.deepEqual(render(flow.frame(time),'en'),before);}
 }
});
