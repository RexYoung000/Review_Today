import {createContact,advanceContact,contactMoving,applyContact,drawContact} from './wave-contact.mjs';
export {contactMoving};
export {contactGeometry} from './wave-contact.mjs';
export const voiceModes=['listening','thinking','speaking','idle'];
export function createVoiceState(geometry){return {contact:createContact(geometry),time:0,level:0,listen:0,speak:0,think:0,accumulator:0};}
// The audio envelope and physics share a clock, independent of drawing at 30,
// 60 or 120 fps. No microphone access; volume is the preview's simulated input.
export function advanceVoice(s,dt,mode,volume,reduced=false){
  dt=Math.max(0,Math.min(.05,dt));
  if(reduced){s.level=s.listen=s.speak=s.think=s.accumulator=0;advanceContact(s.contact,0,false,true);return s;}
  s.contact.audio={mode,level:s.level,listen:s.listen,speak:s.speak,time:s.time};
  advanceContact(s.contact,0,mode==='thinking');
  s.accumulator+=dt;
  const tick=1/120,ease=(v,t,rate)=>Math.abs(v-t)<.0001?t:v+(t-v)*(1-Math.exp(-tick*rate));
  while(s.accumulator+1e-10>=tick){
    s.accumulator=Math.max(0,s.accumulator-tick);s.time+=tick;
    const active=mode==='listening'||mode==='speaking',syllable=.55+.45*(.5+.5*Math.sin(s.time*3.3));
    const target=active?Math.max(0,Math.min(1,volume))*syllable:0;
    s.level=ease(s.level,target,target>s.level?22:10);
    s.listen=ease(s.listen,mode==='listening'?1:0,14);s.speak=ease(s.speak,mode==='speaking'?1:0,14);s.think=ease(s.think,mode==='thinking'?1:0,12);
    s.contact.audio={mode,level:s.level,listen:s.listen,speak:s.speak,time:s.time};advanceContact(s.contact,tick,mode==='thinking');
  }
  return s;
}
export function applyVoice(runtime,rig,s){return applyContact(runtime,rig,s.contact);}
export function drawVoiceScene(ctx,renderer,rig,s,width,height,options={}){return drawContact(ctx,renderer,rig,s.contact,width,height,options);}
