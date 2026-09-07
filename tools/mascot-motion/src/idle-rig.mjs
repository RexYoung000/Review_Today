// Additive authoring: existing mesh, bone indices and working animation tracks stay intact.
export const idleClips={idle_look:4,idle_hop:3.2,idle_stretch:3.6,idle_book:6};
const smooth=t=>{t=Math.max(0,Math.min(1,t));return t*t*(3-2*t);};
const ramp=(t,a,b)=>smooth((t-a)/(b-a));
const pulse=(t,a,b,c,d)=>ramp(t,a,b)*(1-ramp(t,c,d));
const round=n=>Math.round(n*1e5)/1e5;
export function addIdleRig(json){
 json.bones.push({name:'idle_book',parent:'root',y:-45},{name:'idle_page',parent:'idle_book'});
 json.slots.push({name:'idle_book',bone:'idle_book',attachment:'book',color:'ffffff00'},{name:'idle_page',bone:'idle_page',attachment:'page',color:'ffffff00'});
 Object.assign(json.skins[0].attachments,{idle_book:{book:{type:'region',path:'book',width:126,height:72}},idle_page:{page:{type:'region',path:'page',x:28,width:56,height:62}}});
 for(const [name,duration] of Object.entries(idleClips)){
  const a={bones:{},slots:{}};
  const add=(bone,prop,time,data)=>((a.bones[bone]??={})[prop]??=[]).push({time,...Object.fromEntries(Object.entries(data).map(([k,v])=>[k,round(v)]))});
  const alpha=(slot,time,value)=>((a.slots[slot]??={}).alpha??=[]).push({time,value:round(value)});
  const frames=Math.round(duration*30);
  for(let i=0;i<=frames;i++){
   const t=duration*i/frames,time=round(t),end=i===0||i===frames;
   let gaze=0,lookY=0,tilt=0,lift=0,sx=1,sy=1,blink=0,book=0,flip=0;
   if(!end){
    if(name==='idle_look'){gaze=-15*pulse(t,.2,.7,1.3,1.65)+3*pulse(t,1.6,2.15,2.85,3.55);tilt=gaze*.2;blink=pulse(t,3.55,3.65,3.70,3.85);}
    if(name==='idle_hop'){const crouch=pulse(t,.15,.5,.55,.75),land=pulse(t,1.05,1.18,1.3,1.65);lift=t>.65&&t<1.2?11*Math.sin(Math.PI*(t-.65)/.55):0;sy=1-.065*crouch-.055*land;sx=1+.025*crouch+.025*land;lookY=lift*.15;}
    if(name==='idle_stretch'){const stretch=pulse(t,.5,1.2,1.8,2.8);sx=1-.035*stretch;sy=1+.065*stretch;blink=pulse(t,.15,.25,.3,.48)+pulse(t,2.85,2.95,3.02,3.2);}
    if(name==='idle_book'){book=pulse(t,.25,.85,5,5.6);lookY=-4*book;gaze=-5*book;tilt=-2*book;flip=ramp(t,2.5,3.5);blink=pulse(t,4.2,4.3,4.36,4.52);}
   }
   add('body','translate',time,{x:0,y:lift});add('body','scale',time,{x:sx,y:sy});add('body','rotate',time,{value:tilt});
   for(const side of ['left','right']){add('pupil_'+side,'translate',time,{x:gaze,y:lookY});add('eye_'+side,'scale',time,{x:1,y:1-.94*blink});}
   add('ground_shadow','scale',time,{x:1-lift*.015,y:1-lift*.01});alpha('ground_shadow',time,.7-lift*.024);
   if(name==='idle_book'){
    alpha('idle_book',time,book);alpha('idle_page',time,book);
    add('idle_book','scale',time,{x:.01+.99*book,y:.85+.15*book});add('idle_book','translate',time,{x:0,y:-8*(1-book)});
    add('idle_page','scale',time,{x:1-2*flip,y:1});
   }
  }
  // Hidden prop returns to setup-compatible values, including its page hinge.
  json.animations[name]=a;
 }
 return json;
}
