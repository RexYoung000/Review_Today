import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHeaderPlayer,headerReactions} from '../../../brand/refresh-2026-09/motion-rig/header-player.mjs';
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

test('all three reactions are selectable and accepted clicks never repeat the last reaction',()=>{
 for(const [i,name] of headerReactions.entries()){
  const p=createHeaderPlayer(()=> (i+.5)/3);p.poke();assert.equal(p.inspect().reaction,name);
 }
 const p=createHeaderPlayer(()=>.7),seen=new Set();let previous=null;
 for(let i=0;i<30;i++){
  p.poke();const selected=p.inspect().reaction;seen.add(selected);assert.notEqual(selected,previous);
  assert.equal(p.poke(),false);assert.equal(p.inspect().reaction,selected);
  p.reset();assert.equal(p.moving(),false);previous=selected;
 }
 assert.ok(seen.size>=2);
});

test('three Spine reactions produce distinct motion and return exactly to setup pose',async()=>{
 const {skeleton:s}=await loadRig(json),poses=[];
 for(let i=0;i<3;i++){
  const p=createHeaderPlayer(()=>(i+.5)/3);p.poke();
  for(let j=0;j<15;j++)p.advance(1/120);
  s.setToSetupPose();p.apply(s);const b=s.findBone('body');poses.push([b.x,b.y,b.rotation,b.scaleX,b.scaleY]);
  for(let j=0;j<120;j++)p.advance(1/120);
  s.setToSetupPose();const rest=[b.x,b.y,b.rotation,b.scaleX,b.scaleY];p.apply(s);
  assert.deepEqual([b.x,b.y,b.rotation,b.scaleX,b.scaleY],rest);assert.equal(p.moving(),false);
 }
 assert.equal(new Set(poses.map(JSON.stringify)).size,3);
});

test('Spine header mesh stays valid and framed; pupils stay inside eye whites through clicks',async()=>{
 const rig=await loadRig(json),s=rig.skeleton;
 for(let reaction=0;reaction<3;reaction++){
 for(const x of [-1,0,1])for(const y of [-1,0,1]){
  const p=createHeaderPlayer(()=>(reaction+.5)/3);p.pointer(x,y);p.poke();
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
 }
});
