// Deterministic authoring for one Review Today rig. No third-party animation code copied.
import { z } from 'zod';
export const recipeSchema = z.object({
  duration:z.number().min(4).max(9), strength:z.number().min(0).max(1.5),
  gaze:z.number().min(0).max(1), softness:z.number().min(35).max(140),
  bend:z.number().min(-18).max(18), wave:z.number().min(0).max(12),
  fps:z.number().int().min(12).max(30),
}).strict();
export const defaults={duration:5.6,strength:1,gaze:.85,softness:85,bend:10,wave:5,fps:24};
export const controls=[{name:'left',x:-76,y:-22},{name:'crown',x:0,y:65},{name:'right',x:76,y:-22}];
export const smooth=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x);};
const ramp=(t,a,b)=>smooth((t-a)/(b-a));
const pulse=(t,a,b,c,d)=>ramp(t,a,b)*(1-ramp(t,c,d));
const round=x=>Math.round(x*100000)/100000;
export function weightsAt(x,y,softness){
  const values=controls.map(c=>Math.exp(-((x-c.x)**2+(y-c.y)**2)/(2*softness**2)));
  const total=values.reduce((a,b)=>a+b,0);return values.map(v=>v/total);
}
export function createMesh(contour,softness){
  // Outer ring comes first, as expected by Spine's nonessential hull data.
  const points=[],uvs=[],triangles=[],vertices=[],weights=[];const n=contour.length,rings=4;
  for(let r=0;r<rings;r++)for(const p of contour){const ratio=1-r/rings;points.push({x:p.x*ratio,y:p.y*ratio});}
  const center=points.push({x:0,y:0})-1;
  for(let r=0;r<rings-1;r++)for(let i=0;i<n;i++){
    const a=r*n+i,b=r*n+(i+1)%n,c=(r+1)*n+i,d=(r+1)*n+(i+1)%n;
    triangles.push(a,b,c,b,d,c);
  }
  for(let i=0;i<n;i++)triangles.push((rings-1)*n+i,(rings-1)*n+(i+1)%n,center);
  for(const p of points){
    uvs.push((p.x/280*999+629)/1254,(614-p.y/280*999)/1254);
    const ws=weightsAt(p.x,p.y,softness);weights.push(ws);vertices.push(3);
    controls.forEach((c,i)=>vertices.push(i+2,round(p.x-c.x),round(p.y-c.y),ws[i]));
  }
  return {points,weights,attachment:{type:'mesh',path:'body',uvs,triangles,vertices,hull:n,width:1254,height:1254}};
}
function poseAt(u,p){
  const glance=pulse(u,.03,.095,.63,.79), engage=pulse(u,.10,.23,.72,.87);
  const split=pulse(u,.23,.33,.68,.82);
  const orbit=smooth((u-.33)/.35)*Math.PI*2;
  const lag=pulse(u,.14,.27,.73,.87);
  const settle=u>.82?Math.sin((u-.82)/.18*Math.PI*4)*Math.sin((u-.82)/.18*Math.PI)*2:0;
  const blink=pulse(u,.085,.102,.115,.14)+pulse(u,.77,.785,.8,.83);
  return {glance,engage,split,orbit,lag,settle,blink};
}
export function compile(contour,input=defaults){
  const p=recipeSchema.parse(input);const mesh=createMesh(contour,p.softness);
  const bones=[{name:'root'},{name:'body',parent:'root',scaleX:.86,scaleY:.86},...controls.map(c=>({...c,parent:'body'})),
    {name:'face',parent:'body',x:-15,y:23},{name:'eye_left',parent:'face',x:-26},
    {name:'eye_right',parent:'face',x:26},{name:'pupil_left',parent:'eye_left',x:8},
    {name:'pupil_right',parent:'eye_right',x:8},{name:'fragment',parent:'root',x:105,y:25},
    {name:'ground_shadow',parent:'root',y:-116},{name:'ball_ground_shadow',parent:'root',x:105,y:-116},
    {name:'body_shadow',parent:'root',x:114,y:10}];
  const slots=[{name:'ground_shadow',bone:'ground_shadow',attachment:'shadow',color:'ffffffb3'},
    {name:'ball_ground_shadow',bone:'ball_ground_shadow',attachment:'shadow',color:'ffffff00'},
    {name:'fragment',bone:'fragment',attachment:'fragment',color:'ffffff00'},
    {name:'body',bone:'body',attachment:'body'},
    {name:'shadow_clip',bone:'body',attachment:'clip'},
    {name:'body_shadow',bone:'body_shadow',attachment:'shadow',color:'ffffff00'},
    ...['left','right'].flatMap(side=>[{name:'eye_'+side,bone:'eye_'+side,attachment:'eye'},
      {name:'pupil_'+side,bone:'pupil_'+side,attachment:'pupil'}])];
  const attachments={body:{body:mesh.attachment},fragment:{fragment:{type:'region',path:'fragment',width:35,height:35}},
    ground_shadow:{shadow:{type:'region',path:'shadow',width:226,height:38}},
    ball_ground_shadow:{shadow:{type:'region',path:'shadow',width:42,height:15}},
    body_shadow:{shadow:{type:'region',path:'shadow',width:55,height:28}},
    shadow_clip:{clip:{type:'clipping',end:'body_shadow',vertexCount:contour.length,vertices:mesh.attachment.vertices.slice(0,contour.length*13)}}};
  for(const side of ['left','right']){
    attachments['eye_'+side]={eye:{type:'region',path:'eye',width:36,height:20}};
    attachments['pupil_'+side]={pupil:{type:'region',path:'pupil',width:10.8,height:10.8}};
  }
  const animation={bones:{},slots:{fragment:{alpha:[]},ground_shadow:{alpha:[]},ball_ground_shadow:{alpha:[]},body_shadow:{alpha:[]}},drawOrder:[],attachments:{default:{body:{body:{deform:[]}},shadow_clip:{clip:{deform:[]}}}}};
  let lastFront;
  function add(name,prop,frame){((animation.bones[name]??={})[prop]??=[]).push(frame);}
  const frames=Math.round(p.duration*p.fps);
  for(let f=0;f<=frames;f++){
    const u=f/frames,time=round(u*p.duration), s=poseAt(u,p), k=p.strength;
    const movement=s.engage*k;
    add('body','rotate',{time,value:round(-2*movement+s.settle*.4*k)});
    add('body','translate',{time,x:round(3*s.lag*k),y:round(3*movement*Math.sin(u*Math.PI*2))});
    controls.forEach((c,i)=>{
      add(c.name,'rotate',{time,value:round([-.45,1,-.6][i]*p.bend*movement)});
      add(c.name,'translate',{time,x:round([-.8,.5,.7][i]*4*movement),y:round([1,-.7,.8][i]*3*movement)});
    });
    add('face','translate',{time,x:round(5*s.lag*k),y:round(2*s.lag*k)});
    for(const side of ['left','right']){
      add('pupil_'+side,'translate',{time,x:round((-14*s.glance*(1-s.split)+(-8+7*Math.cos(s.orbit))*s.split)*p.gaze),y:round((3*s.glance*(1-s.split)-2*Math.sin(s.orbit)*s.split)*p.gaze)});
      add('eye_'+side,'scale',{time,x:round(1-.03*s.blink),y:round(1-.94*Math.min(1,s.blink))});
    }
    // A tilted ellipse in perspective. Positive depth is the near half, below the face.
    const depth=Math.sin(s.orbit),tx=154*Math.cos(s.orbit),ty=18+30*Math.cos(s.orbit)-44*depth;
    const ballX=105+(tx-105)*s.split,ballY=25+(ty-25)*s.split;
    const front=depth>1e-6&&s.split>0;
    if(front!==lastFront||f===frames){animation.drawOrder.push(front?{time,offsets:[{slot:'fragment',offset:slots.length-3}]}:{time});lastFront=front;}
    add('fragment','translate',{time,x:round(ballX-105),y:round(ballY-25)});
    const perspective=1+.22*depth;
    add('fragment','scale',{time,x:round((.01+.99*s.split)*perspective),y:round((.01+.99*s.split)*perspective)});
    // Keep the upper-left lighting direction stable while the ball travels.
    add('fragment','rotate',{time,value:0});
    animation.slots.fragment.alpha.push({time,value:round(s.split)});
    const lift=3*movement*Math.sin(u*Math.PI*2);
    add('ground_shadow','translate',{time,x:round(2*s.lag*k),y:0});
    add('ground_shadow','scale',{time,x:round(1+lift*.012),y:round(1+lift*.02)});
    animation.slots.ground_shadow.alpha.push({time,value:round(.7-lift*.02)});
    add('ball_ground_shadow','translate',{time,x:round(ballX-105),y:round(-depth*12*s.split)});
    add('ball_ground_shadow','scale',{time,x:round(.5+.5*s.split+.15*depth*s.split),y:round(.65+.35*s.split)});
    animation.slots.ball_ground_shadow.alpha.push({time,value:round(.6*s.split)});
    add('body_shadow','translate',{time,x:round(ballX-105),y:round(ballY-25)});
    add('body_shadow','scale',{time,x:round(1+.35*Math.max(0,depth)*s.split),y:round(1+.2*Math.max(0,depth)*s.split)});
    animation.slots.body_shadow.alpha.push({time,value:round(.75*s.split*Math.max(0,depth))});
    const offsets=[];
    for(const v of mesh.points){
      const upper=Math.max(0,(v.y+80)/190),right=Math.exp(-((v.x-100)**2+(v.y-30)**2)/1800);
      // Non-uniform bend + travelling wave + budding/rejoining. Offsets are repeated
      // per influence, not multiplied by weights twice. This is Spine 4.2 weighted FFD.
      const dx=(p.wave*Math.sin(v.y/55-u*Math.PI*5)*upper*movement - 9*right*s.split*k + s.settle*upper*k);
      const dy=p.wave*.7*Math.sin(v.x/60-u*Math.PI*4)*movement + 3*right*s.split*k;
      for(let i=0;i<3;i++)offsets.push(round(dx),round(dy));
    }
    animation.attachments.default.body.body.deform.push({time,vertices:offsets});
    animation.attachments.default.shadow_clip.clip.deform.push({time,vertices:offsets.slice(0,contour.length*6)});
  }
  const json={skeleton:{spine:'4.2.00',images:'./images/',x:-200,y:-150,width:400,height:300,fps:p.fps},
    bones,slots,skins:[{name:'default',attachments}],animations:{recall:animation,rest:{}}};
  return {json,mesh,recipe:p};
}
export function validate(json){
  const errors=[]; const fail=x=>errors.push(x);const att=json.skins?.[0]?.attachments?.body?.body;
  if(!att)return {ok:false,errors:['Missing body mesh']};
  const names=new Set();json.bones.forEach(b=>{if(b.parent&&!names.has(b.parent))fail('Parent order: '+b.name);if(names.has(b.name))fail('Duplicate bone');names.add(b.name);});
  for(const slot of json.slots)if(!names.has(slot.bone))fail('Missing slot bone');
  const count=att.uvs.length/2;let offset=0,n=0;
  while(offset<att.vertices.length){const influences=att.vertices[offset++];if(influences!==3){fail('Unexpected influence count');break;}let sum=0;
    for(let i=0;i<influences;i++){const [b,x,y,w]=att.vertices.slice(offset,offset+4);offset+=4;if(!json.bones[b]||![x,y,w].every(Number.isFinite)||w<0||w>1)fail('Invalid weight');sum+=w;}
    if(Math.abs(sum-1)>1e-6)fail('Weights must sum to 1');n++;
  }
  if(n!==count)fail('Vertex count mismatch');
  if(att.triangles.some(i=>!Number.isInteger(i)||i<0||i>=count))fail('Invalid triangle index');
  if(att.uvs.some(x=>!Number.isFinite(x)||x<0||x>1))fail('Invalid UV');
  const anim=json.animations.recall;const tracks=[...Object.values(anim.bones).flatMap(x=>Object.values(x)),...Object.values(anim.slots).flatMap(x=>Object.values(x)),anim.attachments.default.body.body.deform];
  for(const track of tracks){
    for(let i=0;i<track.length;i++){
      const frame=track[i];if(!Number.isFinite(frame.time)||frame.time<0||(i&&frame.time<=track[i-1].time))fail('Unsorted time');
      if(frame.vertices&&(frame.vertices.length!==count*6||frame.vertices.some(x=>!Number.isFinite(x))))fail('Invalid weighted deform frame');
    }
    const strip=f=>JSON.stringify(Object.fromEntries(Object.entries(f).filter(([k])=>k!=='time')));
    if(strip(track[0])!==strip(track.at(-1)))fail('Loop endpoints differ');
  }
  const clip=json.skins[0].attachments.shadow_clip?.clip;
  if(clip){
    const frames=anim.attachments.default.shadow_clip?.clip?.deform;
    if(!frames||frames.length!==anim.attachments.default.body.body.deform.length)fail('Missing clip deformation');
    else for(const [i,frame] of frames.entries()){
      const bodyFrame=anim.attachments.default.body.body.deform[i];
      if(frame.time!==bodyFrame.time||frame.vertices.length!==clip.vertexCount*6||frame.vertices.some((v,k)=>v!==bodyFrame.vertices[k]))fail('Clip must follow body deformation');
    }
  }
  if(!anim.drawOrder?.length)fail('Missing depth ordering');
  else for(const frame of anim.drawOrder)for(const offset of frame.offsets??[]){const i=json.slots.findIndex(s=>s.name===offset.slot);if(i<0||!Number.isInteger(offset.offset)||i+offset.offset<0||i+offset.offset>=json.slots.length)fail('Invalid depth order');}
  return {ok:errors.length===0,errors:[...new Set(errors)],bones:json.bones.length,vertices:count,triangles:att.triangles.length/3,weighted:true,frames:tracks.at(-1).length,duration:tracks.at(-1).at(-1).time};
}
