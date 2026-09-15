// Header-only pointer response on the existing Spine bones and weighted mesh.
const clamp=v=>Number.isFinite(v)?Math.max(-1,Math.min(1,v)):0;
export function createHeaderPlayer(){
 let x=0,y=0,tx=0,ty=0,elapsed=1;
 return {
  pointer(px,py){tx=clamp(px);ty=clamp(py);},
  quiet(){tx=ty=0;},
  reset(){x=y=tx=ty=0;elapsed=1;},
  poke(){if(elapsed<.72)return false;elapsed=0;return true;},
  advance(dt){dt=Math.max(0,Math.min(.05,dt));const blend=1-Math.exp(-dt*24);x+=(tx-x)*blend;y+=(ty-y)*blend;elapsed=Math.min(1,elapsed+dt);if(Math.abs(x-tx)<.001)x=tx;if(Math.abs(y-ty)<.001)y=ty;},
  moving(){return x!==tx||y!==ty||elapsed<.72;},
  inspect(){return {x,y,tx,ty,elapsed};},
  apply(s){
   const b=s.findBone('body'),face=s.findBone('face');
   // Brief squash, damped recovery, then exact rest. No queued reactions.
   const t=elapsed,impact=t<.72?Math.sin(Math.min(1,t/.12)*Math.PI/2)*Math.exp(-t*6)*Math.cos(Math.max(0,t-.12)*17)*(1-t/.72):0;
   b.scaleY*=1-.24*impact;b.scaleX*=1+.16*impact;
   b.rotation-=x*2;face.x+=x*2;face.y+=y;
   for(const side of ['left','right']){
    const pupil=s.findBone('pupil_'+side),eye=s.findBone('eye_'+side);
    pupil.x=x*9;pupil.y=y*3;
    eye.scaleY*=1+Math.max(0,impact)*.35;
   }
  }
 };
}
