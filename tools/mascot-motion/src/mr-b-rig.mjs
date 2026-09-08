import {durations,ease,ingestion} from './mr-b-state.mjs';
import {writeBookFrame,bookDrawOrder,bookSlots} from './book-rig.mjs';
const pulse=(t,a,b,c,d)=>ease((t-a)/(b-a))*(1-ease((t-c)/(d-c)));
const rounded=n=>Math.round(n*1e5)/1e5;
// Add authored Spine timelines to a cloned accepted rig. Existing assets unchanged.
export function addMrBRig(original){
 const json=structuredClone(original);
 for(const [name,duration] of Object.entries(durations)){
  const a={bones:{},slots:{}};
  const add=(bone,prop,t,data)=>((a.bones[bone]??={})[prop]??=[]).push({time:rounded(t),...Object.fromEntries(Object.entries(data).map(([k,v])=>[k,rounded(v)]))});
  const alpha=(slot,t,value)=>((a.slots[slot]??={}).alpha??=[]).push({time:rounded(t),value});
  for(let i=0,n=Math.round(duration*30);i<=n;i++){
   const t=i/n*duration,u=t/duration,envelope=Math.sin(Math.PI*u)**2;
   let bodyX=0,tilt=0,sx=1,sy=1,gaze=0,gy=0,lift=0,blink=pulse(u,.12,.14,.16,.2),bookTime=null;
   if(name==='mr_receive'){
    const dip=pulse(u,.04,.16,.22,.37),stand=pulse(u,.3,.48,.61,.82);
    sy=1-.24*dip+.3*stand;sx=1/sy;tilt=-9*dip+5*stand;gaze=-7*stand;
   }
   if(name==='mr_ponder'){
    const lean=pulse(u,.08,.3,.58,.79),snap=pulse(u,.72,.8,.84,.96);
    tilt=-25*lean+8*snap;bodyX=-17*lean;gaze=-12*lean;gy=2*lean;
    sy=1+.16*lean-.12*snap;sx=1/sy;
   }
   if(name==='mr_weigh'){
    const left=pulse(u,.04,.2,.3,.44),right=pulse(u,.35,.54,.67,.84);
    tilt=23*left-23*right;bodyX=-23*left+23*right;
    gaze=-13*pulse(u,.02,.12,.26,.42)+3*pulse(u,.33,.44,.64,.84);
    sy=1-.17*(left+right);sx=1+.14*(left+right);
   }
   if(name==='mr_focus'){
    const squash=pulse(u,.08,.3,.43,.6),spring=pulse(u,.5,.64,.72,.85),rebound=pulse(u,.8,.87,.9,.98);
    sy=1-.45*squash+.42*spring-.12*rebound;sx=1+.6*squash-.29*spring+.1*rebound;
    gaze=-8*squash;blink=.68*squash-.18*spring;
   }
   if(name==='mr_peek'){
    const crouch=pulse(u,.05,.2,.45,.61),sneak=pulse(u,.18,.36,.43,.6),caught=pulse(u,.53,.63,.7,.85);
    sy=1-.33*crouch+.35*caught;sx=1+.26*crouch-.22*caught;
    bodyX=-27*sneak;tilt=12*sneak-4*caught;gaze=-13*sneak;blink=.2*crouch-.22*caught;
   }
   if(name==='mr_hide'){
    // Read, suddenly stash the notebook, pretend innocence, then hide its corner.
    bookTime=u<.16?u/.16*2.6:u<.3?2.6+(u-.16)/.14*.7:u<.45?3.3+(u-.3)/.15*3.88:u<.7?7.18:u<.88?7.18+(u-.7)/.18*.52:7.7+(u-.88)/.12*.3;
    const caught=pulse(u,.26,.33,.37,.47),cover=pulse(u,.42,.53,.78,.94),tuck=pulse(u,.7,.78,.82,.94);
    sy=1+.3*caught-.18*tuck;sx=1-.2*caught+.18*tuck;
    bodyX=27*cover;tilt=-14*tuck;gaze=-12*cover+3*tuck;blink=-.2*caught+.28*tuck;
   }
   if(name.startsWith('mr_ingest')){
    const p=ingestion(t,name.endsWith('short')),r=p.time;
    const roll=pulse(r,.5,.7,4,4.2);tilt=(Math.sin(r*8)*12+360*(Math.floor(Math.max(0,r-.55)/1.2)+p.progress))*roll;
    const inflate=pulse(r,4.1,4.4,4.75,5.5);sy=1-.2*roll+.22*inflate;sx=1/sy+.22*inflate;
    gaze=-6*inflate;blink+=.4*roll;
   }
   if(name==='mr_review'){
    const check=pulse(u,.05,.2,.3,.43),stamp=pulse(u,.42,.54,.57,.7),pride=pulse(u,.7,.78,.87,.99);
    gaze=-9*check+2*pride;gy=-2*check;tilt=-6*check-5*pride;sy=1-.23*stamp+.12*pride;sx=1/sy;
   }
   if(i===0||i===n){bodyX=tilt=0;sx=sy=1;gaze=gy=lift=blink=0;}
   add('body','translate',t,{x:bodyX,y:-84*(1-sy)+lift});add('body','scale',t,{x:sx,y:sy});add('body','rotate',t,{value:tilt});
   for(const side of ['left','right']){add('pupil_'+side,'translate',t,{x:gaze,y:gy});add('eye_'+side,'scale',t,{x:1,y:1-.88*blink});}
   if(bookTime!==null){
    // Re-time existing mesh frames into this authored clip (not a second prop).
    const oldAdd=(bone,prop,_,data)=>add(bone,prop,t,data),oldAlpha=(slot,_,v)=>alpha(slot,t,v);
    writeBookFrame(json,a,bookTime,oldAdd,oldAlpha);
    for(const slots of Object.values(a.attachments?.default??{}))for(const attachment of Object.values(slots))attachment.deform.at(-1).time=rounded(t);
   }
  }
  if(name==='mr_hide'){
   const remap=t=>t===0?0:t===1.1?1.1/2.6*.16*duration:t===6.9?(.3+(6.9-3.3)/3.88*.15)*duration:duration;
   a.drawOrder=bookDrawOrder(json).map(f=>({...f,time:rounded(remap(f.time))}));
   // Last frame neutral and props hidden even under floating-point re-timing.
   for(const slot of bookSlots)a.slots[slot].alpha.at(-1).value=0;
  }
  json.animations[name]=a;
 }
 return json;
}
