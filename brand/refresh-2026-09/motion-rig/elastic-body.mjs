// Normalized world: y points up, bar pitch = 20, capsule radius = 4.
// Spine is the presentation adapter; simulation owns all contact geometry.
export const BODY_SCALE = .2;
export const CAPSULE_RADIUS = 4;
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
export function area(p,hull){let sum=0;for(let i=0;i<hull;i++){const j=(i+1)%hull;sum+=p[2*i]*p[2*j+1]-p[2*j]*p[2*i+1];}return sum/2;}
export function contactGeometry(runtime,rig){
  const s=rig.skeleton;s.setToSetupPose();s.updateWorldTransform(runtime.Physics.none);
  const slot=s.findSlot('body'),a=slot.getAttachment(),world=new Float32Array(a.worldVerticesLength);
  a.computeWorldVertices(slot,0,world.length,world,0,2);
  let bottom=Infinity;for(let i=1;i<world.length;i+=2)bottom=Math.min(bottom,world[i]);
  const rest=Array.from(world,(v,i)=>(v-(i%2?bottom:0))*BODY_SCALE);
  const hull=a.hullLength/2,triangles=Array.from(a.triangles);
  return {rest,hull,triangles,bottom,area:area(rest,hull),span:Math.max(...rest.filter((_,i)=>i%2))};
}
export function createElastic(geometry){return {geometry,points:geometry.rest.slice(),velocity:geometry.rest.map(()=>0),contacts:[],maxPenetration:0,areaRatio:1};}
// Exact circle-vs-line maximum, including edge endpoints. Unlike probes at bar
// centers, this catches a round head entering between two contour vertices.
export function capsuleSupports(points,hull,bars,bodyX){
  const result=[],r=CAPSULE_RADIUS;
  for(let bar=0;bar<bars.length;bar++){
    const cx=(bar-2)*20-bodyX;let best=null;
    for(let i=0;i<hull;i++){
      const j=(i+1)%hull,ax=points[2*i],bx=points[2*j];
      if(bx<=ax+1e-8)continue; // CCW lower envelope (including rising sides).
      const lo=Math.max(ax,cx-r),hi=Math.min(bx,cx+r);if(lo>hi)continue;
      const slope=(points[2*j+1]-points[2*i+1])/(bx-ax);
      const x=clamp(cx-r*slope/Math.sqrt(1+slope*slope),lo,hi),u=(x-ax)/(bx-ax);
      const y=points[2*i+1]+u*(points[2*j+1]-points[2*i+1]);
      const capY=bars[bar]+Math.sqrt(Math.max(0,r*r-(x-cx)**2));
      const support=capY-y;
      if(!best||support>best.support)best={bar,x,y,capY,support,i,j,u};
    }
    if(best)result.push(best);
  }
  return result;
}
export function supportHeight(c,points=c.soft.points){return Math.max(4,...capsuleSupports(points,c.soft.geometry.hull,c.bars,c.x*20).map(k=>k.support));}
function positive(p,g){for(let i=0;i<g.triangles.length;i+=3){const a=g.triangles[i]*2,b=g.triangles[i+1]*2,d=g.triangles[i+2]*2;if((p[b]-p[a])*(p[d+1]-p[a+1])-(p[b+1]-p[a+1])*(p[d]-p[a])<.01)return false;}return true;}
export function resetElastic(c){const e=c.soft;e.points=e.geometry.rest.slice();e.velocity.fill(0);e.contacts=[];e.areaRatio=1;e.maxPenetration=0;c.rootY=supportHeight(c);c.velocity=0;c.height=0;}
export function solveElastic(c,dt){
  const e=c.soft,g=e.geometry,rest=g.rest;
  // Pose targets preserve area; contact deformation itself is spatially local.
  const sy=1-clamp(c.squish,-.08,.2),sx=1/sy;
  const absorb=1-.055*c.absorb;
  const pose=rest.map((v,i)=>i%2?v*sy/absorb:v*sx*absorb);
  const hits=capsuleSupports(pose,g.hull,c.bars,c.x*20).filter(k=>k.support>c.rootY-.6);
  const targets=pose.slice();
  for(let n=0;n<rest.length;n+=2){
    let lift=0;
    for(const hit of hits){
      const dent=Math.min(4.5,Math.max(0,hit.support-c.rootY)+c.impact*3.2+(c.quiet===0?.35:0));
      // Broad, smooth displacement around each cap, decaying through the body.
      lift=Math.max(lift,dent*Math.exp(-(((pose[n]-hit.x)/6.8)**2))*Math.exp(-Math.max(0,pose[n+1]-hit.y)/12));
    }
    targets[n+1]+=lift;
  }
  // Second-order local response retains delayed recovery after separation.
  for(let n=0;n<rest.length;n++){
    e.velocity[n]+=(950*(targets[n]-e.points[n])-40*e.velocity[n])*dt;
    e.points[n]+=e.velocity[n]*dt;
  }
  // Global area constraint prevents shrink-to-fit. Distribute volume laterally,
  // instead of cutting away the lower mesh or stretching a clipping mask.
  const ratio=area(e.points,g.hull)/g.area,expand=clamp(1/ratio,.94,1.08);
  for(let n=0;n<rest.length;n+=2)e.points[n]*=expand;
  // Feasibility line search protects the coarse radial topology during extreme
  // state switches. Contact is re-solved afterward, never hidden by clipping.
  let blend=1;
  while(!positive(e.points,g)&&blend>.015){blend*=.5;for(let n=0;n<rest.length;n++)e.points[n]=rest[n]+(e.points[n]-rest[n])*.5;}
  const required=supportHeight(c),correction=Math.max(0,required-c.rootY);
  c.rootY+=correction; // unilateral nonpenetration, measured on entire edges
  const supports=capsuleSupports(e.points,g.hull,c.bars,c.x*20);
  e.contacts=supports.filter(k=>c.rootY-k.support<.28).map(k=>({...k,depth:Math.max(0,hits.find(h=>h.bar===k.bar)?.support-c.rootY||0)}));
  e.maxPenetration=Math.max(0,...supports.map(k=>k.support-c.rootY));e.areaRatio=area(e.points,g.hull)/g.area;
  return {correction,contacts:e.contacts};
}
