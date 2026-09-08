// Presentation only. No business status, network, or persistence lives here.
export const durations={mr_receive:1.5,mr_ponder:3.8,mr_weigh:3.6,mr_focus:3.2,mr_peek:4.8,mr_hide:6,mr_ingest:6,mr_ingest_short:1.6,mr_review:3};
export const thinking=['mr_ponder','mr_weigh','mr_focus'];
export const classic=['idle_look','idle_hop','idle_stretch','idle_book'];
export function createSequence(random=Math.random){
 let previous='',oldSinceNew=2,step=0;
 return { next(kind='thinking',organizing=false){
  let candidates=kind==='idle'?classic:thinking;
  if(kind==='idle'&&oldSinceNew>=2&&random()<.25)candidates=['mr_peek','mr_hide'];
  if(kind==='thinking'&&organizing&&step>0&&step%4===0)candidates=['recall'];
  candidates=candidates.filter(x=>x!==previous);
  const clip=candidates[Math.min(candidates.length-1,Math.floor(random()*candidates.length))];
  oldSinceNew=clip.startsWith('idle_')?oldSinceNew+1:0;previous=clip;step++;
  return {clip,wait:kind==='idle'?1.5+random()*1.5:1+random()};
 }};
}
export const clamp=x=>Math.max(0,Math.min(1,x));
export const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
// All scene layers share this clock: transfers never drift from the Spine roll.
export function ingestion(time,short=false){
 const t=short?time/1.6*6:time,roll=clamp((t-.55)/3.6)*3;
 const row=Math.min(2,Math.floor(roll)),progress=roll>=3?1:roll-row;
 const x=90+340*(row%2?1-ease(progress):ease(progress));
 const settle=ease((t-4.2)/.8);
 return {time:t,row,progress,removed:[0,1,2].map(i=>clamp(roll-i)),
  x:x+(410-x)*settle,y:54+row*42+(120-(54+row*42))*settle,
  card:ease((t-4.75)/.7),ink:ease((t-.6)/.3)*(1-ease((t-4.6)/.7))};
}
