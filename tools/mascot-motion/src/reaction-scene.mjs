import {poseFrame,stamping,clamp} from './settlement-scene.mjs';
export const reactionKinds=['reaction_approve','reaction_encourage','reaction_guide'];
export const reactionDuration=3.2;
export const reactionViewport={x:205,y:18,width:350,height:340};
const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
const pulse=(t,a,b,c,d)=>ease((t-a)/(b-a))*(1-ease((t-c)/(d-c)));
export function reactionFrame(kind,time,reduced=false){
 const t=reduced?({reaction_approve:.9,reaction_encourage:1.5,reaction_guide:1.35}[kind]??0):Math.max(0,Math.min(reactionDuration,time));
 let sx=1,sy=1,lean=0,shift=0,bulge=0,gaze=0,nod=0;
 if(kind==='reaction_approve'){
  const crouch=pulse(t,.12,.38,.42,.65),proud=pulse(t,.5,.78,1.20,1.48),bow=pulse(t,1.24,1.44,1.55,1.80),settle=pulse(t,1.7,1.9,2.05,2.55);
  sy=1-.28*crouch+.42*proud-.2*bow+.1*settle;sx=1+.22*crouch-.14*proud+.12*bow;
  bulge=.19*crouch-.06*proud+.10*bow;nod=bow;gaze=-1.2*proud;
 } else if(kind==='reaction_encourage'){
  const close=pulse(t,.15,.62,1.50,2.20),yes=pulse(t,1.12,1.42,1.55,1.97);
  lean=-49*close;shift=-5*close;sy=1-.08*close-.23*yes;sx=1+.06*close+.1*yes;bulge=.13*yes;nod=yes;gaze=-3.2*pulse(t,.04,.25,1.65,2.3);
 } else if(kind==='reaction_guide'){
  const turn=pulse(t,.22,.84,1.98,2.90);
  lean=72*turn;shift=7*turn;sy=1-.12*turn;sx=1+.06*turn;bulge=.16*turn;gaze=4.2*pulse(t,.03,.22,2.25,2.92);
 }
 const p=stamping(0);p.gaze=[0,0];
 const f=poseFrame(kind,time,p,false,'stamp_study','');
 f.patches=f.patches.filter(p=>['body','body_shadow','eye0','eye1','pupil0','pupil1'].includes(p.id));
 const body=f.patches.find(p=>p.id==='body'),ground=Math.max(...body.points.map(p=>p[1])),top=Math.min(...body.points.map(p=>p[1])),height=ground-top;
 const anchor=312,warp=([x,y,z])=>{const v=(ground-y)/height;return [380+shift+(x-380)*sx*(1+bulge*Math.sin(Math.PI*v))+lean*v*v,anchor-(ground-y)*sy,z];};
 body.points=body.points.map(warp);
 // Keep the small facial features rigid and contained while their shared anchor
 // follows the deforming surface; do not stretch pupils with the body mesh.
 const [fx,fy]=warp([380,154-23*.7,11]);
 for(const item of f.patches.filter(p=>p.material==='eye'||p.material==='pupil')){
  const isPupil=item.material==='pupil',side=item.id.endsWith('1')?11:-41;
  const cx=fx+side*.7,cy=fy+nod*3;
  const ox=380+side*.7,oy=154-23*.7;
  item.points=item.points.map(([x,y,z])=>[cx+(x-ox)+(isPupil?gaze:0),cy+(y-oy)+(isPupil?nod*1.2:0),z]);
 }
 const shadow=f.patches.find(p=>p.id==='body_shadow');
 shadow.points=shadow.points.map(([x,y,z])=>[380+shift+(x-380)*Math.min(1.22,sx),anchor+5+(y-234)*(.8+.2/sy),z]);
 shadow.alpha=.55;
 f.viewport=reactionViewport;
 f.meta={body:[380+shift,anchor-height*sy/2],contact:[380+shift,anchor],phase:kind,lean,sy,sx,bulge,reaction:kind,representativeTime:t};
 return f;
}
export function returnReaction(source,time,reduced=false){
 const neutral=reactionFrame('reaction_rest',0),q=reduced?1:ease(time/.18);
 if(!source)return {...neutral,time,kind:'reaction_rest'};
 return {...neutral,time,kind:'reaction_rest',patches:neutral.patches.map((p,i)=>({...p,points:p.points.map((point,j)=>point.map((v,k)=>k===2?v:source.patches[i].points[j][k]*(1-q)+v*q))}))};
}
