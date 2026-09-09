import {contour} from './settlement-character.mjs';
// Flat stage coordinates. The third coordinate is painter order, never depth:
// no perspective scaling, cylinder, or new body lighting model.
export const studyDuration={walk_study:4.6,stamp_study:4.8};
export const stage={width:760,height:400};
export const clamp=x=>Math.max(0,Math.min(1,x));
const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
const ramp=(t,a,b)=>ease((t-a)/(b-a));
const mix=(a,b,t)=>a+(b-a)*t;
export const project=([x,y])=>[x,y];
export const stepStarts=[.25,1.45,2.65];
export const contactTime=2.18;
const lineX=310,lineY=234,lineWidth=140,lineGap=34;

export function walking(t){
 const steps=stepStarts.map(start=>{
  const local=t-start,erase=ramp(local,.48,.80),feed=ramp(local,.98,1.16);
  return {local,erase,feed,contact:local>=.48&&local<=.80,
   lift:ramp(local,0,.20)*(1-ramp(local,.25,.43)),
   planted:ramp(local,.34,.48)*(1-ramp(local,.87,.98)),
   rebound:ramp(local,.98,1.04)*(1-ramp(local,1.04,1.16))};
 });
 const active=Math.min(2,Math.max(0,stepStarts.findLastIndex(start=>t>=start))),step=steps[active];
 const lift=steps.reduce((sum,s)=>sum+s.lift,0),plant=steps.reduce((sum,s)=>sum+s.planted,0),rebound=steps.reduce((sum,s)=>sum+s.rebound,0);
 return {x:380,y:154-5*lift+3*plant-1.4*rebound,steps,active,lift,plant,rebound,
  gaze:[2.2-4.4*ramp(step.local,.03,.28)+4.4*step.erase,.6+.7*plant],
  contactX:mix(lineX,lineX+lineWidth,step.erase),
  lines:steps.map((s,i)=>({erase:s.erase,y:lineY+i*lineGap-lineGap*steps.slice(0,i).reduce((n,s)=>n+s.feed,0)}))};
}

// One rigid prop follows the same behind -> clear of body -> front route as
// the daily book. Switching painter order only happens outside the silhouette.
export function stamping(t){
 const out=ramp(t,.15,.7),across=ramp(t,.7,1.2),lift=ramp(t,1.4,1.78);
 // Accelerate into contact, hold pressure, then lift slowly enough to read R.
 const down=clamp((t-2.0)/(contactTime-2.0))**2,up=ramp(t,2.42,2.72);
 const returnAcross=ramp(t,3.10,3.60),hide=ramp(t,3.60,4.12);
 const x=422+153*out-235*across+235*returnAcross-153*hide;
 const y=228-4*across-41*lift+92*down-58*up+11*returnAcross;
 const angle=-.12*out*(1-across)-.12*returnAcross*(1-hide);
 const puff=t>=contactTime?ramp(t,contactTime,contactTime+.06)*(1-ramp(t,contactTime+.08,contactTime+.40)):0;
 return {bodyX:422,bodyY:175,card:{x:340,y:272,w:196,h:94},
  gaze:[-1.4+4.6*out-6.2*across+6.2*returnAcross-4.6*hide,.8-1.4*lift+2.4*down-1.1*up-.7*returnAcross+.8*hide],
  stamp:{x,y,angle,layer:t<.7||t>=3.60?5:15,visible:t>=.15&&t<4.12},
  imprinted:t>=contactTime,puff,puffTravel:ramp(t,contactTime,contactTime+.40),
  phase:t<1.2?'从身后拿出印章':t<1.4?'对准，停稳':t<1.78?'认真抬起':t<2?'悬停，准备盖下':t<2.42?'按下，压实':t<2.72?'抬起印章':t<3.10?'看一眼，盖好了':t<4.12?'收回身后':'R 印记留在卡面'};
}

function quad(id,material,x,y,w,h,layer,{angle=0,alpha=1,uvs=[0,0,1,0,1,1,0,1],anchorY=.5}={}){
 const points=[[-w/2,-h*anchorY],[w/2,-h*anchorY],[w/2,h*(1-anchorY)],[-w/2,h*(1-anchorY)]].map(([xx,yy])=>[x+xx*Math.cos(angle)-yy*Math.sin(angle),y+xx*Math.sin(angle)+yy*Math.cos(angle),layer]);
 return {id,material,points,uvs,triangles:[0,1,2,2,3,0],hull:4,layer,alpha};
}
// Four rings use the unchanged daily contour and its UV mapping. Only the
// walking lower edge receives local lift/plant deformation; the face stays rigid.
export function bodyMesh(kind,t){
 const walk=kind==='walk_study',p=walk?walking(t):stamping(t),x=walk?p.x:p.bodyX,y=walk?p.y:p.bodyY;
 const points=[],uvs=[],triangles=[],n=contour.length;
 for(const ratio of [1,.75,.5,.25,0])for(let i=0;i<(ratio? n:1);i++){
  const source=ratio?contour[i]:{x:0,y:0},xx=source.x*.7*ratio,yy=-source.y*.7*ratio;
  const lower=ramp(yy,8,64),wave=walk?Math.exp(-(((x+xx-p.contactX)/34)**2)):0;
  // The planted lobe reaches the line; it retracts before the next line feeds.
  const delta=walk?lower*(-15*p.lift*(.55+.45*Math.cos(xx/23))+p.plant*wave*Math.max(0,242-y-yy)):0;
  const spread=walk?lower*p.plant*xx/100*2.6:0;
  points.push([x+xx+spread,y+yy+delta,10]);
  uvs.push((source.x*ratio/280*999+629)/1254,(614-source.y*ratio/280*999)/1254);
 }
 for(let r=0;r<3;r++)for(let i=0;i<n;i++){const next=(i+1)%n,a=r*n+i,b=r*n+next,c=(r+1)*n+i,d=(r+1)*n+next;triangles.push(a,b,c,b,d,c);}
 for(let i=0;i<n;i++)triangles.push(3*n+i,3*n+(i+1)%n,4*n);
 return {id:'body',material:'body',points,uvs,triangles,hull:n,layer:10,alpha:1};
}

