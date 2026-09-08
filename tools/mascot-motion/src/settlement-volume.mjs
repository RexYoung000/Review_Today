import {referencePoint} from './settlement-character.mjs';
// Authored soft-volume scene, projected into Spine mesh attachments. Z is height
// above the paper, not screen Y. One fixed overhead camera for both studies.
export const studyDuration={walk_study:6.4,stamp_study:7.2};
export const stage={width:760,height:400,cameraZ:980,cx:380,cy:200};
const TAU=Math.PI*2;
export const clamp=x=>Math.max(0,Math.min(1,x));
const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
const ramp=(t,a,b)=>ease((t-a)/(b-a));
const lerp=(a,b,t)=>a+(b-a)*t;
const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const unit=a=>{const l=Math.hypot(...a)||1;return a.map(v=>v/l);};
const avg=ps=>ps[0].map((_,i)=>ps.reduce((s,p)=>s+p[i],0)/ps.length);
export function project([x,y,z]){const f=stage.cameraZ/(stage.cameraZ-z);return [stage.cx+(x-stage.cx)*f,stage.cy+(y-stage.cy)*f];}
// Translation is paired with a travelling deformation at the lower edge.
// No rotation, surface ink, or cylinder integration remains in this study.
export function walking(t){
 const move=ramp(t,.7,5.1),distance=458*move;
 return {x:118+distance,y:176,distance,phase:distance/72*TAU,activity:ramp(t,.2,.65)*(1-ramp(t,5.1,5.65)),erasedX:118+distance};
}
export function stamping(t){
 const carry=ramp(t,.55,1.85),land=ramp(t,1.85,2.3),release=ramp(t,2.35,2.7);
 const fetch=ramp(t,2.85,3.8),down=ramp(t,4.15,4.55),up=ramp(t,4.85,5.3),away=ramp(t,5.5,6.35);
 const card={x:lerp(525,281,carry),y:lerp(187,207,carry),z:2+23*ramp(t,.25,.55)*(1-land),yaw:-.09*Math.sin(carry*Math.PI)*(1-land)};
 const stamp={x:lerp(506,281,fetch)*(1-away)+506*away,y:lerp(174,207,fetch)*(1-away)+174*away,z:6.2+64*fetch-64*down+76*up-76*away};
 const bX=525-51*carry+18*release-62*fetch+62*away;
 return {card,stamp,bodyX:bX,carry,land,release,fetch,down,up,away,grip:(fetch*(1-away)),imprinted:t>=4.55,pressure:down*(1-up)};
}
function patch(id,points,material='body',extra={}){
 const n=unit(cross(sub(points[1],points[0]),sub(points[2],points[0]))),center=avg(points);
 return {id,points,material,normal:n,depth:center[2],visible:dot(n,sub([stage.cx,stage.cy,stage.cameraZ],center))>0.001,...extra};
}
// The original contour is draped over a shallow volume solely for prop
// occlusion/contact. Its original material supplies colour, never new highlights.
export function bodySurface(kind,t){
 const walk=kind==='walk_study',p=walk?walking(t):stamping(t);
 const scale=.70,height=walk?34:45-6*p.pressure;
 return (theta,v,offset=0)=>{
  const rest=referencePoint(theta,v,scale),round=Math.cos(theta)*Math.cos(v);
  let x=rest.x,y=rest.y,z=Math.max(0,height+45*round);
  if(walk){
   const lower=ramp(y,5,75),edge=lower*lower;
   // Alternating raised arches and planted lobes pass from front to rear.
   // The face-bearing upper area is untouched; the lower body really deforms.
   const wave=Math.sin(x/20+p.phase);
   y-=edge*p.activity*(8+8*wave);
   x+=edge*p.activity*3*Math.cos(x/20+p.phase);
   z+=Math.max(0,wave)*edge*p.activity*3;
  }else{
   const left=Math.exp(-Math.pow(Math.atan2(Math.sin(theta+Math.PI/2),Math.cos(theta+Math.PI/2))/.47,2))*Math.exp(-Math.pow(v/.42,2));
   const supportCard=p.carry*(1-p.release),grip=p.grip;
   // Keep the already verified underside / shaft contact targets while the
   // neutral silhouette comes from the actual Mr. B source contour.
   const baseLeft=referencePoint(-Math.PI/2,0,scale).x;
   const target=-114.5*supportCard-145*grip;
   x+=left*(target-baseLeft*(supportCard+grip));
   z+=left*((p.card.z-height)*supportCard+(p.stamp.z+30-height)*grip);
   y+=left*13*(supportCard+grip);
  }
  // Body texture and eye attachments share the same material-space position.
  if(offset)z+=offset;
  x+=walk?p.x:p.bodyX;y+=walk?p.y:187;z=Math.max(0,z);
  if(!walk && p.grip>.95){
   const localZ=z-p.stamp.z;
   if(localZ>16 && localZ<43){
    const shaftRadius=localZ<21?18-(localZ-16)*7/5:localZ<38?10:10+(localZ-38)*6/7;
    const dx=x-p.stamp.x,dy=y-p.stamp.y,d=Math.hypot(dx,dy),limit=shaftRadius+.7;
    if(d<limit){x=p.stamp.x+dx/(d||1)*limit;y=p.stamp.y+dy/(d||1)*limit;}
   }
  }
  return [x,y,z];
 };
}
function surfaceNormal(fn,a,v){const e=.0001;return unit(cross(sub(fn(a+e,v),fn(a-e,v)),sub(fn(a,v+e),fn(a,v-e))));}
const light=unit([-.55,-.7,1]);
function shade(n){const diffuse=Math.max(0,dot(n,light)),spec=Math.max(0,dot(n,unit([-.25,-.32,1])))**22;return .14+.67*diffuse+.19*spec;}
function surfaceGrid(out,prefix,fn,a0,a1,v0,v1,n,m,material='body',uv=[0,0,1,1],visible=true){
 for(let j=0;j<m;j++)for(let i=0;i<n;i++){
  const a=lerp(a0,a1,i/n),b=lerp(a0,a1,(i+1)/n),v=lerp(v0,v1,j/m),w=lerp(v0,v1,(j+1)/m);
  const params=[[a,v],[b,v],[b,w],[a,w]],points=params.map(p=>fn(...p));
  out.push(patch(`${prefix}_${j}_${i}`,points,material,{enabled:visible,tones:params.map(p=>shade(surfaceNormal(fn,...p))),uvs:material==='body'?params.flatMap(([a,v])=>{const p=referencePoint(a,v);return [p.u,p.v];}):[lerp(uv[0],uv[2],i/n),lerp(uv[1],uv[3],j/m),lerp(uv[0],uv[2],(i+1)/n),lerp(uv[1],uv[3],j/m),lerp(uv[0],uv[2],(i+1)/n),lerp(uv[1],uv[3],(j+1)/m),lerp(uv[0],uv[2],i/n),lerp(uv[1],uv[3],(j+1)/m)]}));
 }
}
function roundedOutline(w,h,r,steps=6){const out=[];for(let c=0;c<4;c++){const cx=c===0||c===3?w/2-r:-w/2+r,cy=c<2?h/2-r:-h/2+r;for(let i=0;i<=steps;i++){const a=c*Math.PI/2+i/steps*Math.PI/2;out.push([cx+r*Math.cos(a),cy+r*Math.sin(a)]);}}return out;}
// Planar top is triangulated into quads with a small central inset to avoid
// degenerate UVs; renderer/export use a centre fan with non-degenerate triangles.
function solid(out,id,outline,z0,z1,center,material,yaw=0){
 const tr=([x,y,z])=>[center[0]+x*Math.cos(yaw)-y*Math.sin(yaw),center[1]+x*Math.sin(yaw)+y*Math.cos(yaw),z];
 const len=outline.length;
 for(let i=0;i<len;i++){
  const a=outline[i],b=outline[(i+1)%len];
  out.push(patch(`${id}_side_${i}`,[tr([...b,z0]),tr([...a,z0]),tr([...a,z1]),tr([...b,z1])],material+'_edge'));
  out.push(patch(`${id}_top_${i}`,[tr([a[0]*.001,a[1]*.001,z1]),tr([...a,z1]),tr([...b,z1]),tr([b[0]*.001,b[1]*.001,z1])],material));
 }
}
function stampGeometry(out,p){
 solid(out,'stamp_foot',roundedOutline(68,55,10,7),p.z,p.z+11,[p.x,p.y],'stamp');
 solid(out,'stamp_pad',roundedOutline(60,47,7,6),p.z-2,p.z,[p.x,p.y],'rubber');
 // Turned handle: separate height rings, closed domed cap, fixed overhead view.
 const rings=[[p.z+11,20],[p.z+16,18],[p.z+21,11],[p.z+38,10],[p.z+45,16],[p.z+50,19],[p.z+55,18],[p.z+59,12],[p.z+60,0.05]];
 for(let j=0;j<rings.length-1;j++)for(let i=0;i<40;i++){
  const a=i/40*TAU,b=(i+1)/40*TAU,[z,r]=rings[j],[zz,rr]=rings[j+1];
  out.push(patch(`handle_${j}_${i}`,[[p.x+r*Math.cos(b),p.y+r*Math.sin(b),z],[p.x+r*Math.cos(a),p.y+r*Math.sin(a),z],[p.x+rr*Math.cos(a),p.y+rr*Math.sin(a),zz],[p.x+rr*Math.cos(b),p.y+rr*Math.sin(b),zz]],'stamp',{tones:[shade(unit([Math.cos(a),Math.sin(a),.3]))]}));
 }
}
export function scene(kind,time){
 const t=Math.max(0,Math.min(studyDuration[kind],time)),out=[],walk=kind==='walk_study',p=walk?walking(t):stamping(t),surface=bodySurface(kind,t);
 surfaceGrid(out,'bread',surface,-Math.PI,Math.PI,-Math.PI/2+.001,Math.PI/2-.001,64,24);
 for(let eye=0;eye<2;eye++){
  // Daily rig: face (-15,23), eyes +/-26, 36x20, pupil 10.8x10.8.
  const a=(eye?11:-41)/137,v=-23/108;
  surfaceGrid(out,`eye${eye}`,(a,v)=>surface(a,v,1.1),a-.131,a+.131,v-.0925,v+.0925,6,4,'eye');
  surfaceGrid(out,`pupil${eye}`,(a,v)=>surface(a,v,1.4),a+.02,a+.096,v-.05,v+.05,4,4,'pupil');
 }
 let meta;
 if(walk){
  const source={x:230,y:216,w:220,h:18},cut=Math.max(source.x,Math.min(source.x+source.w,p.erasedX));
  // Erase inside the covered contact band, so no letters reappear behind
  // a lifted lobe. The whole text height has been covered at this X.
  out.push(patch('source',[[cut,source.y,0.04],[source.x+source.w,source.y,0.04],[source.x+source.w,source.y+source.h,0.04],[cut,source.y+source.h,0.04]],'text',{enabled:cut<source.x+source.w,uvs:[(cut-source.x)/source.w,0,1,0,1,1,(cut-source.x)/source.w,1]}));
  meta={body:[p.x,p.y],height:34,contact:[p.x,p.y+58],erasedX:cut,source,activity:p.activity,stepPhase:p.phase,phase:t<.7?'准备迈步':t<5.1?'底缘波浪行走、经过后消字':'站稳，演出文字已收好'};
 }else{
  solid(out,'card',roundedOutline(162,104,12,8),p.card.z,p.card.z+2.2,[p.card.x,p.card.y],'paper',p.card.yaw);
  stampGeometry(out,p.stamp);
  const z=p.card.z+2.25;
  out.push(patch('logo',[[p.card.x-24,p.card.y-24,z],[p.card.x+24,p.card.y-24,z],[p.card.x+24,p.card.y+24,z],[p.card.x-24,p.card.y+24,z]],'logo',{enabled:p.imprinted,uvs:[0,0,1,0,1,1,0,1]}));
  meta={body:[p.bodyX,187],height:45,contact:[p.card.x+81,p.card.y],...p,phase:t<2.35?'托出、放下卡片':t<4.15?'承托章柄，移至卡面上方':t<4.85?'垂直下压、压实':t<6.4?'抬起印章，收回身体':'R 印记留在卡面'};
 }
 // Non-planar quads at the soft side silhouette can have one front and one
 // back-facing triangle. Separate them before culling/export; never drop a
 // whole quad or render its hidden half through the surface.
 const triangles=out.flatMap(p=>[[0,1,2,2],[2,3,0,0]].map((ids,i)=>patch(p.id+(i?'_b':''),ids.map(j=>p.points[j]),p.material,{enabled:p.enabled,tones:ids.map(j=>p.tones?.[j]??p.tones?.[0]??(.3+.7*Math.max(0,p.normal[2]))),uvs:ids.flatMap(j=>(p.uvs??[0,0,1,0,1,1,0,1]).slice(j*2,j*2+2))})));
 return {patches:triangles,meta,time:t,kind};
}
export function spineData(frame){
 const slots=[],attachments={};
 for(const p of frame.patches){const uv=p.uvs??[0,0,1,0,1,1,0,1];slots.push({name:p.id,bone:'root',attachment:p.id});attachments[p.id]={[p.id]:{type:'mesh',path:p.material,uvs:uv,triangles:[0,1,2,2,3,0],vertices:p.points.flatMap(project),hull:4,width:64,height:64}};}
 return {skeleton:{spine:'4.2.00'},bones:[{name:'root'}],slots,skins:[{name:'default',attachments}],animations:{}};
}
export function applyScene(skeleton,frame){
 const depths=new Map(),slots=skeleton.studySlots??=new Map(skeleton.slots.map(s=>[s.data.name,s]));
 for(const p of frame.patches){const slot=slots.get(p.id);slot.color.a=p.visible&&p.enabled!==false?1:0;slot.deform=p.points.flatMap(project);depths.set(p.id,p.depth);}
 skeleton.drawOrder=[...skeleton.slots].sort((a,b)=>depths.get(a.data.name)-depths.get(b.data.name));skeleton.updateWorldTransform(0);
}
export function bakeStudy(kind,fps=30){
 const first=scene(kind,0),json=spineData(first),animation={attachments:{default:{}},slots:{},drawOrder:[]};
 const round=n=>Math.round(n*100)/100;
 const baseIndex=new Map(json.slots.map((s,i)=>[s.name,i]));
 for(let i=0;i<=studyDuration[kind]*fps;i++){
  const time=i/fps,f=scene(kind,time);
  for(const p of f.patches){const att=json.skins[0].attachments[p.id][p.id],visible=p.visible&&p.enabled!==false;
   const slots=animation.slots[p.id]??={alpha:[],rgb:[]};
   if(visible&&!['body','eye','pupil','text','logo'].includes(p.material)){const tone=(p.tones??[.6]).reduce((s,x)=>s+x,0)/(p.tones?.length??1),grey=p.material==='body'?12+53*tone:p.material.startsWith('stamp')?34+63*tone:p.material.startsWith('rubber')?24:p.material==='paper_edge'?205:253,hex=Math.round(grey).toString(16).padStart(2,'0').repeat(3);if(slots.rgb.at(-1)?.color!==hex)slots.rgb.push({time,color:hex});}
   const old=slots.alpha.at(-1)?.value;if(old!==Number(visible))slots.alpha.push({time,value:Number(visible),curve:'stepped'});
   if(visible){const track=(animation.attachments.default[p.id]??={})[p.id]??={deform:[]};track.deform.push({time,vertices:p.points.flatMap(project).map((v,j)=>round(v-att.vertices[j]))});}
  }
  const order=[...f.patches].sort((a,b)=>a.depth-b.depth);const offsets=order.map((p,target)=>({slot:p.id,offset:target-baseIndex.get(p.id)})).sort((a,b)=>baseIndex.get(a.slot)-baseIndex.get(b.slot));animation.drawOrder.push({time,offsets});
 }
 for(const slot of Object.values(animation.slots))if(!slot.rgb.length)delete slot.rgb;
 json.animations[kind]=animation;return json;
}
