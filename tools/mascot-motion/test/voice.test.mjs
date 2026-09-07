import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {compile,defaults,validate} from '../src/rig.mjs';
import {loadRig,verifyRuntime,verticesOf,sample} from '../src/runtime.mjs';
import * as spine from '@esotericsoftware/spine-core';
import {createVoiceState,advanceVoice,applyVoice,contactGeometry} from '../../../brand/refresh-2026-09/motion-rig/voice-scene.mjs';
const contour=JSON.parse(await readFile(new URL('../../../brand/refresh-2026-09/motion-rig/assets/contour.json',import.meta.url)));
const json=compile(contour,defaults).json;
const geometry=contactGeometry(spine,await loadRig(json));
test('voice loops deform locally beyond bone motion, close exactly and reject broken voice frames',async()=>{
  const r=await verifyRuntime(json);for(const mode of ['listening','speaking']){assert.ok(r.voices[mode].minTriangleArea>0);assert.equal(r.voices[mode].endpointError,0);
    const rig=await loadRig(json),s=sample(rig,.8,mode),v=verticesOf(s);s.findSlot('body').deform=[];const bonesOnly=verticesOf(s);assert.ok(Math.max(...v.map((x,i)=>Math.abs(x-bonesOnly[i])))>1);
  }
  const bad=structuredClone(json);bad.animations.speaking.attachments.default.body.body.deform[3].vertices[0]=NaN;assert.equal(validate(bad).ok,false);
});
test('voice reacts on next frame; silence, stop and reduced motion settle to stable geometry',async()=>{
  const rig=await loadRig(json),s=createVoiceState(geometry);advanceVoice(s,1/60,'speaking',1);assert.ok(s.level>0);
  for(let i=0;i<90;i++)advanceVoice(s,1/60,'speaking',1);
  applyVoice(spine,rig,s);const active=verticesOf(rig.skeleton);
  for(let i=0;i<180;i++)advanceVoice(s,1/60,'speaking',0);assert.equal(s.level,0);
  applyVoice(spine,rig,s);const silent=verticesOf(rig.skeleton);assert.ok(active.some((v,i)=>Math.abs(v-silent[i])>.1));
  advanceVoice(s,.05,'speaking',0);applyVoice(spine,rig,s);assert.deepEqual(verticesOf(rig.skeleton),silent);
  for(let i=0;i<600;i++){const mode=['thinking','listening','speaking','idle'][Math.floor(i/19)%4];advanceVoice(s,1/60,mode,.8);applyVoice(spine,rig,s);const v=verticesOf(rig.skeleton),tri=rig.skeleton.findSlot('body').getAttachment().triangles;
    for(let j=0;j<tri.length;j+=3){const [a,b,c]=tri.slice(j,j+3).map(n=>n*2);assert.ok((v[b]-v[a])*(v[c+1]-v[a+1])-(v[b+1]-v[a+1])*(v[c]-v[a])>0);}
  }
  for(let i=0;i<180;i++)advanceVoice(s,1/60,'idle',1);applyVoice(spine,rig,s);assert.deepEqual(verticesOf(rig.skeleton),silent);assert.equal(rig.skeleton.findSlot('fragment').color.a,0);
  advanceVoice(s,.02,'speaking',1,true);applyVoice(spine,rig,s,true);assert.deepEqual(verticesOf(rig.skeleton),silent);
});

test('incoming and outgoing crests travel oppositely; voice keeps one shadow-free silhouette',async()=>{
  const {audioPulse,surfaceLayout,contactMoving}=await import('../../../brand/refresh-2026-09/motion-rig/wave-contact.mjs');
  const peak=(time,direction)=>Array.from({length:901},(_,i)=>({d:i/100,h:audioPulse(i/100,time,direction)})).reduce((a,b)=>a.h>b.h?a:b).d;
  assert.ok(peak(.6,'in')<peak(.4,'in'));assert.ok(peak(.6,'out')>peak(.4,'out'));
  assert.equal(surfaceLayout(890).indices.length,19);assert.equal(surfaceLayout(425).indices.length,15);assert.equal(surfaceLayout(240,true).indices.length,15);assert.equal(surfaceLayout(890).pitch,surfaceLayout(425).pitch);
  const rig=await loadRig(json),s=createVoiceState(geometry);
  for(const mode of ['listening','thinking','speaking']){
    for(let i=0;i<120;i++){advanceVoice(s,1/60,mode,.9);applyVoice(spine,rig,s);
      for(const slot of ['ground_shadow','ball_ground_shadow','body_shadow'])assert.equal(rig.skeleton.findSlot(slot).color.a,0);
    }
  }
  const x=s.contact.x;advanceVoice(s,0,'idle',0);assert.equal(s.contact.x,x);assert.ok(s.contact.finish||['brake','settle'].includes(s.contact.phase));
  for(let i=0;i<240;i++)advanceVoice(s,1/60,'idle',0);
  assert.equal(contactMoving(s.contact),false);assert.equal(s.contact.look,0);assert.equal(s.contact.height,0);
});

test('listening passively separates and relands; each reply emits once after actual contact',async()=>{
  const {audioHeight}=await import('../../../brand/refresh-2026-09/motion-rig/wave-contact.mjs');
  const rig=await loadRig(json),listen=createVoiceState(geometry);let gap=0,localChange=0;
  for(let i=0;i<960;i++){advanceVoice(listen,1/120,'listening',.85);gap=Math.max(gap,listen.contact.height);localChange=Math.max(localChange,...listen.contact.soft.points.map((v,i)=>Math.abs(v-geometry.rest[i])));}
  assert.ok(gap>=3&&gap<=6,`listener gap ${gap}`);assert.ok(listen.contact.landings>0);assert.ok(localChange>1);
  const reply=createVoiceState(geometry);let impacts=0,lookBeforeImpact=false,maxHeight=0,age=99;
  for(let i=0;i<900;i++){
    advanceVoice(reply,1/120,'speaking',1);const c=reply.contact;applyVoice(spine,rig,reply);
    maxHeight=Math.max(maxHeight,c.height);if(c.height>2&&c.velocity<0&&c.lookY<-2)lookBeforeImpact=true;
    if(c.answerWaveAge<age){impacts++;assert.ok(c.soft.contacts.length>0,'wave emission requires a collision');}age=c.answerWaveAge;
    if(impacts===0)assert.equal(audioHeight(c,10),0);
  }
  assert.equal(impacts,2);assert.ok(lookBeforeImpact);assert.ok(maxHeight>10&&maxHeight<=16);
});

test('30, 60 and 120 fps produce the same contact and audio state across transitions',()=>{
  const results=[];
  for(const fps of [30,60,120]){
    const s=createVoiceState(geometry);
    for(const [mode,volume] of [['listening',1],['listening',0],['thinking',1],['speaking',.85],['idle',0]]){
      for(let i=0;i<fps*2;i++)advanceVoice(s,1/fps,mode,volume);
      results.push({fps,mode,points:s.contact.soft.points.slice(),bars:s.contact.bars.slice(),y:s.contact.rootY});
    }
  }
  for(let i=5;i<results.length;i++){const a=results[i],b=results[i%5];assert.deepEqual(a.points,b.points);assert.deepEqual(a.bars,b.bars);assert.equal(a.y,b.y);}
});
