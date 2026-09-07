// Fixed-step spring surface + an interruptible jump. All quantities use a 20 px bar pitch.
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
const bell=(x,r)=>Math.exp(-(x*x)/(r*r));
export function createContact(){return {enabled:true,running:false,phase:'rest',elapsed:0,x:7,from:7,to:10.5,hop:0,height:0,velocity:0,squish:0,squishTarget:0,mound:0,impact:0,look:0,lookY:0,tilt:0,pressure:0,absorb:0,faceDrop:0,answerClock:-1,answerWaveAge:99,answerLevel:0,previousMode:'idle',bars:Array(19).fill(10),velocities:Array(19).fill(0),accumulator:0};}
function land(c){c.height=0;c.velocity=0;c.elapsed=0;c.phase=c.running?'land':'settle';c.settleSquish=.3;c.impact=1;for(let i=0;i<19;i++)c.velocities[i]-=100*bell(i-2-c.x,1.1);}
// Travel direction is explicit: incoming crests converge; outgoing crests radiate.
export function audioPulse(distance,time,direction){
  const phase=time/1.55+(direction==='in'?1:-1)*distance/9;
  return Math.max(0,Math.cos(phase*Math.PI*2))**6;
}
export function audioHeight(c,x){
  const a=c.audio;if(!a)return 0;const distance=Math.abs(x-7);
  const edge=1-.65*smooth((distance-6)/3);
  const front=c.answerWaveAge*7.5;
  const emitted=c.answerWaveAge<1.65?bell(distance-front,.85)*c.answerLevel:0;
  const phraseRipple=c.answerClock>.85?3*a.level*audioPulse(distance,a.time,'out'):0;
  return edge*(34*a.level*a.listen*audioPulse(distance,a.time,'in')+a.speak*(46*emitted+phraseRipple));
}
function stepAnswer(c,dt){
  const a=c.audio;
  c.answerWaveAge+=dt;
  if(a?.mode!=='speaking'||a.level<=.0001)return;
  if(c.answerClock<0){if(c.phase!=='rest'||c.height>0)return;c.answerClock=0;}
  const previous=c.answerClock;c.answerClock+=dt;
  if(c.answerClock>=3.6){c.answerClock=0;c.answerLevel=0;}
  const t=c.answerClock;
  if(t<.12){c.squishTarget=.12*smooth(t/.12);}
  else if(t<.32){const u=(t-.12)/.2;c.height=15*smooth(u);c.velocity=15*6*u*(1-u)/.2;c.squishTarget=-.08*Math.sin(Math.PI*u);}
  else if(t<.52){const u=(t-.32)/.2;c.height=15*(1-smooth(u));c.velocity=-15*6*u*(1-u)/.2;c.squishTarget=-.035;}
  else if(previous<.52){land(c);c.answerWaveAge=0;c.answerLevel=Math.min(1,a.level*1.5);}
  else if(c.phase==='rest')c.squishTarget=.028*a.level*Math.sin((t-.52)*5);
}
function step(c,dt){
  c.elapsed+=dt;c.impact*=Math.exp(-dt*11);
  if(c.phase==='charge'){
    c.squishTarget=.27*smooth(c.elapsed/.19);
    if(c.elapsed>=.19){c.phase='flight';c.elapsed=0;c.from=c.x;c.to=[10.5,7,3.5,7][c.hop++%4];}
  }else if(c.phase==='flight'){
    const u=clamp(c.elapsed/.68);c.x=c.from+(c.to-c.from)*smooth(u);c.height=4*48*u*(1-u);c.velocity=4*48*(1-2*u)/.68;c.squishTarget=-.13*Math.sin(Math.PI*u);
    if(u>=1)land(c);
  }else if(c.phase==='brake'){
    const u=clamp(c.elapsed/c.brakeDuration),u2=u*u,u3=u2*u;
    c.height=Math.max(0,(2*u3-3*u2+1)*c.brakeHeight+(u3-2*u2+u)*c.brakeVelocity*c.brakeDuration);
    c.squishTarget*=Math.exp(-dt*8);if(u>=1)land(c);
  }else if(c.phase==='land'||c.phase==='settle'){
    c.squishTarget=(c.phase==='land'?.3:(c.settleSquish??0))*Math.exp(-c.elapsed*12)*Math.cos(c.elapsed*22)+(c.finish?.075*Math.sin(Math.PI*Math.min(1,c.elapsed/.42)):0);
    if(c.phase==='land'&&c.elapsed>.28){c.phase='charge';c.elapsed=0;c.from=c.x;c.to=[10.5,7,3.5,7][c.hop%4];}
    if(c.phase==='settle'&&c.elapsed>.8){c.phase='rest';c.finish=false;c.squish=c.squishTarget=0;}
  }else {
    c.squishTarget=0;
  }
  stepAnswer(c,dt);
  const a=c.audio;
  if(a&&['listening','speaking'].includes(a.mode)&&c.height===0)c.x+=(7-c.x)*(1-Math.exp(-dt*6));
  const gaze=c.running?(c.to>=c.from?5:-5):a?Math.sin(a.time*1.4)*4*a.level*a.listen:0;
  c.look+=(gaze-c.look)*(1-Math.exp(-dt*12));if(Math.abs(c.look)<.0001&&gaze===0)c.look=0;
  const downward=c.answerClock>=.27&&c.answerClock<.95?-5:c.phase==='flight'?2:0;
  c.lookY+=(downward-c.lookY)*(1-Math.exp(-dt*30));if(downward===0&&Math.abs(c.lookY)<.0001)c.lookY=0;
  const tilt=a?Math.sin(a.time*2.1)*3*a.listen*a.level:0;c.tilt+=(tilt-c.tilt)*(1-Math.exp(-dt*10));if(Math.abs(c.tilt)<.0001&&tilt===0)c.tilt=0;
  c.squish+=(c.squishTarget-c.squish)*(1-Math.exp(-dt*30));if(c.squishTarget===0&&Math.abs(c.squish)<1e-6)c.squish=0;
  const blend=(v,t,rate)=>Math.abs(v-t)<1e-5?t:v+(t-v)*(1-Math.exp(-dt*rate));
  const load=(c.phase==='land'||c.phase==='settle')&&c.impact>.001?(c.elapsed<.12?1:Math.exp(-(c.elapsed-.12)*15)):c.phase==='charge'?.22*smooth(c.elapsed/.19):0;
  c.pressure=blend(c.pressure,load,65);
  c.absorb=blend(c.absorb,a?Math.min(1,a.level*1.9)*a.listen*audioPulse(0,a.time,'in'):0,24);
  c.faceDrop=blend(c.faceDrop,c.pressure*9+c.absorb*3,14);
  const targetMound=c.running?1:0;c.mound+=(targetMound-c.mound)*(1-Math.exp(-dt*9));if(Math.abs(c.mound-targetMound)<1e-5)c.mound=targetMound;
  const before=c.bars.slice();
  for(let i=0;i<19;i++){
    const barX=i-2;
    const pressure=(c.pressure*24+Math.max(0,c.squish)*24)*bell(barX-c.x,1.05);
    const shoulder=c.pressure*8*(bell(barX-c.x-1.8,.65)+bell(barX-c.x+1.8,.65));
    const target=10+26*c.mound*bell(barX-c.x,2.3)+audioHeight(c,barX)-pressure+shoulder;
    const neighbors=(before[Math.max(0,i-1)]+before[Math.min(18,i+1)])/2-before[i];
    c.velocities[i]+=(150*(target-before[i])+65*neighbors-15*c.velocities[i])*dt;
    c.bars[i]=Math.max(4,before[i]+c.velocities[i]*dt);
    if(!c.running&&c.phase==='rest'&&!(a?.level>0)&&Math.abs(c.bars[i]-10)<.002&&Math.abs(c.velocities[i])<.02){c.bars[i]=10;c.velocities[i]=0;}
  }
}
export function advanceContact(c,dt,thinking,reduced=false){
  if(reduced){Object.assign(c,createContact(),{enabled:true,audio:{mode:'idle',level:0,listen:0,speak:0,time:0}});return;}
  const mode=c.audio?.mode??(thinking?'thinking':'idle');
  if(c.answerClock>=0&&(mode!=='speaking'||c.audio.level<=.0001)){
    c.answerClock=-1;
    if(c.height>0){c.phase='brake';c.elapsed=0;c.brakeHeight=c.height;c.brakeVelocity=c.velocity;c.brakeDuration=.25;}
  }
  if(mode==='idle'&&['listening','speaking'].includes(c.previousMode)&&c.height===0&&c.phase!=='brake'){c.settleSquish=c.squish;c.impact=0;c.finish=true;c.phase='settle';c.elapsed=0;}
  c.previousMode=mode;
  if(thinking&&!c.running){c.enabled=true;c.running=true;if(c.phase==='rest'){c.phase='charge';c.elapsed=0;c.from=c.x;c.to=[10.5,7,3.5,7][c.hop%4];}}
  if(thinking&&c.phase==='rest'){c.phase='charge';c.elapsed=0;c.from=c.x;c.to=[10.5,7,3.5,7][c.hop%4];}
  if(!thinking&&c.running){c.running=false;if(c.height>0){c.phase='brake';c.elapsed=0;c.brakeHeight=c.height;c.brakeVelocity=c.velocity;c.brakeDuration=.32;}else{c.settleSquish=c.squish;c.phase='settle';c.elapsed=0;}}
  c.accumulator+=Math.max(0,Math.min(.05,dt));
  while(c.accumulator>=1/120){step(c,1/120);c.accumulator-=1/120;}
}
export function contactMoving(c){return c.running||c.phase!=='rest'||c.look!==0||c.lookY!==0||c.pressure!==0||c.absorb!==0||c.faceDrop!==0||c.tilt!==0||c.bars.some((h,i)=>h!==10||c.velocities[i]!==0);}
export function surfaceBar(c,i){const d=i-2-c.x;return Math.max(4,c.bars[i]-c.pressure*9*bell(d,1.05)+c.pressure*2*(bell(d-1.8,.65)+bell(d+1.8,.65)));}
export function contactHeight(c,x=c.x){const left=Math.floor(clamp(x,-2,16))+2,right=Math.min(18,left+1),f=clamp(x,-2,16)-(left-2);return surfaceBar(c,left)*(1-f)+surfaceBar(c,right)*f;}
export function applyContact(runtime,rig,c){
  const s=rig.skeleton;s.setToSetupPose();
  s.findSlot('ground_shadow').color.a=0;
  const body=s.findBone('body');body.scaleX*=(1+c.squish*.68)*(1-.14*c.absorb);body.scaleY*=(1-c.squish)*(1-.045*c.absorb);body.rotation+=c.tilt;
  const direction=c.to>=c.from?1:-1;
  s.findBone('crown').rotation=-direction*(c.height/48)*5;
  s.findBone('left').rotation=c.squish*12;s.findBone('right').rotation=-c.squish*12;
  s.findBone('face').y-=c.faceDrop;
  for(const side of ['left','right']){
    const pupil=s.findBone('pupil_'+side);pupil.x=c.look+(side==='left'?2:-2)*c.absorb;pupil.y=c.lookY;
    s.findBone('eye_'+side).scaleY=1-Math.max(0,c.squish)*1.5-.2*c.pressure;
  }
  // Shape the already posed mesh in world space: a flat lower contact patch,
  // a wider lower body under load, and a local crown dent while absorbing sound.
  s.updateWorldTransform(runtime.Physics.none);
  const slot=s.findSlot('body'),attachment=slot.getAttachment(),v=new Float32Array(attachment.worldVerticesLength);
  attachment.computeWorldVertices(slot,0,v.length,v,0,2);
  let bottom=Infinity,top=-Infinity;for(let i=1;i<v.length;i+=2){bottom=Math.min(bottom,v[i]);top=Math.max(top,v[i]);}
  const span=top-bottom,cut=span*.27,center=s.findBone('body').worldX;
  const influences=['left','crown','right'].map(name=>s.findBone(name)),deform=[];
  for(let n=0;n<v.length;n+=2){
    const x=v[n]-center,d=v[n+1]-bottom;
    const cap=d<cut?d:cut*(1-smooth((d-cut)/cut));
    const dy=-.82*c.pressure*cap-span*.07*c.absorb*bell(x,span*.35)*smooth((d/span-.55)/.45);
    const dx=x*.07*c.pressure*(1-smooth(d/(cut*2)));
    // Give every influence the same world displacement; inverse bone matrices
    // preserve normalized weighting and keep the clipping contour coincident.
    for(const bone of influences){const det=bone.a*bone.d-bone.b*bone.c;deform.push((bone.d*dx-bone.b*dy)/det,(-bone.c*dx+bone.a*dy)/det);}
  }
  s.findSlot('body').deform=deform;s.findSlot('shadow_clip').deform=deform.slice(0,48*6);
  s.updateWorldTransform(runtime.Physics.none);return s;
}
export function bodyBounds(s){const slot=s.findSlot('body'),a=slot.getAttachment(),v=new Float32Array(a.worldVerticesLength);a.computeWorldVertices(slot,0,v.length,v,0,2);let bottom=Infinity;for(let i=1;i<v.length;i+=2)bottom=Math.min(bottom,v[i]);return {bottom};}
export function surfaceLayout(width,compact=false){const wide=!compact&&width>=520,pitch=Math.min(compact?11:20,(width-56)/(wide?20:16));return {pitch,indices:Array.from({length:wide?19:15},(_,i)=>i+(wide?0:2))};}
export function drawContact(ctx,renderer,rig,c,width,height,{dark=false,compact=false}={}){
  ctx.clearRect(0,0,width,height);const {pitch,indices}=surfaceLayout(width,compact),unit=pitch/20,base=height*(compact?.8:.77),left=width/2-7*pitch;
  ctx.lineCap='round';
  for(const i of indices){
    const barX=i-2,near=bell(barX-c.x,2.3)*(c.mound*.65+c.impact*.35)+audioHeight(c,barX)/34,t=clamp(near);
    const start=dark?[71,95,86]:[187,207,196],end=dark?[145,210,186]:[49,123,102];
    ctx.strokeStyle=`rgb(${start.map((v,k)=>Math.round(v+(end[k]-v)*t)).join(',')})`;ctx.lineWidth=8*unit;ctx.beginPath();ctx.moveTo(left+barX*pitch,base);ctx.lineTo(left+barX*pitch,base-surfaceBar(c,i)*unit);ctx.stroke();
  }
  const x=left+c.x*pitch,surface=base-contactHeight(c)*unit-4*unit;
  const scale=pitch*2.4/240;
  ctx.save();ctx.translate(x,surface-c.height*unit+bodyBounds(rig.skeleton).bottom*scale);ctx.scale(scale,-scale);renderer.draw(rig.skeleton);ctx.restore();
}
