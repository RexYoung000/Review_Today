import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createIdlePlayer,idleDurations,idleNames} from '../../../brand/refresh-2026-09/motion-rig/idle-player.mjs';
import {loadRig,sample,verticesOf,verifyRuntime} from '../src/runtime.mjs';
import {idleFraming} from '../../../brand/refresh-2026-09/motion-rig/idle-definition.mjs';
import {bookSlots} from '../src/book-rig.mjs';
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
 const single=createIdlePlayer(seeded(),'idle_book');single.advance(1+idleDurations.idle_book);assert.equal(single.inspect().phase,'done');single.advance(99);assert.equal(single.inspect().phase,'done');
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
 sample(rig,3,'idle_book');assert.equal(rig.skeleton.findSlot('idle_book').color.a,1);assert.ok(rig.skeleton.findBone('pupil_left').y<0);
 const pageBefore=Array.from(verticesOf(sample(rig,3.7,'idle_book'),'idle_page'));
 const pageAfter=Array.from(verticesOf(sample(rig,4.5,'idle_book'),'idle_page'));
 assert.ok(pageBefore[2]>pageBefore[0]&&pageAfter[2]<pageAfter[0], 'Page should cross its vertical hinge');
});

test('idle gaze keeps the whole pupil inside the rounded eye white',async()=>{
 const rig=await loadRig(json);
 for(const [name,duration] of Object.entries(idleDurations))for(let t=0;t<=duration;t+=1/60){
  sample(rig,t,name);
  for(const side of ['left','right']){const p=rig.skeleton.findBone('pupil_'+side),dx=Math.max(0,Math.abs(p.x)-8);assert.ok(dx*dx+p.y*p.y<=4.6*4.6,name+' pupil leaves eye white');}
 }
});

test('exaggerated stretch and jump have measurable anticipation, height and landing',async()=>{
 const rig=await loadRig(json),ys=s=>Array.from(verticesOf(s)).filter((_,i)=>i%2),baseline=ys(sample(rig,0,'idle_hop'));
 const min=Math.min(...baseline),height=Math.max(...baseline)-min;
 const stretch=ys(sample(rig,1.4,'idle_stretch'));
 assert.ok((Math.max(...stretch)-Math.min(...stretch))/height>1.39);
 assert.ok(Math.abs(Math.min(...stretch)-min)<1,'Stretch must stay anchored at its foot');
 const crouch=ys(sample(rig,.48,'idle_hop'));assert.ok((Math.max(...crouch)-Math.min(...crouch))/height<.77);
 const peak=ys(sample(rig,1.11,'idle_hop'));assert.ok((Math.min(...peak)-min)/height>.34);
 const landing=ys(sample(rig,1.67,'idle_hop'));assert.ok((Math.max(...landing)-Math.min(...landing))/height<.77);
 sample(rig,1.11,'idle_hop');assert.ok(rig.skeleton.findBone('ground_shadow').scaleX<.6);
 sample(rig,1.67,'idle_hop');assert.ok(rig.skeleton.findBone('ground_shadow').scaleX>1.1);
});

test('upright book is opaque, keeps R outward, and changes depth only clear of the body',async()=>{
 const rig=await loadRig(json);
 for(let t=0;t<=8;t+=1/60){
  const s=sample(rig,t,'idle_book');
  for(const name of bookSlots)assert.ok([0,1].includes(s.findSlot(name).color.a),'No alpha reveal');
  const v=verticesOf(s,'idle_book');
  assert.ok((v[2]-v[0])*(v[7]-v[1])-(v[3]-v[1])*(v[6]-v[0])>0,'R cover must not mirror');
 }
 for(const t of [1.1,6.9]){
  const s=sample(rig,t,'idle_book'),bodyMax=Math.max(...Array.from(verticesOf(s)).filter((_,i)=>i%2===0));
  const propMin=Math.min(...bookSlots.filter(n=>s.findSlot(n).color.a>0).flatMap(n=>Array.from(verticesOf(s,n)).filter((_,i)=>i%2===0)));
  assert.ok(propMin>bodyMax,'Depth change intersects body');
 }
 for(const t of [.1,7.8]){const s=sample(rig,t,'idle_book');assert.ok(s.drawOrder.indexOf(s.findSlot('idle_book'))<s.drawOrder.indexOf(s.findSlot('body')));}
 const s=sample(rig,3,'idle_book');assert.ok(s.drawOrder.indexOf(s.findSlot('idle_book'))>s.drawOrder.indexOf(s.findSlot('body')));
 const cover=verticesOf(s,'idle_book');assert.ok(Math.hypot(cover[6]-cover[0],cover[7]-cover[1])>Math.hypot(cover[2]-cover[0],cover[3]-cover[1]),'Cover must be portrait');
 for(const name of ['idle_book','idle_back']){
  const v=verticesOf(s,name);assert.ok(v[5]>v[7]+5&&v[3]>v[1]+5,'Outer cover edges must rise from the spine into a V');
 }
 for(const name of ['idle_paper_left','idle_paper_right']){const v=verticesOf(s,name);assert.ok(v[5]>v[7]+5,'Paper edges must follow the cover V');}
 for(const t of [3.7,4.5]){const v=verticesOf(sample(rig,t,'idle_book'),'idle_page');assert.ok(v[5]>v[7],'Turning page must settle toward the raised outer edge');}
});

test('all visible motion stays inside the App and preview canvases, below the eyes when reading',async()=>{
 const rig=await loadRig(json);
 for(const [clip,duration] of Object.entries(idleDurations))for(let t=0;t<=duration;t+=1/60){
  const s=sample(rig,t,clip);
  for(const [w,h] of [[150,170],[640,480]]){
   const frame=idleFraming(w,h);
   for(const slot of s.slots){
    const a=slot.getAttachment();if(!a||a.endSlot||slot.color.a===0)continue;
    const v=verticesOf(s,slot.data.name);
    for(let i=0;i<v.length;i+=2){const x=frame.x+v[i]*frame.scale,y=frame.y-v[i+1]*frame.scale;assert.ok(x>=1&&x<=w-1&&y>=1&&y<=h-1,`${clip} ${t.toFixed(2)} ${slot.data.name} clips at ${x},${y}`);}
   }
  }
  if(clip==='idle_book'&&t>2.55&&t<5.6){
   const top=Math.max(...bookSlots.filter(n=>s.findSlot(n).color.a>0).flatMap(n=>Array.from(verticesOf(s,n)).filter((_,i)=>i%2)));
   const eyes=Math.min(...['eye_left','eye_right'].flatMap(n=>Array.from(verticesOf(s,n)).filter((_,i)=>i%2)));
   assert.ok(top<eyes,'Book covers eyes');
  }
 }
});


test('sidebar cycles book and gaze only, with short rests and no terminal static state',()=>{
 const player=createIdlePlayer(()=>0.99,'sidebar_loop');
 player.advance(0.99);assert.equal(player.inspect().phase,'wait');player.advance(0.01);
 for(let cycle=0;cycle<20;cycle++)for(const name of ['idle_book','idle_look']){
  assert.equal(player.inspect().phase,'play');assert.equal(player.inspect().clip,name);
  player.advance(idleDurations[name]);assert.equal(player.inspect().phase,'wait');assert.equal(player.inspect().remaining,0.8);
  const paused=player.inspect();player.advance(0);assert.deepEqual(player.inspect(),paused);
  player.advance(0.8);
 }
 assert.equal(player.inspect().clip,'idle_book');
});
