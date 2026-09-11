import test from 'node:test';
import assert from 'node:assert/strict';
import {rowSpec,rowStart,rowTime,rowAt,rowLayout,paragraphPeriod} from '../src/paragraph-rows.mjs';
import {processingPose,createSettlementFlow} from '../src/settlement-flow.mjs';
import {scene,bodyMesh} from '../src/settlement-scene.mjs';
const lines=f=>f.patches.filter(p=>p.material==='line');
test('paragraph rows have stable widths, left alignment, short endings and extra paragraph spacing',()=>{
 const widths=new Set();
 for(let i=0;i<32;i++){
  const spec=rowSpec(i),p=processingPose(rowStart(i)),f=createSettlementFlow().frame(rowStart(i));widths.add(spec.width);
  assert.equal(p.cycle,i);assert.equal(p.lines[0].width,spec.width);assert.equal(lines(f)[0].points[0][0],rowLayout.x);
  assert.equal(p.lines[1].y-p.lines[0].y,spec.gap);
  if(spec.paragraphEnd){assert.ok(spec.width<rowSpec(i-1).width);assert.ok(spec.gap>rowLayout.gap);}
  assert.equal(rowAt(rowStart(i)+spec.duration/2),i);
  assert.equal(rowSpec(i+8).width,spec.width);
 }
 assert.ok(widths.size>=3);assert.ok(paragraphPeriod>0);
});
test('wiping time follows distance at the same speed and every erase frontier is under the planted body',()=>{
 const durations=new Set(),speeds=[];
 for(let i=0;i<8;i++){
  const spec=rowSpec(i);durations.add(spec.duration);speeds.push(spec.width/spec.stroke);
  for(let phase=.49;phase<.80;phase+=.01){
   const t=rowTime(i,phase),p=processingPose(t),body=bodyMesh('walk_study',0,p),edge=body.points.slice(0,body.hull),ys=[];
   assert.ok(p.steps[0].contact);assert.equal(p.lift,0);
   assert.ok(Math.abs(p.contactX-(rowLayout.x+spec.width*p.lines[0].erase))<1e-8);
   for(let n=0;n<edge.length;n++){const a=edge[n],b=edge[(n+1)%edge.length];if((a[0]<=p.contactX&&b[0]>=p.contactX)||(b[0]<=p.contactX&&a[0]>=p.contactX)){const q=(p.contactX-a[0])/(b[0]-a[0]);if(Number.isFinite(q))ys.push(a[1]+q*(b[1]-a[1]));}}
   assert.ok(Math.max(...ys)>=236.5,`Uncovered row ${i} at ${phase}`);
  }
  assert.equal(processingPose(rowTime(i,.44)).lines[0].erase,0);
  assert.equal(processingPose(rowTime(i,.81)).lines[0].erase,1);
 }
 assert.ok(durations.size>=3);assert.ok(Math.max(...speeds)-Math.min(...speeds)<1e-8);
});
test('paragraph break holds unloaded with no feeding; row identities survive feed and cycle boundaries',()=>{
 for(let i=0;i<16;i++){
  const spec=rowSpec(i);
  if(spec.paragraphEnd){const t=rowTime(i,.98)+spec.pause/2,p=processingPose(t);assert.equal(p.plant,0);assert.equal(p.lift,0);assert.equal(p.lines[0].erase,1);assert.equal(p.steps[0].feed,0);assert.equal(p.y,154);}
  const before=processingPose(rowTime(i,1.19)),after=processingPose(rowStart(i+1));
  assert.deepEqual(before.lines.slice(1).map(({index,width,y})=>({index,width,y})),after.lines.slice(0,3).map(({index,width,y})=>({index,width,y})));
  for(let t=rowStart(i);t<rowStart(i+1);t+=.02)for(const line of processingPose(t).lines)if(line.alpha>0)assert.ok(line.y+2.5<=345,'Row outside paper');
 }
});
test('completion at every short/long beat preserves current rows and drains them without restarting the paragraph',()=>{
 for(let i=0;i<16;i++)for(const beat of [.2,.6,.84,1.06,1.19]){
  const t=rowTime(i,beat),flow=createSettlementFlow(),before=flow.frame(t);flow.signal('saved',t);
  assert.deepEqual(flow.frame(t).patches,before.patches);
  const e=flow.inspect();assert.equal(e.clearAt,rowStart(e.lastRow+1));
  for(let at=t;at<e.clearAt;at+=.043){const f=flow.frame(at);for(const row of f.meta.lines)if(row.alpha>0){assert.ok(row.index<=e.lastRow);assert.equal(row.width,rowSpec(row.index).width);}}
  assert.deepEqual(flow.frame(e.stampAt).patches,scene('stamp_study',0).patches);
 }
});
