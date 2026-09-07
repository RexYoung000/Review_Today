import {createContact,advanceContact,contactMoving,applyContact,drawContact} from './wave-contact.mjs';
export {contactMoving};
// Four modes use one body, one surface and one audio envelope. No microphone access.
export const voiceModes=['listening','thinking','speaking','idle'];
export function createVoiceState(){return {contact:createContact(),time:0,level:0,listen:0,speak:0,think:0};}
export function advanceVoice(s,dt,mode,volume,reduced=false){
  dt=Math.max(0,Math.min(.05,dt));
  s.time+=reduced?0:dt;
  const active=mode==='listening'||mode==='speaking';
  const syllable=.55+.45*(.5+.5*Math.sin(s.time*3.3));
  const target=active?Math.max(0,Math.min(1,volume))*syllable:0;
  const ease=(v,t,rate)=>Math.abs(v-t)<.0001?t:v+(t-v)*(1-Math.exp(-dt*rate));
  s.level=reduced?0:ease(s.level,target,target>s.level?22:10);
  s.listen=reduced?0:ease(s.listen,mode==='listening'?1:0,14);
  s.speak=reduced?0:ease(s.speak,mode==='speaking'?1:0,14);
  s.think=reduced?0:ease(s.think,mode==='thinking'?1:0,12);
  s.contact.audio={mode,level:s.level,listen:s.listen,speak:s.speak,time:s.time};
  advanceContact(s.contact,dt,mode==='thinking',reduced);return s;
}
export function applyVoice(runtime,rig,s){return applyContact(runtime,rig,s.contact);}
export function drawVoiceScene(ctx,renderer,rig,s,width,height,options={}){return drawContact(ctx,renderer,rig,s.contact,width,height,options);}
