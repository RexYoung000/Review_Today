// Fixed-step spring surface + an interruptible jump. All quantities use a 20 px bar pitch.
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
const bell=(x,r)=>Math.exp(-(x*x)/(r*r));
export function createContact(){return {enabled:false,running:false,phase:'rest',elapsed:0,x:7,from:7,to:10.5,hop:0,height:0,velocity:0,squish:0,squishTarget:0,mound:0,impact:0,bars:Array(15).fill(10),velocities:Array(15).fill(0),accumulator:0};}
function land(c){c.height=0;c.velocity=0;c.elapsed=0;c.phase=c.running?'land':'settle';c.settleSquish=.3;c.impact=1;for(let i=0;i<15;i++)c.velocities[i]-=100*bell(i-c.x,1.1);}
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
    c.squishTarget=(c.phase==='land'?.3:(c.settleSquish??0))*Math.exp(-c.elapsed*12)*Math.cos(c.elapsed*22);
    if(c.phase==='land'&&c.elapsed>.28){c.phase='charge';c.elapsed=0;c.from=c.x;c.to=[10.5,7,3.5,7][c.hop%4];}
    if(c.phase==='settle'&&c.elapsed>.8){c.phase='rest';c.squish=c.squishTarget=0;}
  }else c.squishTarget=0;
  c.squish+=(c.squishTarget-c.squish)*(1-Math.exp(-dt*30));
  const targetMound=c.running?1:0;c.mound+=(targetMound-c.mound)*(1-Math.exp(-dt*9));if(Math.abs(c.mound-targetMound)<1e-5)c.mound=targetMound;
  const before=c.bars.slice();
  for(let i=0;i<15;i++){
    const pressure=Math.max(0,c.squish)*80*bell(i-c.x,1.1);
    const target=10+26*c.mound*bell(i-c.x,2.3)-pressure;
    const neighbors=(before[Math.max(0,i-1)]+before[Math.min(14,i+1)])/2-before[i];
    c.velocities[i]+=(150*(target-before[i])+65*neighbors-15*c.velocities[i])*dt;
    c.bars[i]=Math.max(4,before[i]+c.velocities[i]*dt);
    if(!c.running&&c.phase==='rest'&&Math.abs(c.bars[i]-10)<.002&&Math.abs(c.velocities[i])<.02){c.bars[i]=10;c.velocities[i]=0;}
  }
}
export function advanceContact(c,dt,thinking,reduced=false){
  if(reduced){Object.assign(c,createContact(),{enabled:c.enabled||thinking});return;}
  if(thinking&&!c.running){c.enabled=true;c.running=true;if(c.phase==='rest'){c.phase='charge';c.elapsed=0;c.from=c.x;c.to=[10.5,7,3.5,7][c.hop%4];}}
  if(!thinking&&c.running){c.running=false;if(c.height>0){c.phase='brake';c.elapsed=0;c.brakeHeight=c.height;c.brakeVelocity=c.velocity;c.brakeDuration=.32;}else{c.settleSquish=c.squish;c.phase='settle';c.elapsed=0;}}
  c.accumulator+=Math.max(0,Math.min(.05,dt));
  while(c.accumulator>=1/120){step(c,1/120);c.accumulator-=1/120;}
}
export function contactMoving(c){return c.running||c.phase!=='rest'||c.bars.some((h,i)=>h!==10||c.velocities[i]!==0);}
export function contactHeight(c,x=c.x){const left=Math.floor(clamp(x,0,14)),right=Math.min(14,left+1),f=x-left;return c.bars[left]*(1-f)+c.bars[right]*f;}
export function applyContact(runtime,rig,c){
  const s=rig.skeleton;s.setToSetupPose();
  s.findSlot('ground_shadow').color.a=0;
  const body=s.findBone('body');body.scaleX*=1+c.squish*.68;body.scaleY*=1-c.squish;
  const direction=c.to>=c.from?1:-1;
  s.findBone('crown').rotation=-direction*(c.height/48)*5;
  s.findBone('left').rotation=c.squish*12;s.findBone('right').rotation=-c.squish*12;
  s.findBone('face').y-=Math.max(0,c.squish)*9;
  for(const side of ['left','right']){
    const pupil=s.findBone('pupil_'+side);pupil.x=direction*(c.running?5:0);pupil.y=c.phase==='flight'?2:0;
    s.findBone('eye_'+side).scaleY=1-Math.max(0,c.squish)*1.5;
  }
  // Compress the lower silhouette locally, with the same offsets on weighted clipping.
  const a=s.findSlot('body').getAttachment(),deform=[];
  for(let n=0;n<a.vertices.length;n+=9){
    const controls=[[-76,-22],[0,65],[76,-22]];let x=0,y=0;
    for(let k=0;k<3;k++){const j=n+k*3,w=a.vertices[j+2];x+=(a.vertices[j]+controls[k][0])*w;y+=(a.vertices[j+1]+controls[k][1])*w;}
    const low=clamp((-y+20)/130),dx=x*.045*c.squish*low,dy=-8*c.squish*low;
    for(let k=0;k<3;k++)deform.push(dx,dy);
  }
  s.findSlot('body').deform=deform;s.findSlot('shadow_clip').deform=deform.slice(0,48*6);
  s.updateWorldTransform(runtime.Physics.none);return s;
}
export function bodyBounds(s){const slot=s.findSlot('body'),a=slot.getAttachment(),v=new Float32Array(a.worldVerticesLength);a.computeWorldVertices(slot,0,v.length,v,0,2);let bottom=Infinity;for(let i=1;i<v.length;i+=2)bottom=Math.min(bottom,v[i]);return {bottom};}
export function drawContact(ctx,renderer,rig,c,width,height,{dark=false,compact=false}={}){
  ctx.clearRect(0,0,width,height);const pitch=Math.min(compact?11:20,(width-56)/16),unit=pitch/20,base=height*(compact?.8:.77),left=width/2-7*pitch;
  ctx.lineCap='round';
  for(let i=0;i<15;i++){
    const near=bell(i-c.x,2.3)*(c.mound*.65+c.impact*.35),t=clamp(near);
    const start=dark?[71,95,86]:[187,207,196],end=dark?[145,210,186]:[49,123,102];
    ctx.strokeStyle=`rgb(${start.map((v,k)=>Math.round(v+(end[k]-v)*t)).join(',')})`;ctx.lineWidth=8*unit;ctx.beginPath();ctx.moveTo(left+i*pitch,base);ctx.lineTo(left+i*pitch,base-c.bars[i]*unit);ctx.stroke();
  }
  const x=left+c.x*pitch,surface=base-contactHeight(c)*unit-4*unit;
  const shadowWidth=(19+c.height*.15)*unit;
  ctx.save();ctx.translate(x,surface+2*unit);ctx.scale(shadowWidth,3*unit);const grad=ctx.createRadialGradient(0,0,0,0,0,1);grad.addColorStop(0,`rgba(2,20,13,${.33*(1-c.height/80)})`);grad.addColorStop(1,'rgba(2,20,13,0)');ctx.fillStyle=grad;ctx.fillRect(-1,-1,2,2);ctx.restore();
  const scale=pitch*2.4/240;
  ctx.save();ctx.translate(x,surface-c.height*unit+bodyBounds(rig.skeleton).bottom*scale);ctx.scale(scale,-scale);renderer.draw(rig.skeleton);ctx.restore();
}
