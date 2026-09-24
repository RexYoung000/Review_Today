import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createCanvas,loadImage} from '@napi-rs/canvas';
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
  return {
   slots:Object.fromEntries(skeleton.slots.map(slot=>[slot.data.name,slot.color.a])),
   bones:Object.fromEntries(skeleton.bones.map(bone=>[bone.data.name,
    {x:bone.x,y:bone.y,rotation:bone.rotation,scaleX:bone.scaleX,scaleY:bone.scaleY}]))
  };
  };
 const stable=value=>JSON.parse(JSON.stringify(value,(_,entry)=>
  typeof entry==='number'?Math.round(entry*100000)/100000:entry));
 for(const kind of ['learning','exam']){
  assert.ok(Math.abs(data.findAnimation(kind).duration-1.6)<1e-6);
  assert.deepEqual(stable(pose(kind,0)),stable(pose(kind,1.6)),`${kind} drifts at the loop seam`);
 }
 assert.ok(Object.values(pose('learning',0).slots).every(value=>value===0),'learning appears at rest');
 assert.ok(pose('learning',.24).slots['star-left']>.8);
 assert.ok(pose('learning',.24).slots['star-main']>.8);
 assert.ok(pose('learning',.58).slots['star-right']>.8);
 assert.ok(pose('learning',.92).slots['star-bottom']>.8);
 assert.ok(['exam-badge','exam-line-top','exam-line-middle','exam-line-low','exam-line-bottom']
  .every(name=>pose('exam',0).slots[name]===1),'the exam icon must be complete in its first frame');
 assert.ok(pose('exam',.38).bones['exam-badge'].scaleX>1.04);
 assert.ok(pose('exam',.4).bones['exam-line-top'].x>pose('exam',0).bones['exam-line-top'].x+.5);
 assert.equal(pose('learning',.5).slots['exam-badge'],0);
 assert.equal(pose('exam',.5).slots['star-left'],0);
});

test('resting exam symbol and five animated layers have identical pixels',async()=>{
 const png=async file=>{
  const image=await loadImage(file),canvas=createCanvas(88,88),ctx=canvas.getContext('2d');
  ctx.drawImage(image,0,0);
  return ctx.getImageData(0,0,88,88).data;
 };
 const resting=await png(resolve(root,'Review_Today/Assets.xcassets/TodayExamIcon.imageset/exam.png'));
 const layers=await Promise.all(['exam-badge','exam-line-top','exam-line-middle','exam-line-low','exam-line-bottom']
  .map(name=>png(resolve(folder,name+'.png'))));
 let visible=0;
 for(let i=3;i<resting.length;i+=4){
  const total=layers.reduce((sum,layer)=>sum+layer[i],0);
  assert.equal(total,resting[i],`pixel ${Math.floor(i/4)} differs between resting and Spine art`);
  if(resting[i])visible++;
 }
 assert.ok(visible>300,'resting exam symbol is unexpectedly blank');
});
