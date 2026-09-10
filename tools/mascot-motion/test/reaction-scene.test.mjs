import test from 'node:test';
import assert from 'node:assert/strict';
import * as spine from '@esotericsoftware/spine-core';
import {reactionFrame,returnReaction,reactionKinds,reactionDuration,reactionViewport} from '../src/reaction-scene.mjs';
import {bakeScene,project} from '../src/settlement-scene.mjs';
const body=f=>f.patches.find(p=>p.id==='body');
const area=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
const inside=(p,poly)=>{let yes=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j];if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])yes=!yes;}return yes;};

test('reactions have distinct vertical, left-lean and right-lean silhouettes and common endpoints',()=>{
 const neutral=reactionFrame('reaction_rest',0);
 for(const k of reactionKinds){assert.deepEqual(reactionFrame(k,0).patches,neutral.patches);assert.deepEqual(reactionFrame(k,reactionDuration).patches,neutral.patches);}
 const frames=reactionKinds.map(k=>reactionFrame(k,.95));
 const heights=frames.map(f=>{const ys=body(f).points.map(p=>p[1]);return Math.max(...ys)-Math.min(...ys);});
 assert.ok(heights[0]>heights[1]*1.4&&heights[0]>heights[2]*1.4);
 assert.ok(frames[1].meta.lean<-45&&frames[2].meta.lean>65);
 // Nonuniform local curvature: three collinear neutral ring points must bend.
 for(const k of reactionKinds){const f=reactionFrame(k,k==='reaction_approve'?.38:1),p=body(f),n=(p.points.length-1)/4;
  assert.ok(p.points.some((_,i)=>i<n&&Math.abs(area(p.points[i],p.points[n+i],p.points[2*n+i]))>1),'Only an affine image transform');
 }
});

test('every reaction preserves mesh orientation, keeps face inside body and stays in fixed framing',()=>{
 const base=body(reactionFrame('reaction_rest',0));
 for(const kind of reactionKinds)for(let t=0;t<=reactionDuration;t+=1/120){const f=reactionFrame(kind,t),p=body(f),hull=p.points.slice(0,p.hull);
  for(let i=0;i<p.triangles.length;i+=3){const ids=p.triangles.slice(i,i+3);const a=area(...ids.map(i=>base.points[i])),b=area(...ids.map(i=>p.points[i]));assert.ok(a*b>0,`${kind} fold at ${t}`);}
  for(const point of p.points){assert.ok(point[0]>reactionViewport.x&&point[0]<reactionViewport.x+reactionViewport.width);assert.ok(point[1]>reactionViewport.y&&point[1]<reactionViewport.y+reactionViewport.height);}
  for(const face of f.patches.filter(p=>['eye','pupil'].includes(p.material)))for(const point of face.points)assert.ok(inside(point,hull),`${kind} face outside silhouette at ${t}`);
  for(const side of [0,1]){const eye=f.patches.find(p=>p.id==='eye'+side),pupil=f.patches.find(p=>p.id==='pupil'+side);for(const point of pupil.points)assert.ok(inside(point,eye.points),'Pupil outside eye');}
 }
});

test('next-question settling begins at the exact current pose and reduced motion uses distinct static poses',()=>{
 for(const kind of reactionKinds)for(const t of [.38,.95,1.5,2.3]){const f=reactionFrame(kind,t);assert.deepEqual(returnReaction(f,0).patches,f.patches);assert.deepEqual(returnReaction(f,.18).patches,reactionFrame('reaction_rest',0).patches);assert.deepEqual(returnReaction(f,0,true).patches,reactionFrame('reaction_rest',0).patches);}
 for(const k of reactionKinds)assert.deepEqual(reactionFrame(k,0,true).patches,reactionFrame(k,3.2,true).patches);
 assert.notDeepEqual(reactionFrame(reactionKinds[0],0,true).patches,reactionFrame(reactionKinds[1],0,true).patches);
});

test('all three editable Spine clips reproduce actual meshes on forward and backward seek',()=>{
 for(const k of reactionKinds){const json=bakeScene(k,reactionDuration,t=>reactionFrame(k,t));
  const names=[...new Set(reactionFrame(k,0).patches.map(p=>p.material))];
  const atlas=new spine.TextureAtlas(names.map(n=>`${n}.png\nsize: 64,64\n${n}\nbounds: 0,0,64,64\n`).join('\n'));for(const page of atlas.pages)page.setTexture(new spine.FakeTexture({width:64,height:64}));
  const skeleton=new spine.Skeleton(new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(json));
  for(const time of [0,.4,.9,1.4,3.2,1.4,.9,0]){skeleton.setToSetupPose();skeleton.data.findAnimation(k).apply(skeleton,0,time,false,[],1,spine.MixBlend.replace,spine.MixDirection.mixIn);skeleton.updateWorldTransform(spine.Physics.none);
   for(const p of reactionFrame(k,time).patches){const slot=skeleton.findSlot(p.id),att=slot.getAttachment(),v=new Float32Array(att.worldVerticesLength);att.computeWorldVertices(slot,0,v.length,v,0,2);const actual=p.points.flatMap(project);assert.ok(v.every((x,i)=>Math.abs(x-actual[i])<.002));}
  }
 }
});
