// Additive authoring: original mesh, weights, bone indices and action tracks stay intact.
import {idleDurations} from '../../../brand/refresh-2026-09/motion-rig/idle-definition.mjs';
import {addBookRig,writeBookFrame,bookDrawOrder} from './book-rig.mjs';
export const idleClips=idleDurations;
const smooth=t=>{t=Math.max(0,Math.min(1,t));return t*t*(3-2*t);};
const ramp=(t,a,b)=>smooth((t-a)/(b-a));
const pulse=(t,a,b,c,d)=>ramp(t,a,b)*(1-ramp(t,c,d));
const round=n=>Math.round(n*1e5)/1e5;
const parabola=(t,a,b)=>{const u=(t-a)/(b-a);return u>0&&u<1?4*u*(1-u):0;};
function bodyBounds(json){
 const v=json.skins[0].attachments.body.body.vertices,ys=[];
 for(let i=0;i<v.length;){let n=v[i++],y=0;for(let j=0;j<n;j++){const bone=json.bones[v[i++]];i++;const localY=v[i++],weight=v[i++];y+=(bone.y+localY)*weight;}ys.push(y*json.bones[1].scaleY);}
 return {bottom:Math.min(...ys),height:Math.max(...ys)-Math.min(...ys)};
}
export function addIdleRig(json){
 const bounds=bodyBounds(json);addBookRig(json);
 for(const [name,duration] of Object.entries(idleClips)){
  const a={bones:{},slots:{}};
  const add=(bone,prop,time,data)=>((a.bones[bone]??={})[prop]??=[]).push({time:round(time),...Object.fromEntries(Object.entries(data).map(([k,v])=>[k,round(v)]))});
  const alpha=(slot,time,value)=>((a.slots[slot]??={}).alpha??=[]).push({time:round(time),value:round(value)});
  const frames=Math.round(duration*30);
  for(let i=0;i<=frames;i++){
   const t=duration*i/frames,end=i===0||i===frames;
   let gaze=0,lookY=0,tilt=0,lift=0,sy=1,sx=1,blink=0,crown=0,face=0,land=0;
   if(!end){
    if(name==='idle_look'){gaze=-15*pulse(t,.2,.7,1.3,1.65)+3*pulse(t,1.6,2.15,2.85,3.55);tilt=gaze*.2;blink=pulse(t,3.55,3.65,3.70,3.85);}
    if(name==='idle_hop'){
     const crouch=pulse(t,.1,.48,.5,.7),launch=pulse(t,.51,.66,.8,.98),flight=parabola(t,.7,1.52),rebound=parabola(t,1.8,2.2);
     land=pulse(t,1.5,1.65,1.72,1.9)+.35*pulse(t,2.18,2.28,2.32,2.55);
     lift=bounds.height*(.35*flight+.065*rebound);sy=1-.25*crouch+.16*launch-.27*land;sx=1/sy;
     crown=-4*pulse(t,.52,.65,.73,.9)+3*pulse(t,1.52,1.65,1.72,1.92);face=-2*launch+2*land;
     lookY=2*flight;gaze=-3*flight;blink=pulse(t,.24,.34,.39,.5)+pulse(t,1.5,1.56,1.64,1.78);
    }
    if(name==='idle_stretch'){
     const crouch=pulse(t,.08,.28,.32,.5),stretch=pulse(t,.42,1.12,1.62,2.32),release=pulse(t,2.28,2.46,2.52,2.76),rebound=pulse(t,2.63,2.8,2.87,3.13);
     sy=1-.1*crouch+.4*stretch-.14*release+.06*rebound;sx=1/sy;
     crown=-6*pulse(t,.48,.72,.86,1.12)+3*pulse(t,1.72,1.94,2.12,2.35);face=-3*pulse(t,.5,.75,.9,1.15);
     blink=pulse(t,.1,.22,.33,.53)+pulse(t,.9,1.02,1.5,1.7);land=release;
    }
    if(name==='idle_book'){
     const reach=pulse(t,.1,.6,1.15,1.8)+pulse(t,6.18,6.7,7.2,7.8),read=pulse(t,1.8,2.55,5.6,6.2);
     gaze=3*reach-5*read;lookY=-4*read;tilt=-7*reach-2*read;face=-2*read;
     blink=pulse(t,2.2,2.3,2.37,2.53)+pulse(t,4.6,4.72,4.78,4.94);
    }
   }
   // Hold the foot plane during stretch/squash; lift is independent flight height.
   const anchor=name==='idle_hop'||name==='idle_stretch'?bounds.bottom*(1-sy):0;
   add('body','translate',t,{x:0,y:anchor+lift});add('body','scale',t,{x:sx,y:sy});add('body','rotate',t,{value:tilt});
   if(name==='idle_hop'||name==='idle_stretch'){add('crown','translate',t,{x:0,y:crown});add('face','translate',t,{x:0,y:face});}
   if(name==='idle_book')add('face','translate',t,{x:0,y:face});
   for(const side of ['left','right']){add('pupil_'+side,'translate',t,{x:gaze,y:lookY});add('eye_'+side,'scale',t,{x:1,y:1-.94*blink});}
   const altitude=lift/bounds.height;
   add('ground_shadow','scale',t,{x:1-altitude*1.35+land*.13,y:1-altitude*.7+land*.06});alpha('ground_shadow',t,.7-altitude*1.25+land*.07);
   if(name==='idle_book')writeBookFrame(json,a,t,add,alpha);
  }
  if(name==='idle_book')a.drawOrder=bookDrawOrder(json);
  json.animations[name]=a;
 }
 return json;
}