export function scene(kind,time){
 const t=Math.max(0,Math.min(studyDuration[kind],time)),walk=kind==='walk_study',p=walk?walking(t):stamping(t),out=[];
 const x=walk?p.x:p.bodyX,y=walk?p.y:p.bodyY;
 if(walk){
  out.push(quad('paper','paper',380,248,294,194,1));
  p.lines.forEach((line,i)=>{const width=Math.max(.001,lineWidth*(1-line.erase)),cut=lineX+lineWidth*line.erase;
   out.push(quad('line'+i,'line',cut+width/2,line.y,width,5,3,{alpha:line.erase<1?1:0}));
  });
 }else{
  out.push(quad('card_shadow','shadow',p.card.x,p.card.y+43,204,20,0,{alpha:.45}));
  out.push(quad('card','card',p.card.x,p.card.y,p.card.w,p.card.h,2));
  out.push(quad('logo','logo',340,261,30,30,4,{alpha:p.imprinted?1:0}));
  out.push(quad('stamp','stamp',p.stamp.x,p.stamp.y,72,90,p.stamp.layer,{angle:p.stamp.angle,anchorY:1,alpha:p.stamp.visible?1:0}));
  for(const side of [-1,1])out.push(quad('puff'+side,'puff',340+side*(42+18*p.puffTravel),271-12*p.puffTravel,26,16,16,{alpha:p.puff*.65}));
 }
 out.push(quad('body_shadow','shadow',x,walk?234:254,walk?188+8*p.lift+6*p.plant:188,walk?17+4*p.lift-3*p.plant:17,4,{alpha:walk?.55-.19*p.lift+.22*p.plant:.65}));
 out.push(bodyMesh(kind,t));
 for(let i=0;i<2;i++){
  // Daily face position (-15,23), eyes +/-26, 36x20, pupil 10.8x10.8.
  const ex=x+(i?11:-41)*.7,ey=y-23*.7;
  out.push(quad('eye'+i,'eye',ex,ey,25.2,14,11));
  out.push(quad('pupil'+i,'pupil',ex+p.gaze[0],ey+p.gaze[1],7.56,7.56,12));
 }
 return {patches:out,time:t,kind,meta:{...p,body:[x,y],contact:walk?[p.contactX,lineY]:[340,275],
  phase:walk?(t<.25?'准备踏步':t<3.8?`第 ${p.active+1} 次踏步 · 逐行消除`:'横线已收好，站稳'):p.phase}};
}

export function spineData(frame){
 const slots=[],attachments={};
 for(const p of frame.patches){slots.push({name:p.id,bone:'root',attachment:p.id});attachments[p.id]={[p.id]:{type:'mesh',path:p.material,uvs:p.uvs,triangles:p.triangles,vertices:p.points.flatMap(project),hull:p.hull,width:64,height:64}};}
 return {skeleton:{spine:'4.2.00'},bones:[{name:'root'}],slots,skins:[{name:'default',attachments}],animations:{}};
}
export function applyScene(skeleton,frame){
 const layers=new Map(),slots=skeleton.studySlots??=new Map(skeleton.slots.map(s=>[s.data.name,s]));
 for(const p of frame.patches){const slot=slots.get(p.id);slot.color.a=p.alpha;slot.deform=p.points.flatMap(project);layers.set(p.id,p.layer);}
 skeleton.drawOrder=[...skeleton.slots].sort((a,b)=>layers.get(a.data.name)-layers.get(b.data.name));skeleton.updateWorldTransform(0);
}
export function bakeStudy(kind,fps=30){
 const first=scene(kind,0),json=spineData(first),animation={attachments:{default:{}},slots:{},drawOrder:[]};
 const baseIndex=new Map(json.slots.map((s,i)=>[s.name,i]));
 for(let i=0;i<=Math.ceil(studyDuration[kind]*fps);i++){
  const time=Math.min(i/fps,studyDuration[kind]),f=scene(kind,time);
  for(const p of f.patches){const att=json.skins[0].attachments[p.id][p.id];
   const slot=animation.slots[p.id]??={alpha:[]};slot.alpha.push({time,value:p.alpha,curve:'stepped'});
   const track=(animation.attachments.default[p.id]??={})[p.id]??={deform:[]};
   track.deform.push({time,vertices:p.points.flatMap(project).map((v,j)=>Math.round((v-att.vertices[j])*1000)/1000)});
  }
  const order=[...f.patches].sort((a,b)=>a.layer-b.layer);
  const offsets=order.map((p,target)=>({slot:p.id,offset:target-baseIndex.get(p.id)})).sort((a,b)=>baseIndex.get(a.slot)-baseIndex.get(b.slot));animation.drawOrder.push({time,offsets});
 }
 json.animations[kind]=animation;return json;
}
