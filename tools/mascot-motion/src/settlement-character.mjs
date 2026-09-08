// Same source contour and UV coordinate system as the daily Spine body.
// Bundling inlines this JSON; there is no separately redesigned silhouette.
import contour from '../../../brand/refresh-2026-09/motion-rig/assets/contour.json' with {type:'json'};
export {contour};
export function referencePoint(theta,v,scale=.70){
 const nx=Math.sin(theta)*Math.cos(v),ny=Math.sin(v),r=Math.hypot(nx,ny);
 const angle=(Math.atan2(-ny,nx)+Math.PI*2)%(Math.PI*2),index=angle/(Math.PI*2)*contour.length,i=Math.floor(index),f=index-i;
 const a=contour[i],b=contour[(i+1)%contour.length];
 const length=Math.hypot(a.x,a.y)*(1-f)+Math.hypot(b.x,b.y)*f;
 const x=r?nx*length:0,y=r?ny*length:0;
 return {x:x*scale,y:y*scale,u:(x/280*999+629)/1254,v:(y/280*999+614)/1254};
}
