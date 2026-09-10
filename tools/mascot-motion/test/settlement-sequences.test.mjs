import test from 'node:test';
import assert from 'node:assert/strict';
import * as core from '@esotericsoftware/spine-core';
import {compactStampKeys,compactStampTime,compactStampDuration,stampFrame,reviewFrame,reviewDuration} from '../src/settlement-sequences.mjs';
import {scene,bakeScene,project} from '../src/settlement-scene.mjs';
import {createSettlementFlow} from '../src/settlement-flow.mjs';
const patch=(f,id)=>f.patches.find(p=>p.id===id);

test('compact stamp shortens holds while preserving every moving interval and contact sequence',()=>{
 for(const [a,b] of [[.05,.6],[.6,1.1],[1.15,1.53],[1.58,1.76],[1.88,2.18],[2.24,2.74],[2.74,3.26]]){
  assert.ok(Math.abs((compactStampTime(b)-compactStampTime(a))-(b-a))<1e-8);
 }
 for(let t=0;t<=compactStampDuration;t+=.01){
  const f=stampFrame(t,true),original=scene('stamp_study',compactStampTime(t));assert.deepEqual(f.patches,original.patches);
  assert.equal(patch(f,'logo').alpha,t<1.76?0:1);
 }
 assert.deepEqual(stampFrame(compactStampDuration,true).patches,scene('stamp_study',4.8).patches);
 assert.equal(compactStampKeys.at(-1)[0],compactStampDuration);
});

test('full and compact flows keep identical A and B and only diverge after the paper is clear',()=>{
 for(const time of [.43,.87,1.31,5.31]){
  const full=createSettlementFlow(),short=createSettlementFlow({compact:true});full.signal('saved',time);short.signal('saved',time);
  const start=full.inspect().stampAt;assert.equal(start,short.inspect().stampAt);
  for(let t=0;t<start;t+=.031)assert.deepEqual(full.frame(t).patches,short.frame(t).patches);
  assert.equal(short.duration(),start+compactStampDuration);
  assert.equal(short.frame(short.duration()).meta.flowPhase,'done');
  assert.deepEqual(short.frame(short.duration(),true).patches,full.frame(full.duration(),true).patches);
 }
});

test('review aligns one paper, stamps only at contact, and returns to the same neutral result',()=>{
 assert.deepEqual(reviewFrame(.8).patches,scene('stamp_study',0).patches);
 assert.deepEqual(reviewFrame(5.6).patches,scene('stamp_study',4.8).patches);
 assert.deepEqual(reviewFrame(reviewDuration).patches,scene('stamp_study',4.8).patches);
 for(let t=0;t<=reviewDuration;t+=.013){const f=reviewFrame(t);assert.equal(patch(f,'logo').alpha,t<2.98?0:1);
  assert.equal(f.patches.filter(p=>p.material==='paper').length,1);
  for(let i=0;i<2;i++){const eye=patch(f,'eye'+i),pupil=patch(f,'pupil'+i);const ys=eye.points.map(p=>p[1]);
   for(const point of pupil.points)assert.ok(point[1]>=Math.min(...ys)&&point[1]<=Math.max(...ys),'Pupil outside narrowed eye');
  }
 }
});

test('new editable Spine exports reproduce actual vertices and opacity when seeking in either direction',()=>{
 for(const [kind,duration,sample] of [['compact_stamp',compactStampDuration,t=>stampFrame(t,true)],['review_study',reviewDuration,reviewFrame]]){
  const json=bakeScene(kind,duration,sample),first=sample(0),names=[...new Set(first.patches.map(p=>p.material))];
  const atlas=new core.TextureAtlas(names.map(n=>`${n}.png\nsize: 64,64\n${n}\nbounds: 0,0,64,64\n`).join('\n'));for(const page of atlas.pages)page.setTexture(new core.FakeTexture({width:64,height:64}));
  const skeleton=new core.Skeleton(new core.SkeletonJson(new core.AtlasAttachmentLoader(atlas)).readSkeletonData(json));
  for(const time of [0,1,2,3,duration,2,1,0]){
   skeleton.setToSetupPose();skeleton.data.findAnimation(kind).apply(skeleton,0,time,false,[],1,core.MixBlend.replace,core.MixDirection.mixIn);skeleton.updateWorldTransform(core.Physics.none);
   const f=sample(time);
   for(const p of f.patches){const slot=skeleton.findSlot(p.id),att=slot.getAttachment(),v=new Float32Array(att.worldVerticesLength);att.computeWorldVertices(slot,0,v.length,v,0,2);
    assert.ok(v.every((x,i)=>Math.abs(x-p.points.flatMap(project)[i])<.002));assert.ok(Math.abs(slot.color.a-p.alpha)<1e-6);
   }
  }
 }
});
