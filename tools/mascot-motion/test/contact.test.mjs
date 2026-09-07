import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import * as spine from '@esotericsoftware/spine-core';
import {loadRig,verticesOf} from '../src/runtime.mjs';
import {createContact,advanceContact,contactMoving,applyContact} from '../../../brand/refresh-2026-09/motion-rig/wave-contact.mjs';
const json=JSON.parse(await readFile(new URL('../../../brand/refresh-2026-09/motion-rig/data/mascot.json',import.meta.url)));
test('contact jump has local mesh deformation, a shared landing surface and positive triangles',async()=>{
  const c=createContact(),rig=await loadRig(json);let land=0,flight=0,press=0;
  for(let i=0;i<900;i++){
    advanceContact(c,1/120,true);applyContact(spine,rig,c);
    if(c.phase==='flight')flight++;if(c.phase==='land')land++;if(c.squish>.15)press++;
    assert.ok(c.bars.every(h=>Number.isFinite(h)&&h>=4));assert.ok(c.height>=0&&c.height<=48.001);
    const v=verticesOf(rig.skeleton),tris=rig.skeleton.findSlot('body').getAttachment().triangles;
    assert.equal(rig.skeleton.findSlot('body').deform.length,193*6);
    for(let j=0;j<tris.length;j+=3){const [a,b,d]=tris.slice(j,j+3).map(n=>n*2);assert.ok((v[b]-v[a])*(v[d+1]-v[a+1])-(v[b+1]-v[a+1])*(v[d]-v[a])>0);}
    const clip=verticesOf(rig.skeleton,'shadow_clip');assert.deepEqual(clip,v.slice(0,96));

  }
  assert.ok(land>0&&flight>0&&press>0);
});
test('stopping at every part of a hop keeps position continuous and all residual motion settles',()=>{
  for(const stopTime of [.05,.25,.5,.75,.95,1.1,2.1]){
    const c=createContact();for(let t=0;t<stopTime;t+=1/120)advanceContact(c,1/120,true);
    const x=c.x,h=c.height;advanceContact(c,0,false);assert.equal(c.x,x);assert.equal(c.height,h);
    for(let i=0;i<600;i++){advanceContact(c,1/120,false);assert.equal(c.x,x);assert.ok(Number.isFinite(c.height)&&c.height>=0);}
    assert.equal(c.height,0);assert.equal(c.squish,0);assert.equal(contactMoving(c),false);assert.deepEqual(c.bars,Array(19).fill(10));
    advanceContact(c,.01,true);assert.equal(c.running,true);advanceContact(c,.01,true,true);assert.equal(c.height,0);assert.equal(contactMoving(c),false);
  }
});


test('resuming thought before the stop settles cannot get stuck in the rest pose',()=>{
  const c=createContact();for(let i=0;i<30;i++)advanceContact(c,1/120,true);
  for(let i=0;i<10;i++)advanceContact(c,1/120,false);
  let fliesAgain=false;for(let i=0;i<240;i++){advanceContact(c,1/120,true);if(c.phase==='flight'&&c.height>5)fliesAgain=true;}
  assert.ok(fliesAgain);
});
