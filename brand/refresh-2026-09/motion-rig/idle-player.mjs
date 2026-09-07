import {idleDurations,idleNames} from './idle-definition.mjs';
export {idleDurations,idleNames} from './idle-definition.mjs';
export function createIdlePlayer(random=Math.random,selected='random'){
 const sequence=selected==='sidebar_loop'?['idle_book','idle_look']:null;
 let sequenceIndex=0;
 let phase='wait',clip=null,previous=null,elapsed=0,wait=1;
 const choose=()=>{const choices=idleNames.filter(n=>n!==previous);return choices[Math.min(choices.length-1,Math.floor(random()*choices.length))];};
 return {
  advance(dt){
   let remaining=Math.max(0,dt);
   while(remaining>0&&phase!=='done'){
    const duration=phase==='wait'?wait:idleDurations[clip],step=Math.min(remaining,duration-elapsed);elapsed+=step;remaining-=step;
    if(elapsed+1e-8<duration)break;
    elapsed=0;
    if(phase==='wait'){clip=sequence?sequence[sequenceIndex++%sequence.length]:idleNames.includes(selected)?selected:choose();phase='play';}
    else {previous=clip;clip=null;phase=selected==='random'||sequence?'wait':'done';wait=sequence ? 0.8 : 1.5+random()*1.5;}
   }
  },
  inspect(){return {phase,clip,previous,elapsed,remaining:phase==='wait'?Math.max(0,wait-elapsed):phase==='play'?Math.max(0,idleDurations[clip]-elapsed):0};},
  apply(spine,rig){
   const s=rig.skeleton;s.setToSetupPose();
   if(phase==='play')rig.data.findAnimation(clip)?.apply(s,0,elapsed,false,[],1,spine.MixBlend.replace,spine.MixDirection.mixIn);
   else if(phase==='wait'){const b=s.findBone('body'),breath=Math.sin(Math.PI*elapsed/wait)**2;b.scaleY*=1+breath*.008;b.scaleX*=1-breath*.004;}
  }
 };
}
