import {walking,poseFrame,studyDuration,clamp} from './settlement-scene.mjs';
import {stampFrame,compactStampDuration} from './settlement-sequences.mjs';

export const flowTiming={lead:.25,cycle:1.2,settle:.15,stop:.18};
const emptyPose=()=>({...walking(4.6),lines:[0,1,2,3].map(i=>({erase:1,y:234+i*34}))});
const cycleAt=time=>Math.max(0,Math.floor((time-flowTiming.lead)/flowTiming.cycle));
const localAt=time=>time<flowTiming.lead?time:flowTiming.lead+(time-flowTiming.lead)%flowTiming.cycle;

export function processingPose(time,lastRow=Infinity){
 const cycle=cycleAt(time),p=walking(localAt(time)),step=p.steps[0];
 return {...p,cycle,lines:[
  {erase:step.erase,y:234,alpha:cycle<=lastRow?1:0},
  {erase:0,y:268-34*step.feed,alpha:cycle+1<=lastRow?1:0},
  {erase:0,y:302-34*step.feed,alpha:cycle+2<=lastRow?1:0},
  {erase:0,y:336-34*step.feed,alpha:cycle+3<=lastRow?step.feed:0}
 ]};
}

export function createSettlementFlow({compact=false}={}){
 const stampDuration=compact?compactStampDuration:studyDuration.stamp_study;
 let event=null;
 function signal(outcome,time){
  if(event||!['saved','failed','cancelled'].includes(outcome))return false;
  time=Math.max(0,time);
  const p=processingPose(time),lastRow=p.cycle+(p.steps[0].feed>0?3:2);
  const clearAt=flowTiming.lead+(lastRow+1)*flowTiming.cycle;
  event={outcome,time,lastRow,clearAt,stampAt:clearAt+flowTiming.settle};
  return true;
 }
 function duration(){return !event?Infinity:event.outcome==='saved'?event.stampAt+stampDuration:event.time+flowTiming.stop;}
 function frame(time,reduced=false){
  time=Math.max(0,time);const accepted=event&&time>=event.time?event:null;
  let f,phase;
  if(!accepted){
   phase='A';f=poseFrame('flow_study',time,processingPose(reduced?0:time),true,'walk_study','A · 持续整理');
  }else if(accepted.outcome==='saved'){
   if(reduced||time>=event.stampAt){
    const t=reduced||time>=duration()-1e-9?stampDuration:Math.min(stampDuration,time-event.stampAt);
    phase=t>=stampDuration?'done':'stamp';f=stampFrame(t,compact);
   }else{
    phase='B';f=poseFrame('flow_study',time,time>=event.clearAt?emptyPose():processingPose(time,event.lastRow),true,'walk_study','B · 收好剩余内容');
   }
  }else{
   phase=accepted.outcome;
   // Freeze the row state immediately, ease only the body's load back to rest.
   const p=processingPose(event.time),rest=walking(4.6),q=reduced?1:clamp((time-event.time)/flowTiming.stop),mix=q*q*(3-2*q);
   for(const key of ['y','lift','plant','rebound'])p[key]+=(rest[key]-p[key])*mix;
   p.gaze=p.gaze.map((v,i)=>v+(rest.gaze[i]-v)*mix);
   f=poseFrame('flow_study',time,p,true,'walk_study',phase==='failed'?'整理失败 · 未保存':'已取消');
  }
  return {...f,kind:'flow_study',time,meta:{...f.meta,flowPhase:phase,outcome:accepted?.outcome??'processing',signalAt:event?.time??null}};
 }
 return {signal,duration,frame,inspect:()=>event?{...event}:null};
}
