// A hinged upright notebook. The audience sees the outside covers, the reader
// sees the pages. All vertices are authored in the book's local 3D projection.
export const bookSlots=['idle_page','idle_paper_left','idle_paper_right','idle_back','idle_book','idle_spine'];
const smooth=t=>{t=Math.max(0,Math.min(1,t));return t*t*(3-2*t);};
const ramp=(t,a,b)=>smooth((t-a)/(b-a));
const round=n=>Math.round(n*1e5)/1e5;
const quad=(l,b,r,t)=>[l,b,r,b,r,t,l,t];
const setup=quad(0,-43,60,43);
function mesh(path){return {type:'mesh',path,uvs:[0,1,1,1,1,0,0,0],triangles:[0,1,2,2,3,0],vertices:setup,hull:4,width:160,height:224};}
export function addBookRig(json){
 json.bones.push({name:'idle_book',parent:'root'},...['idle_cover_left','idle_cover_right','idle_page'].map(name=>({name,parent:'idle_book'})));
 const specs=[['idle_page','idle_page','page'],['idle_paper_left','idle_cover_left','page'],['idle_paper_right','idle_cover_right','page'],['idle_back','idle_cover_left','book-back'],['idle_book','idle_cover_right','book'],['idle_spine','idle_book','book-spine']];
 for(const [name,bone,path] of specs){json.slots.push({name,bone,attachment:path,color:'ffffff00'});json.skins[0].attachments[name]={[path]:mesh(path)};}
}
export function bookPose(t){
 let x=-26,y=-38,angle=-10;
 const out=ramp(t,.4,1.1),front=ramp(t,1.1,1.8),away=ramp(t,6.25,6.9),behind=ramp(t,6.9,7.65);
 x+=160*out-126*front+126*away-160*behind;
 y+=20*out-34*front+34*away-20*behind;
 angle+=-2*out+12*front-12*away+2*behind;
 const open=ramp(t,1.85,2.55)*(1-ramp(t,5.65,6.25));
 return {x:t===0||t===8?0:x,y:t===0||t===8?0:y,angle:t===0||t===8?0:angle,open,flip:t===8?0:ramp(t,3.65,4.55),visible:t>0&&t<8};
}
// Perspective keeps the logo-bearing right cover facing outward at every angle;
// only the unmarked back cover passes through an edge-on projection.
function cover(side,open){
 const angle=side==='right'?-.15-.4*open:-.15-2.4*open;
 const x=60*Math.cos(angle),z=60*Math.sin(angle),depth=1+z*.0015;
 return [0,-43,x,-43*depth+z*.18,x,43*depth+z*.18,0,43];
}
export function bookGeometry(p){
 const right=cover('right',p.open),left=cover('left',p.open);
 const edge=q=>[q[6],q[7],q[4],q[5],q[4],q[5]+3,q[6],q[7]+3];
 const f=p.flip,arc=Math.sin(Math.PI*f),x=55*Math.cos(Math.PI*f),top=43+arc*16,z=-12*arc;
 return {idle_book:right,idle_back:left,idle_spine:quad(-2,-44,2,44),idle_paper_right:edge(right),idle_paper_left:edge(left),
  idle_page:[0,40,x,40+arc*2+z*.1,x,top,0,43]};
}
export function writeBookFrame(json,a,t,add,alpha){
 const p=bookPose(t),geometry=bookGeometry(p);
 add('idle_book','translate',t,{x:p.x,y:p.y});add('idle_book','rotate',t,{value:p.angle});
 for(const slot of bookSlots){
  const visible=p.visible&&(slot!=='idle_page'||(t>=3.65&&t<=4.55));alpha(slot,t,visible?1:0);
  a.slots[slot].alpha.at(-1).curve='stepped';
  const attachment=json.slots.find(s=>s.name===slot).attachment;
  const track=(((a.attachments??={}).default??={})[slot]??={})[attachment]??={deform:[]};
  track.deform.push({time:round(t),vertices:geometry[slot].map((v,i)=>round(v-setup[i]))});
 }
}
export function bookDrawOrder(json){
 const start=json.slots.findIndex(s=>s.name===bookSlots[0]),behind=bookSlots.map(slot=>({slot,offset:3-start}));
 return [{time:0,offsets:behind},{time:1.1,offsets:[]},{time:6.9,offsets:behind},{time:8,offsets:[]}];
}
