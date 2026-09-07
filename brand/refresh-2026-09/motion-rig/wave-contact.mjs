import {BODY_SCALE,CAPSULE_RADIUS,contactGeometry,createElastic,solveElastic,resetElastic,supportHeight} from './elastic-body.mjs';
export {contactGeometry};
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
const bell=(x,r)=>Math.exp(-(x*x)/(r*r));
const ease=(x,target,rate,dt)=>Math.abs(target-x)<1e-5?target:x+(target-x)*(1-Math.exp(-rate*dt));
const GRAVITY=850;
export function createContact(geometry){
  const c={enabled:true,running:false,phase:'rest',elapsed:0,x:7,from:7,to:10.5,hop:0,height:0,rootY:14,velocity:0,squish:0,squishTarget:0,mound:0,impact:0,look:0,lookY:0,tilt:0,pressure:0,absorb:0,faceDrop:0,answerClock:-1,answerWaveAge:99,answerLevel:0,previousMode:'idle',bars:Array(19).fill(10),velocities:Array(19).fill(0),accumulator:0,quiet:0,grounded:true,airborne:false,replyPending:false,landings:0};
  if(geometry){c.soft=createElastic(geometry);resetElastic(c);}return c;
}
export function audioPulse(distance,time,direction){const phase=time/1.55+(direction==='in'?1:-1)*distance/9;return Math.max(0,Math.cos(phase*Math.PI*2))**6;}
export function audioHeight(c,x){
  const a=c.audio;if(!a)return 0;const distance=Math.abs(x-7),edge=1-.65*smooth((distance-6)/3);
  const emitted=c.answerWaveAge<1.65?bell(distance-c.answerWaveAge*7.5,.85)*c.answerLevel:0;
  const phraseRipple=c.answerClock>.85&&!c.replyPending?3*a.level*audioPulse(distance,a.time,'out'):0;
  return edge*(34*a.level*a.listen*audioPulse(distance,a.time,'in')+a.speak*(46*emitted+phraseRipple)*smooth((distance-1.1)/1.3));
}
function launch(c,height,kind){c.velocity=Math.sqrt(2*GRAVITY*height);c.grounded=false;c.airborne=true;c.phase='flight';c.elapsed=0;c.jumpKind=kind;c.launchY=c.rootY;if(kind==='thought'){c.from=c.x;c.to=[10.5,7,3.5,7][c.hop++%4];}}
function land(c,speed){
  c.jumpKind=null;c.landings++;c.impact=clamp(speed/220,.12,1);c.phase=c.running?'land':'settle';c.elapsed=0;c.airborne=false;
  if(c.replyPending){c.answerWaveAge=0;c.answerLevel=clamp((c.audio?.level??0)*1.5);c.replyPending=false;}
  for(const hit of c.soft.contacts)c.velocities[hit.bar]-=Math.min(90,speed*.32);
}
function step(c,dt){
  const a=c.audio,mode=a?.mode??(c.running?'thinking':'idle');
  c.elapsed+=dt;c.answerWaveAge+=dt;c.impact*=Math.exp(-dt*10);
  const active=c.running||(['listening','speaking'].includes(mode)&&(a?.level??0)>.0001);
  c.quiet=active?0:c.quiet+dt;
  if(c.sleeping&&!active)return;c.sleeping=false;
  if(c.phase==='rest'&&c.running){c.phase='charge';c.elapsed=0;}
  if(c.phase==='land'&&c.elapsed>.26){c.phase=c.running?'charge':'settle';c.elapsed=0;}
  if(c.phase==='charge'&&c.elapsed>=.19&&c.grounded)launch(c,48,'thought');
  if(mode==='speaking'&&(a?.level??0)>.0001){
    if(c.answerClock<0&&c.grounded){c.answerClock=0;c.replyLaunched=false;}
    if(c.answerClock>=0){c.answerClock+=dt;if(c.answerClock>=3.6&&!c.replyPending){c.answerClock=0;c.replyLaunched=false;}
      if(c.answerClock>=.12&&!c.replyLaunched&&c.grounded){c.replyLaunched=true;c.replyPending=true;launch(c,15,'reply');}}
  }
  if(c.phase==='flight'&&c.running&&c.jumpKind==='thought')c.x=c.from+(c.to-c.from)*smooth(c.elapsed/.68);
  else if(['listening','speaking'].includes(mode)&&c.grounded)c.x=ease(c.x,7,6,dt);
  c.mound=ease(c.mound,c.running?1:0,9,dt);
  c.absorb=ease(c.absorb,a?Math.min(1,a.level*1.9)*a.listen*audioPulse(0,a.time,'in'):0,22,dt);
  c.squishTarget=c.phase==='charge'?.1*smooth(c.elapsed/.19):c.impact*.16-(c.airborne?.04:0);
  c.squish=ease(c.squish,c.squishTarget,24,dt);
  c.look=ease(c.look,c.running?(c.to>=c.from?5:-5):a?Math.sin(a.time*1.4)*4*a.level*a.listen:0,12,dt);
  c.lookY=ease(c.lookY,c.replyPending&&c.velocity<80?-5:c.airborne?2:0,30,dt);
  c.faceDrop=ease(c.faceDrop,c.impact*6+c.absorb*2,14,dt);
  const before=c.bars.slice();
  for(let i=0;i<19;i++){
    const target=10+26*c.mound*bell(i-2-c.x,2.3)+audioHeight(c,i-2);
    const neighbors=(before[Math.max(0,i-1)]+before[Math.min(18,i+1)])/2-before[i];
    c.velocities[i]+=(150*(target-before[i])+65*neighbors-15*c.velocities[i])*dt;
    c.bars[i]=Math.max(4,before[i]+c.velocities[i]*dt);
  }
  if(!c.soft)return; // callers must bind rig geometry before starting playback
  const support=supportHeight(c),oldVelocity=c.velocity;
  c.velocity-=GRAVITY*dt;
  // A moving capsule transfers upward velocity; the listener leaves the surface
  // by inertia when its support slows, rather than following a scale keyframe.
  if(c.grounded&&!c.airborne&&c.soft.contacts.length){const supportSpeed=c.soft.contacts.reduce((sum,k)=>sum+c.velocities[k.bar],0)/c.soft.contacts.length;c.velocity=Math.max(c.velocity,clamp(supportSpeed*.85,-90,90));}
  if(mode==='listening'&&!c.replyPending&&c.jumpKind!=='thought'&&c.rootY-support>5)c.velocity-=2600*(c.rootY-support-5)*dt;
  c.rootY+=c.velocity*dt;
  const incoming=c.velocity;
  const result=solveElastic(c,dt);
  c.grounded=result.contacts.length>0;
  const gap=Math.max(0,c.rootY-supportHeight(c));c.height=gap;
  if(gap>.65)c.airborne=true;
  if(result.correction>0){
    const surfaceSpeed=result.contacts.length?result.contacts.reduce((sum,k)=>sum+c.velocities[k.bar],0)/result.contacts.length:0;
    const relative=Math.max(0,surfaceSpeed-incoming);
    if(c.airborne&&incoming<surfaceSpeed&&c.elapsed>.08&&(c.jumpKind||mode==='listening'&&c.elapsed>.35))land(c,relative);
    c.airborne=false;
    const sharedSpeed=result.contacts.length?result.contacts.reduce((sum,k)=>sum+c.velocities[k.bar],0)/result.contacts.length:0;
    c.velocity=clamp(sharedSpeed*.85,-90,90);
    // Equal contact response is applied to the actual simulated bars, not a
    // different set of heights in draw(). Wave springs restore them next step.
    for(const hit of result.contacts)c.velocities[hit.bar]-=Math.min(18,result.correction/dt*.07)*Math.exp(-c.quiet*4);
  }
  c.pressure=ease(c.pressure,c.grounded?clamp(Math.abs(oldVelocity)/200+c.impact):0,35,dt);
  if(c.phase==='settle'&&c.elapsed>(c.running?.12:.7)&&c.grounded){c.phase='rest';c.jumpKind=null;}
  // End at an exact equilibrium so a silent preview can stop its RAF entirely.
  if(c.quiet>1.8&&Math.abs(c.velocity)<2&&c.height<.5&&c.bars.every((h,i)=>Math.abs(h-10)<.15&&Math.abs(c.velocities[i])<1)){
    c.bars.fill(10);c.velocities.fill(0);c.squish=c.squishTarget=c.pressure=c.impact=c.absorb=c.faceDrop=c.look=c.lookY=c.tilt=0;c.mound=0;c.phase='rest';c.finish=false;c.grounded=true;c.airborne=false;c.jumpKind=null;c.sleeping=true;resetElastic(c);
  }
}
export function advanceContact(c,dt,thinking,reduced=false){
  if(reduced){const geometry=c.soft?.geometry;Object.assign(c,createContact(geometry),{audio:{mode:'idle',level:0,listen:0,speak:0,time:0}});return;}
  const mode=c.audio?.mode??(thinking?'thinking':'idle');
  if(mode!==c.previousMode){
    if(mode!=='speaking'){c.answerClock=-1;c.replyPending=false;}
    if(mode==='idle'){c.phase='settle';c.elapsed=0;c.finish=true;}
    else if(!thinking&&c.running){c.phase='settle';c.elapsed=0;}
    c.previousMode=mode;
  }
  if(mode==='speaking'&&c.audio.level<=.0001){c.answerClock=-1;c.replyPending=false;}
  c.running=thinking;
  c.accumulator+=Math.max(0,Math.min(.05,dt));while(c.accumulator>=1/120){step(c,1/120);c.accumulator-=1/120;}
}
export function contactMoving(c){return c.running||c.phase!=='rest'||c.height>.001||c.look!==0||c.lookY!==0||c.pressure!==0||c.absorb!==0||c.faceDrop!==0||c.bars.some((h,i)=>h!==10||c.velocities[i]!==0);}
export function surfaceBar(c,i){return c.bars[i];}
export function contactHeight(c){return c.soft?supportHeight(c):14;}
export function applyContact(runtime,rig,c){
  if(!c.soft){c.soft=createElastic(contactGeometry(runtime,rig));resetElastic(c);}
  const s=rig.skeleton;s.setToSetupPose();for(const name of ['ground_shadow','ball_ground_shadow','body_shadow'])s.findSlot(name).color.a=0;
  s.findBone('face').y-=c.faceDrop;
  for(const side of ['left','right']){const pupil=s.findBone('pupil_'+side);pupil.x=c.look+(side==='left'?2:-2)*c.absorb;pupil.y=c.lookY;s.findBone('eye_'+side).scaleY=1-.18*c.impact;}
  s.updateWorldTransform(runtime.Physics.none);
  const slot=s.findSlot('body'),a=slot.getAttachment(),v=new Float32Array(a.worldVerticesLength);a.computeWorldVertices(slot,0,v.length,v,0,2);
  const influences=['left','crown','right'].map(name=>s.findBone(name)),deform=[];
  for(let n=0;n<v.length;n+=2){const dx=c.soft.points[n]/BODY_SCALE-v[n],dy=c.soft.points[n+1]/BODY_SCALE+c.soft.geometry.bottom-v[n+1];
    for(const bone of influences){const det=bone.a*bone.d-bone.b*bone.c;deform.push((bone.d*dx-bone.b*dy)/det,(-bone.c*dx+bone.a*dy)/det);}}
  slot.deform=deform;s.findSlot('shadow_clip').deform=deform.slice(0,c.soft.geometry.hull*6);
  // Face follows the local material displacement, then applies its own gaze.
  const g=c.soft.geometry,face=s.findBone('face');let dx=0,dy=0,weight=0;
  for(let n=0;n<g.rest.length;n+=2){const w=Math.exp(-((g.rest[n]/12)**2+((g.rest[n+1]-g.span*.65)/10)**2));dx+=(c.soft.points[n]-g.rest[n])*w;dy+=(c.soft.points[n+1]-g.rest[n+1])*w;weight+=w;}
  face.x+=dx/weight/BODY_SCALE/.86;face.y+=dy/weight/BODY_SCALE/.86;
  s.updateWorldTransform(runtime.Physics.none);return s;
}
export function bodyBounds(s){const slot=s.findSlot('body'),a=slot.getAttachment(),v=new Float32Array(a.worldVerticesLength);a.computeWorldVertices(slot,0,v.length,v,0,2);let bottom=Infinity;for(let i=1;i<v.length;i+=2)bottom=Math.min(bottom,v[i]);return {bottom};}
export function surfaceLayout(width,compact=false){const wide=!compact&&width>=520,pitch=Math.min(compact?11:20,(width-56)/(wide?20:16));return {pitch,indices:Array.from({length:wide?19:15},(_,i)=>i+(wide?0:2))};}
export function drawContact(ctx,renderer,rig,c,width,height,{dark=false,compact=false,debug=false}={}){
  ctx.clearRect(0,0,width,height);const {pitch,indices}=surfaceLayout(width,compact),unit=pitch/20,base=height*(compact?.8:.77),left=width/2-7*pitch;
  ctx.lineCap='round';const radius=CAPSULE_RADIUS*unit;
  for(const i of indices){const barX=i-2,near=bell(barX-c.x,2.3)*(c.mound*.65+c.impact*.35)+audioHeight(c,barX)/34,t=clamp(near),start=dark?[71,95,86]:[187,207,196],end=dark?[145,210,186]:[49,123,102];
    ctx.strokeStyle=`rgb(${start.map((v,k)=>Math.round(v+(end[k]-v)*t)).join(',')})`;ctx.lineWidth=radius*2;ctx.beginPath();ctx.moveTo(left+barX*pitch,base);ctx.lineTo(left+barX*pitch,base-c.bars[i]*unit);ctx.stroke();}
  const scale=unit*BODY_SCALE;ctx.save();ctx.translate(left+c.x*pitch,base-c.rootY*unit+(c.soft?.geometry.bottom??0)*scale);ctx.scale(scale,-scale);renderer.draw(rig.skeleton);ctx.restore();
  if(debug&&c.soft){ctx.save();ctx.strokeStyle='#e87936';ctx.lineWidth=.8;for(const i of indices){ctx.beginPath();ctx.roundRect(left+(i-2)*pitch-radius,base-c.bars[i]*unit-radius,radius*2,c.bars[i]*unit+radius*2,radius);ctx.stroke();}
    ctx.beginPath();for(let i=0;i<c.soft.geometry.hull;i++){const x=left+(c.x*20+c.soft.points[2*i])*unit,y=base-(c.rootY+c.soft.points[2*i+1])*unit;i?ctx.lineTo(x,y):ctx.moveTo(x,y);}ctx.closePath();ctx.stroke();ctx.fillStyle='#dc3d70';for(const k of c.soft.contacts){ctx.beginPath();ctx.arc(left+(c.x*20+k.x)*unit,base-k.capY*unit,2.5,0,Math.PI*2);ctx.fill();}ctx.restore();}
}
