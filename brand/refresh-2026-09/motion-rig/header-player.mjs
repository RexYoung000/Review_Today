// Header-only pointer response on the existing Spine bones and weighted mesh.
const clamp=v=>Number.isFinite(v)?Math.max(-1,Math.min(1,v)):0;
export const headerReactions=['squash','wobble','hop'];
export function createHeaderPlayer(random=Math.random){
 let x=0,y=0,tx=0,ty=0,elapsed=1,reaction=null;
 return {
  pointer(px,py){tx=clamp(px);ty=clamp(py);},
  quiet(){tx=ty=0;},
  reset(){x=y=tx=ty=0;elapsed=1;},
  poke(){
   if(elapsed<.72)return false;
   const choices=headerReactions.filter(name=>name!==reaction);
   reaction=choices[Math.min(choices.length-1,Math.floor(Math.max(0,random())*choices.length))];
   elapsed=0;return true;
  },
  advance(dt){dt=Math.max(0,Math.min(.05,dt));const blend=1-Math.exp(-dt*24);x+=(tx-x)*blend;y+=(ty-y)*blend;elapsed=Math.min(1,elapsed+dt);if(Math.abs(x-tx)<.001)x=tx;if(Math.abs(y-ty)<.001)y=ty;},
  moving(){return x!==tx||y!==ty||elapsed<.72;},
  inspect(){return {x,y,tx,ty,elapsed,reaction};},
  apply(s){
   const b=s.findBone('body'),face=s.findBone('face');
   // Brief squash, damped recovery, then exact rest. No queued reactions.
   const t=elapsed,impact=t<.72?Math.sin(Math.min(1,t/.12)*Math.PI/2)*Math.exp(-t*6)*Math.cos(Math.max(0,t-.12)*17)*(1-t/.72):0;
   let eyes=1;
   if(reaction==='squash'){
    b.scaleY*=1-.24*impact;b.scaleX*=1+.16*impact;
    eyes+=Math.max(0,impact)*.35;
   }else if(reaction==='wobble'&&t<.72){
    const u=t/.72,envelope=Math.sin(Math.PI*u)*(1-u),sway=Math.sin(u*Math.PI*4)*envelope;
    b.rotation+=18*sway;face.rotation-=8*sway;
    b.scaleX*=1+.05*Math.abs(sway);b.scaleY*=1-.04*Math.abs(sway);
    eyes-=.28*Math.sin(Math.PI*u)**2;
   }else if(reaction==='hop'&&t<.72){
    // Anticipation -> short arc -> soft landing, with an exact neutral finish.
    const preload=t<.12?Math.sin(t/.12*Math.PI):0;
    const flight=t>=.12&&t<.46?Math.sin((t-.12)/.34*Math.PI):0;
    const landing=t>=.46?Math.sin((t-.46)/.26*Math.PI)*(1-(t-.46)/.26):0;
    b.y+=18*flight;b.scaleX*=1+.1*preload-.06*flight+.12*landing;
    b.scaleY*=1-.14*preload+.1*flight-.16*landing;
    eyes+=.2*flight-.15*landing;
   }
   b.rotation-=x*2;face.x+=x*2;face.y+=y;
   for(const side of ['left','right']){
    const pupil=s.findBone('pupil_'+side),eye=s.findBone('eye_'+side);
    pupil.x=x*9;pupil.y=y*3;
    eye.scaleY*=eyes;
   }
  }
 };
}
