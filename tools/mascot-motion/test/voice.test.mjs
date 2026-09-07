import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {compile,defaults,validate} from '../src/rig.mjs';
import {loadRig,verifyRuntime,verticesOf,sample} from '../src/runtime.mjs';
import * as spine from '@esotericsoftware/spine-core';
import {createVoiceState,advanceVoice,applyVoice} from '../../../brand/refresh-2026-09/motion-rig/voice-scene.mjs';
const contour=JSON.parse(await readFile(new URL('../../../brand/refresh-2026-09/motion-rig/assets/contour.json',import.meta.url)));
const json=compile(contour,defaults).json;
test('voice loops deform locally beyond bone motion, close exactly and reject broken voice frames',async()=>{
  const r=await verifyRuntime(json);for(const mode of ['listening','speaking']){assert.ok(r.voices[mode].minTriangleArea>0);assert.equal(r.voices[mode].endpointError,0);
    const rig=await loadRig(json),s=sample(rig,.8,mode),v=verticesOf(s);s.findSlot('body').deform=[];const bonesOnly=verticesOf(s);assert.ok(Math.max(...v.map((x,i)=>Math.abs(x-bonesOnly[i])))>1);
  }
  const bad=structuredClone(json);bad.animations.speaking.attachments.default.body.body.deform[3].vertices[0]=NaN;assert.equal(validate(bad).ok,false);
});
test('voice reacts on next frame; silence, stop and reduced motion settle to stable geometry',async()=>{
  const rig=await loadRig(json),s=createVoiceState();advanceVoice(s,1/60,'speaking',1);assert.ok(s.level>0);
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
  const rig=await loadRig(json),s=createVoiceState();
  for(const mode of ['listening','thinking','speaking']){
    for(let i=0;i<120;i++){advanceVoice(s,1/60,mode,.9);applyVoice(spine,rig,s);
      for(const slot of ['ground_shadow','ball_ground_shadow','body_shadow'])assert.equal(rig.skeleton.findSlot(slot).color.a,0);
    }
  }
  const x=s.contact.x;advanceVoice(s,0,'idle',0);assert.equal(s.contact.x,x);assert.ok(s.contact.finish||['brake','settle'].includes(s.contact.phase));
  let finishMotion=0;for(let i=0;i<240;i++){advanceVoice(s,1/60,'idle',0);finishMotion=Math.max(finishMotion,Math.abs(s.contact.squish));}
  assert.ok(finishMotion>.02);assert.equal(contactMoving(s.contact),false);assert.equal(s.contact.look,0);assert.equal(s.contact.height,0);
});

test('listening contracts; thought landing flattens the lower silhouette; one reply impact emits each phrase',async()=>{
  const {createContact,advanceContact,applyContact,audioHeight,contactHeight}=await import('../../../brand/refresh-2026-09/motion-rig/wave-contact.mjs');
  const rig=await loadRig(json),base=createContact();applyContact(spine,rig,base);const rest=verticesOf(rig.skeleton);
  const width=v=>{const xs=Array.from(v).filter((_,i)=>i%2===0);return Math.max(...xs)-Math.min(...xs);};
  const lowIds=Array.from({length:48},(_,i)=>i).filter(i=>rest[i*2+1]<Math.min(...Array.from(rest).filter((_,i)=>i%2===1))+17);
  const lowRange=v=>{const ys=lowIds.map(i=>v[i*2+1]);return Math.max(...ys)-Math.min(...ys);};
  const listen=createVoiceState();let minimumWidth=Infinity,hasDent=false;
  for(let i=0;i<240;i++){advanceVoice(listen,1/120,'listening',1);applyVoice(spine,rig,listen);minimumWidth=Math.min(minimumWidth,width(verticesOf(rig.skeleton)));hasDent ||= rig.skeleton.findSlot('body').deform.some(x=>Math.abs(x)>.5);}
  assert.ok(minimumWidth<width(rest)*.9);assert.ok(hasDent);
  const thought=createContact();let pressedFrames=0,flatRange=Infinity,hasDentInSurface=false;
  for(let i=0;i<144;i++){advanceContact(thought,1/120,true);applyContact(spine,rig,thought);if(thought.pressure>.8){pressedFrames++;hasDentInSurface ||= contactHeight(thought)<(contactHeight(thought,thought.x-1.5)+contactHeight(thought,thought.x+1.5))/2;flatRange=Math.min(flatRange,lowRange(verticesOf(rig.skeleton)));}}
  assert.ok(pressedFrames>=8);assert.ok(hasDentInSurface);assert.ok(flatRange<lowRange(rest)*.45);
  const reply=createVoiceState();let impacts=0,lookBeforeImpact=false,maxHeight=0,age=99;
  for(let i=0;i<900;i++){
    advanceVoice(reply,1/120,'speaking',1);const c=reply.contact;applyVoice(spine,rig,reply);
    maxHeight=Math.max(maxHeight,c.height);if(c.height>2&&c.velocity<0&&c.lookY<-2)lookBeforeImpact=true;
    if(c.answerWaveAge<age)impacts++;age=c.answerWaveAge;
    if(impacts===0)assert.equal(audioHeight(c,8),0);
    const v=verticesOf(rig.skeleton),tris=rig.skeleton.findSlot('body').getAttachment().triangles;
    for(let j=0;j<tris.length;j+=3){const [a,b,d]=tris.slice(j,j+3).map(n=>n*2);assert.ok((v[b]-v[a])*(v[d+1]-v[a+1])-(v[b+1]-v[a+1])*(v[d]-v[a])>0);}
  }
  assert.equal(impacts,2);assert.ok(lookBeforeImpact);assert.ok(maxHeight>10&&maxHeight<=15.001);
});
