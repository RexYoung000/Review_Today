import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import * as spine from '@esotericsoftware/spine-core';
import {loadRig,verticesOf} from '../src/runtime.mjs';
import {createContact,advanceContact,contactMoving,applyContact,contactGeometry} from '../../../brand/refresh-2026-09/motion-rig/wave-contact.mjs';
import {solveElastic} from '../../../brand/refresh-2026-09/motion-rig/elastic-body.mjs';
const json=JSON.parse(await readFile(new URL('../../../brand/refresh-2026-09/motion-rig/data/mascot.json',import.meta.url)));
const geometry=contactGeometry(spine,await loadRig(json));
// Independent signed-distance check against complete vertical capsules. Dense
// edge samples catch cap/side intrusion between mesh vertices, not just centers.
function verify(c,rig){
  const v=verticesOf(rig.skeleton),g=c.soft.geometry,world=Array.from(v,(x,i)=>i%2?(x-g.bottom)*.2+c.rootY:x*.2+c.x*20);
  let sum=0,maxPen=0;
  for(let i=0;i<g.hull;i++){
    const j=(i+1)%g.hull,ax=world[2*i],ay=world[2*i+1],bx=world[2*j],by=world[2*j+1];sum+=ax*by-bx*ay;
    const steps=Math.ceil(Math.hypot(bx-ax,by-ay)/.2);
    for(let n=0;n<=steps;n++){const t=n/steps,x=ax+(bx-ax)*t,y=ay+(by-ay)*t;
      for(let b=0;b<c.bars.length;b++){const cy=Math.max(0,Math.min(c.bars[b],y));maxPen=Math.max(maxPen,4-Math.hypot(x-(b-2)*20,y-cy));}}
  }
  assert.ok(maxPen<=.5,`capsule penetration ${maxPen}`);
  assert.ok(Math.abs(sum/2/g.area-1)<=.1,'body area must stay within 10%');
  for(let j=0;j<g.triangles.length;j+=3){const [a,b,d]=g.triangles.slice(j,j+3).map(n=>n*2);assert.ok((v[b]-v[a])*(v[d+1]-v[a+1])-(v[b+1]-v[a+1])*(v[d]-v[a])>0,'triangle inversion');}
  assert.deepEqual(verticesOf(rig.skeleton,'shadow_clip'),v.slice(0,g.hull*2));
}
test('moving body and complete capsule edges stay separate, retain area and deform locally',async()=>{
  const c=createContact(geometry),rig=await loadRig(json);let land=0,flight=0,localDent=0;
  for(let i=0;i<900;i++){
    advanceContact(c,1/120,true);applyContact(spine,rig,c);verify(c,rig);
    if(c.phase==='flight')flight++;if(c.phase==='land')land++;
    // A nonuniform change to neighboring lower contour slopes distinguishes a
    // round indentation from one affine squash or a horizontal clipping plane.
    const p=c.soft.points,r=geometry.rest;
    for(let n=26;n<45;n++){const a=n*2,b=(n+1)*2;localDent=Math.max(localDent,Math.abs((p[b+1]-p[a+1])/(p[b]-p[a])-(r[b+1]-r[a+1])/(r[b]-r[a])));}
    assert.ok(c.bars.every(h=>Number.isFinite(h)&&h>=4));
  }
  assert.ok(land>0&&flight>0&&localDent>.1);assert.ok(c.landings>=5);
});
test('uneven middle, side and multiple supports do not enter the body, including between vertices',async()=>{
  const rig=await loadRig(json);
  for(const x of [6.15,6.5,7,7.75])for(const heights of [[8,33,8],[31,7,29],[30,32,31],[8,8,40]]){
    const c=createContact(geometry);c.x=x;c.bars[8]=heights[0];c.bars[9]=heights[1];c.bars[10]=heights[2];c.rootY=8;c.impact=.8;
    for(let i=0;i<80;i++){solveElastic(c,1/120);applyContact(spine,rig,c);verify(c,rig);}
  }
});
test('stopping throughout a hop preserves position and velocity then reaches exact quiet rest',()=>{
  for(const stopTime of [.05,.25,.5,.75,.95,1.1,2.1]){
    const c=createContact(geometry);for(let t=0;t<stopTime;t+=1/120)advanceContact(c,1/120,true);
    const x=c.x,y=c.rootY,v=c.velocity;advanceContact(c,0,false);assert.equal(c.x,x);assert.equal(c.rootY,y);assert.equal(c.velocity,v);
    for(let i=0;i<600;i++){advanceContact(c,1/120,false);assert.equal(c.x,x);assert.ok(Number.isFinite(c.rootY));}
    assert.equal(c.height,0);assert.equal(contactMoving(c),false);assert.deepEqual(c.bars,Array(19).fill(10));assert.deepEqual(c.soft.points,geometry.rest);
    advanceContact(c,.01,true);assert.equal(c.running,true);advanceContact(c,.01,true,true);assert.equal(contactMoving(c),false);
  }
});
test('resuming thought before settling starts another physical hop',()=>{
  const c=createContact(geometry);for(let i=0;i<30;i++)advanceContact(c,1/120,true);
  for(let i=0;i<10;i++)advanceContact(c,1/120,false);
  let fliesAgain=false;for(let i=0;i<240;i++){advanceContact(c,1/120,true);if(c.phase==='flight'&&c.height>5)fliesAgain=true;}
  assert.ok(fliesAgain);
});

test('landing transfers downward motion to both the body and the struck bars',()=>{
  const c=createContact(geometry);let struck;
  for(let i=0;i<240&&!struck;i++){
    advanceContact(c,1/120,true);
    if(c.landings===1)struck={y:c.rootY,bars:c.soft.contacts.map(k=>k.bar)};
  }
  assert.ok(struck);assert.ok(c.velocity<0,'body follows the depressed support');
  assert.ok(struck.bars.some(i=>c.velocities[i]<0),'struck bars yield downwards');
  for(let i=0;i<6;i++)advanceContact(c,1/120,true);
  assert.ok(c.rootY<struck.y-1,'weight visibly settles with the surface');
});
