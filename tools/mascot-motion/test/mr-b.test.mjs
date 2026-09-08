import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {addMrBRig} from '../src/mr-b-rig.mjs';
import {durations,createSequence,ingestion} from '../src/mr-b-state.mjs';
import {loadRig,sample,verticesOf} from '../src/runtime.mjs';
const original=JSON.parse(await readFile(new URL('../../../brand/refresh-2026-09/motion-rig/data/mascot.json',import.meta.url)));
const seed=()=>{let s=177;return()=>{s=(s*1664525+1013904223)>>>0;return s/4294967296;};};
test('new Spine timelines preserve accepted mesh and old animations; neutral endings hide the book',async()=>{
 const json=addMrBRig(original);assert.deepEqual(json.skins,original.skins);assert.deepEqual(json.bones,original.bones);
 for(const [name,animation] of Object.entries(original.animations))assert.deepEqual(json.animations[name],animation);
 const rig=await loadRig(json),baseline=Array.from(verticesOf(sample(rig,0,'mr_ponder')));
 for(const [name,duration] of Object.entries(durations)){
  assert.ok(Array.from(verticesOf(sample(rig,duration,name))).every((v,i)=>Math.abs(v-baseline[i])<0.0001),name+' returns to neutral (runtime float precision)');
  assert.equal(rig.skeleton.findSlot('idle_book').color.a,0,name+' stows props');
  for(let t=0;t<duration;t+=1/30){const skeleton=sample(rig,t,name);const v=verticesOf(skeleton);assert.ok(Array.from(v).every(Number.isFinite));
   for(const side of ['left','right']){const p=skeleton.findBone('pupil_'+side),dx=Math.max(0,Math.abs(p.x)-8);assert.ok(dx*dx+p.y*p.y<=4.6*4.6,name+' gaze stays in sclera');}
  }
 }
});
test('low-frequency new idle clips have two classic clips between them, and thinking never repeats',()=>{
 const idle=createSequence(seed());let gap=2,newCount=0,previous='';
 for(let i=0;i<400;i++){const {clip,wait}=idle.next('idle');assert.notEqual(clip,previous);assert.ok(wait>=1.5&&wait<=3);if(clip.startsWith('mr_')){assert.ok(gap>=2);gap=0;newCount++;}else gap++;previous=clip;}
 assert.ok(newCount>20&&newCount<100);
 const thinking=createSequence(seed());previous='';let orbit=0;
 for(let i=0;i<80;i++){const {clip}=thinking.next('thinking',true);assert.notEqual(clip,previous);if(clip==='recall')orbit++;previous=clip;}
 assert.equal(orbit,19);
 const simple=createSequence(seed());for(let i=0;i<100;i++)assert.notEqual(simple.next('thinking',false).clip,'recall');
});
test('row transfer is progressive and compact/full use identical semantic stages',()=>{
 let previous=[0,0,0];
 for(let t=0;t<=6;t+=.02){const p=ingestion(t);p.removed.forEach((n,i)=>{assert.ok(n>=previous[i]);previous[i]=n;});
  const q=ingestion(t/6*1.6,true);assert.ok(Math.abs(p.x-q.x)<1e-8);assert.ok(p.x>=90&&p.x<=430);assert.ok(p.y>=54&&p.y<=138);}
 assert.deepEqual(ingestion(0).removed,[0,0,0]);assert.deepEqual(ingestion(6).removed,[1,1,1]);assert.equal(ingestion(6).ink,0);assert.equal(ingestion(6).card,1);
});
test('rolling body stays inside the enlarged stage without camera shrink',async()=>{
 const rig=await loadRig(addMrBRig(original));
 for(let t=0;t<=6;t+=1/60){const p=ingestion(t),v=verticesOf(sample(rig,t,'mr_ingest'));
  for(let i=0;i<v.length;i+=2){const x=p.x+v[i]*.57,y=p.y+24-v[i+1]*.57;assert.ok(x>=1&&x<=519&&y>=1&&y<=267,`body clipped at ${t}: ${x},${y}`);}
 }
});
test('Rex exaggeration revision has distinct silhouettes while keeping all clips in fixed framing',async()=>{
 const rig=await loadRig(addMrBRig(original));
 let minScale=1,maxScale=1,minTilt=0,maxTilt=0;
 for(const name of ['mr_receive','mr_ponder','mr_weigh','mr_focus','mr_peek','mr_hide'])for(let t=0;t<=durations[name];t+=1/60){
  const s=sample(rig,t,name),body=s.findBone('body');
  if(name==='mr_focus'){minScale=Math.min(minScale,body.scaleY/.86);maxScale=Math.max(maxScale,body.scaleY/.86);}
  if(name==='mr_weigh'){minTilt=Math.min(minTilt,body.rotation);maxTilt=Math.max(maxTilt,body.rotation);}
  const frames=[[260,270,Math.min(260/410,270/460)]];
  if(['mr_receive','mr_ponder','mr_weigh','mr_focus'].includes(name))frames.push([104,96,Math.min(104/390,96/340)]);
  for(const [w,h,scale] of frames)for(const slot of s.slots){const a=slot.getAttachment();if(!a||a.endSlot||slot.color.a===0)continue;const v=verticesOf(s,slot.data.name);
   for(let i=0;i<v.length;i+=2){const x=w/2+v[i]*scale,y=h*.49-v[i+1]*scale;assert.ok(x>=.5&&x<=w-.5&&y>=.5&&y<=h-.5,`${name} clips at ${x},${y}`);}
  }
 }
 assert.ok(minScale<.56&&maxScale>1.4,'focus must visibly flatten and spring up');
 assert.ok(minTilt<-22&&maxTilt>22,'weigh must lean to both sides');
});
