import {createContact,advanceContact,contactMoving,applyContact,drawContact} from './wave-contact.mjs';
export {contactMoving};
// Shared by browser and offline evidence. One envelope drives body, wave and projection.
export const voiceModes=['listening','thinking','speaking','idle'];
export function createVoiceState(){return {contact:createContact(),time:0,recallTime:0,level:0,listen:0,speak:0,think:0};}
export function advanceVoice(s,dt,mode,volume,reduced=false){
  advanceContact(s.contact,dt,mode==='thinking',reduced);
  if(mode==='listening'||mode==='speaking')s.contact.enabled=false;
  dt=Math.max(0,Math.min(.05,dt));
  if(reduced){s.level=s.listen=s.speak=s.think=0;return s;}
  s.time+=dt;
  const active=mode==='listening'||mode==='speaking';
  const syllable=.28+.72*(.5+.5*Math.sin(s.time*5.8))*(.6+.4*Math.sin(s.time*11.3)**2);
  const target=active?Math.max(0,Math.min(1,volume))*syllable:0;
  const ease=(v,t,rate)=>Math.abs(v-t)<.0001?t:v+(t-v)*(1-Math.exp(-dt*rate));
  s.level=ease(s.level,target,target>s.level?22:10);
  s.listen=ease(s.listen,mode==='listening'?1:0,14);
  s.speak=ease(s.speak,mode==='speaking'?1:0,14);
  s.think=ease(s.think,mode==='thinking'?1:0,12);
  if(s.think>0)s.recallTime+=dt;else s.recallTime=0;
  return s;
}
export function applyVoice(runtime,rig,s,reduced=false){
  if(s.contact.enabled)return applyContact(runtime,rig,s.contact);
  const skeleton=rig.skeleton;skeleton.setToSetupPose();
  if(!reduced){
    const apply=(name,time,alpha)=>{if(alpha>0)rig.data.findAnimation(name).apply(skeleton,0,time,true,[],alpha,runtime.MixBlend.add,runtime.MixDirection.mixIn);};
    const expression=Math.min(1,s.level*3.2);
    apply('listening',s.time,s.listen*expression);apply('speaking',s.time,s.speak*expression);
    // Recall uses its authored ordering; hide it only once the transition has settled.
    if(s.think>0){rig.data.findAnimation('recall').apply(skeleton,0,s.recallTime,true,[],s.think,runtime.MixBlend.replace,runtime.MixDirection.mixIn);}
    const ground=skeleton.findBone('ground_shadow');
    ground.y-=16*s.level;
    ground.scaleX*=1-.14*s.level;ground.scaleY*=1-.2*s.level;
    skeleton.findSlot('ground_shadow').color.a*=1-.22*s.level;
  }
  skeleton.updateWorldTransform(runtime.Physics.none);return skeleton;
}
export function drawVoiceScene(ctx,renderer,rig,s,width,height,{dark=false,reduced=false,compact=false}={}){
  if(s.contact.enabled)return drawContact(ctx,renderer,rig,s.contact,width,height,{dark,compact});
  ctx.clearRect(0,0,width,height);
  const waveY=height*(compact?.76:.73),spacing=Math.min(compact?11:20,(width-64)/16);
  const amplitude=reduced?0:s.level*(compact?12:28);
  ctx.lineCap='round';
  for(let i=0;i<15;i++){
    const taper=Math.exp(-(((i-7)/6)**2)),pulse=reduced?0:(.35+.65*(.5+.5*Math.sin(s.time*7-i*.62)));
    const h=3+amplitude*taper*pulse;
    ctx.beginPath();ctx.moveTo(width/2+(i-7)*spacing,waveY-h);ctx.lineTo(width/2+(i-7)*spacing,waveY+h);
    ctx.strokeStyle=dark?'#85beaf':'#91bcb0';ctx.lineWidth=compact?3:5;ctx.stroke();
  }
  // Preserve the old dot's position above the waveform; keep travel within a few pixels.
  const scale=compact?.18:Math.min(.43,width/870),lift=(reduced?0:s.level)*(compact?3:7);
  const x=width/2+(reduced?0:Math.sin(s.time*1.5)*s.level*(compact?2:5));
  ctx.save();ctx.translate(x,waveY-(compact?44:88)-lift);ctx.scale(scale,-scale);
  renderer.draw(rig.skeleton);ctx.restore();
}
