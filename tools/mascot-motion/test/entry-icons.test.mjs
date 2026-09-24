import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {TextureAtlas,AtlasAttachmentLoader,SkeletonJson,Skeleton,FakeTexture,Physics,MixBlend,MixDirection} from '@esotericsoftware/spine-core';
import {root} from '../src/paths.mjs';

const folder=resolve(root,'brand/refresh-2026-09/motion-rig/entry-icons');

test('both Today icon loops are real Spine timelines with clean rest and distinct frames',async()=>{
 const json=JSON.parse(await readFile(resolve(folder,'entry-icons.json'),'utf8'));
 const atlas=new TextureAtlas(await readFile(resolve(folder,'entry-icons.atlas'),'utf8'));
 for(const page of atlas.pages)page.setTexture(new FakeTexture({width:page.width,height:page.height}));
 const data=new SkeletonJson(new AtlasAttachmentLoader(atlas)).readSkeletonData(json);
 const skeleton=new Skeleton(data);
 const pose=(kind,time)=>{
  skeleton.setToSetupPose();
  data.findAnimation(kind).apply(skeleton,0,time,false,[],1,MixBlend.replace,MixDirection.mixIn);
  skeleton.updateWorldTransform(Physics.none);
  return Object.fromEntries(skeleton.slots.map(slot=>[slot.data.name,slot.color.a]));
 };
 for(const kind of ['learning','exam']){
  assert.ok(Math.abs(data.findAnimation(kind).duration-1.6)<1e-6);
  assert.deepEqual(pose(kind,0),pose(kind,1.6),`${kind} drifts at the loop seam`);
 }
 assert.ok(Object.values(pose('learning',0)).every(value=>value===0),'learning appears at rest');
 assert.ok(pose('learning',.24)['star-left']>.8);
 assert.ok(pose('learning',.24)['star-main']>.8);
 assert.ok(pose('learning',.58)['star-right']>.8);
 assert.ok(pose('learning',.92)['star-bottom']>.8);
 assert.ok(pose('exam',.48)['exam-tick']>.8);
 assert.ok(pose('exam',.48)['exam-line-top']>pose('exam',0)['exam-line-top']);
 assert.equal(pose('learning',.5)['exam-tick'],0);
 assert.equal(pose('exam',.5)['star-left'],0);
});
