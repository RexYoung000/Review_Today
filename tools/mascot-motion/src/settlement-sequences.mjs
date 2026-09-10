import {scene,poseFrame,stamping,clamp} from './settlement-scene.mjs';

// Retain the accepted prop's moving intervals; shorten only its holds.
export const compactStampKeys=[[0,0],[.05,.15],[.60,.70],[1.10,1.20],[1.15,1.40],[1.53,1.78],[1.58,2.0],[1.76,2.18],[1.88,2.42],[2.18,2.72],[2.24,3.10],[2.74,3.60],[3.26,4.12],[3.36,4.8]];
export const compactStampDuration=3.36;
export const reviewDuration=6.6;
export function compactStampTime(t){
 t=Math.max(0,Math.min(compactStampDuration,t));
 for(let i=1;i<compactStampKeys.length;i++){
  const [end,value]=compactStampKeys[i],[start,previous]=compactStampKeys[i-1];
  if(t<=end)return previous+(value-previous)*(t-start)/(end-start);
 }
 return 4.8;
}
export function stampFrame(t,compact=false){return scene('stamp_study',compact?compactStampTime(t):t);}
export function reviewFrame(time){
 const t=Math.max(0,Math.min(reviewDuration,time));
 if(t>=.8&&t<5.6)return {...scene('stamp_study',t-.8),kind:'review_study',time:t};
 const ending=t>=5.6,p=stamping(ending?4.8:0),q=ending?clamp(t-5.6):clamp(t/.8);
 const pulse=Math.sin(Math.PI*q),rest=[...p.gaze];
 p.bodyY+=(ending?-2.5:2)*pulse;
 p.gaze=ending?[rest[0]+pulse*.8,rest[1]-pulse]:[rest[0]+Math.sin(2*Math.PI*q)*2,rest[1]+pulse*1.8];
 const f=poseFrame('review_study',t,p,false,'stamp_study',ending?'收好，恢复严肃':'核对，轻轻推齐');
 if(!ending){const paper=f.patches.find(p=>p.id==='paper'),offset=6*(1-q)*(1-q);paper.points=paper.points.map(([x,y,z])=>[x+offset,y,z]);}
 if(ending)for(const eye of f.patches.filter(p=>p.material==='eye')){
  const center=eye.points.reduce((n,p)=>n+p[1],0)/eye.points.length;
  eye.points=eye.points.map(([x,y,z])=>[x,center+(y-center)*(1-.15*pulse),z]);
 }
 return f;
}
