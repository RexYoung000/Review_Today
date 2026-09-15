import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHeaderPlayer} from '../../../brand/refresh-2026-09/motion-rig/header-player.mjs';
import {loadRig,verticesOf} from '../src/runtime.mjs';
const json=JSON.parse(await readFile(new URL('../../../brand/refresh-2026-09/motion-rig/data/mascot.json',import.meta.url)));

test('header follows promptly, clamps extremes, and settles after leaving or typing',()=>{
 const p=createHeaderPlayer();p.pointer(-10,10);p.advance(1/60);
 assert.ok(p.inspect().x<-.25&&p.inspect().y>.25);
 for(let i=0;i<120;i++)p.advance(1/60);
 assert.equal(p.inspect().x,-1);assert.equal(p.inspect().y,1);assert.equal(p.moving(),false);
 p.quiet();for(let i=0;i<120;i++)p.advance(1/60);
 assert.equal(p.inspect().x,0);assert.equal(p.inspect().y,0);assert.equal(p.moving(),false);
 p.pointer(Infinity,NaN);p.advance(1/60);assert.equal(p.moving(),false);
});

test('rapid clicks never queue and interruption drops the reaction',()=>{
 const p=createHeaderPlayer();assert.equal(p.poke(),true);
 for(let i=0;i<35;i++){p.advance(1/60);assert.equal(p.poke(),false);}
 for(let i=0;i<30;i++)p.advance(1/60);
 assert.equal(p.moving(),false);assert.equal(p.poke(),true);
 p.reset();assert.equal(p.moving(),false);assert.equal(p.inspect().elapsed,1);
});

test('Spine header mesh stays valid and framed; pupils stay inside eye whites through clicks',async()=>{
 const rig=await loadRig(json),p=createHeaderPlayer(),s=rig.skeleton;
 for(const x of [-1,0,1])for(const y of [-1,0,1]){
  p.reset();p.pointer(x,y);p.poke();
  for(let i=0;i<100;i++){
   p.advance(1/120);s.setToSetupPose();p.apply(s);s.updateWorldTransform(0);
   for(const side of ['left','right']){
    const eye=s.findBone('pupil_'+side),dx=Math.max(0,Math.abs(eye.x)-8);
    assert.ok(dx*dx+eye.y*eye.y<=4.6**2,'pupil crosses eye white');
   }
   const v=Array.from(verticesOf(s)),a=s.findSlot('body').getAttachment();
   for(let j=0;j<a.triangles.length;j+=3){
    const [u,w,z]=a.triangles.slice(j,j+3).map(n=>n*2);
    assert.ok((v[w]-v[u])*(v[z+1]-v[u+1])-(v[w+1]-v[u+1])*(v[z]-v[u])>0,'mesh folds');
   }
   assert.ok(v.every(Number.isFinite));
   for(let j=0;j<v.length;j+=2){assert.ok(Math.abs(v[j])<150);assert.ok(Math.abs(v[j+1])<130);}
  }
 }
});
