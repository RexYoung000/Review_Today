import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createIdlePlayer,idleDurations,idleNames} from '../../../brand/refresh-2026-09/motion-rig/idle-player.mjs';
import {loadRig,sample,verticesOf,verifyRuntime} from '../src/runtime.mjs';
const json=JSON.parse(await readFile(new URL('../../../brand/refresh-2026-09/motion-rig/data/mascot.json',import.meta.url)));
const seeded=()=>{let s=177;return ()=>{s=(s*1664525+1013904223)>>>0;return s/4294967296;};};
test('idle enters after one second, finishes clips, and draws only from three other choices',()=>{
 const player=createIdlePlayer(seeded());player.advance(.99);assert.equal(player.inspect().phase,'wait');player.advance(.01);
 let previous=null,counts=Object.fromEntries(idleNames.map(n=>[n,0]));
 for(let i=0;i<1000;i++){
  const {clip,phase}=player.inspect();assert.equal(phase,'play');assert.notEqual(clip,previous);counts[clip]++;
  player.advance(idleDurations[clip]-.01);assert.equal(player.inspect().clip,clip);player.advance(.01);
  const wait=player.inspect();assert.equal(wait.phase,'wait');assert.ok(wait.remaining>=1.5&&wait.remaining<=3);previous=clip;player.advance(wait.remaining);
 }
 for(const n of Object.values(counts))assert.ok(n>190&&n<310);
});
test('single clip ends; paused clock is unchanged; seeded timelines replay consistently',()=>{
 const single=createIdlePlayer(seeded(),'idle_book');single.advance(7);assert.equal(single.inspect().phase,'done');single.advance(99);assert.equal(single.inspect().phase,'done');
 const a=createIdlePlayer(seeded()),b=createIdlePlayer(seeded());for(let i=0;i<100;i++){a.advance(.1);b.advance(.1);}assert.deepEqual(a.inspect(),b.inspect());
 const paused=a.inspect();a.advance(0);assert.deepEqual(a.inspect(),paused);
});
test('all four Spine clips keep geometry valid, end in setup body pose and hide props',async()=>{
 const rig=await loadRig(json);rig.skeleton.setToSetupPose();rig.skeleton.updateWorldTransform(0);const setup=Array.from(verticesOf(rig.skeleton));
 for(const [name,duration] of Object.entries(idleDurations)){
  assert.ok((await verifyRuntime(json,name)).minTriangleArea>0);
  const end=Array.from(verticesOf(sample(rig,duration,name)));assert.deepEqual(end,setup);
  assert.equal(rig.skeleton.findSlot('idle_book').color.a,0);assert.equal(rig.skeleton.findSlot('idle_page').color.a,0);
 }
 sample(rig,.92,'idle_hop');assert.ok(rig.skeleton.findBone('body').y>9);assert.ok(rig.skeleton.findBone('ground_shadow').scaleX<.9);assert.ok(rig.skeleton.findSlot('ground_shadow').color.a<.5);
 sample(rig,2,'idle_book');assert.equal(rig.skeleton.findSlot('idle_book').color.a,1);assert.ok(rig.skeleton.findBone('pupil_left').y<0);
 sample(rig,3.4,'idle_book');assert.ok(rig.skeleton.findBone('idle_page').scaleX<0);
});

test('idle gaze keeps the whole pupil inside the rounded eye white',async()=>{
 const rig=await loadRig(json);
 for(const [name,duration] of Object.entries(idleDurations))for(let t=0;t<=duration;t+=1/60){
  sample(rig,t,name);
  for(const side of ['left','right']){const p=rig.skeleton.findBone('pupil_'+side),dx=Math.max(0,Math.abs(p.x)-8);assert.ok(dx*dx+p.y*p.y<=4.6*4.6,name+' pupil leaves eye white');}
 }
});
