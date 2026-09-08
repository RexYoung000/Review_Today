import {stage,scene,spineData,applyScene,project,studyDuration} from './settlement-volume.mjs';
const materials=['body','eye','pupil','text','paper','paper_edge','stamp','stamp_edge','rubber','rubber_edge','logo'];
const mix=(a,b,t)=>a+(b-a)*t;
export async function createStudyPlayer(spine,ctx,logoURL,platform={}){
 const logo=platform.loadImage?await platform.loadImage(logoURL):await (async()=>{const image=new Image();image.src=logoURL;await image.decode();return image;})();
 let json,rig,currentKind,textures,texels,darkValue,englishValue,paintedPixels=0;
 const raster=canvas(1520,800),rctx=raster.getContext('2d'),pixels=rctx.createImageData(1520,800),depth=new Float32Array(1520*800);
 function canvas(w,h){if(platform.createCanvas)return platform.createCanvas(w,h);const c=document.createElement('canvas');c.width=w;c.height=h;return c;}
 function makeTextures(dark,english){const map={};for(const material of materials){const [tw,th]=material==='body'?[1254,1254]:material==='eye'?[144,80]:material==='pupil'?[48,48]:material==='logo'?[512,512]:[1024,128],c=canvas(tw,th),g=c.getContext('2d');
  if(material==='body'){const original=platform.bodyTexture?.(dark);if(!original)throw new Error('Missing original Mr. B body material');g.drawImage(original,0,0,c.width,c.height);}
  else if(material==='text'){g.fillStyle=dark?'#bebebe':'#666666';g.font=`500 ${english?94:104}px "PingFang SC", sans-serif`;g.textAlign='center';g.textBaseline='middle';const letters=Array.from(english?'Keep what matters':'让知识留下来');letters.forEach((letter,i)=>g.fillText(letter,(i+.5)*1024/letters.length,65,1024/letters.length-4));}
  else if(material==='logo'){g.fillStyle=dark?'#dddddd':'#323232';g.fillRect(0,0,c.width,c.height);g.globalCompositeOperation='destination-in';g.drawImage(logo,0,0,c.width,c.height);}
  else if(material==='eye'){g.fillStyle='#f7f7f7';g.beginPath();g.roundRect(2,2,140,76,38);g.fill();if(dark){g.strokeStyle='#777';g.lineWidth=2;g.stroke();}}
  else if(material==='pupil'){g.fillStyle='#232323';g.beginPath();g.arc(24,24,22,0,Math.PI*2);g.fill();}
  else {g.fillStyle='#fff';g.fillRect(0,0,c.width,c.height);}map[material]=c;
 }return map;}
 function setup(kind,dark,english){textures=makeTextures(dark,english);texels=Object.fromEntries(Object.entries(textures).map(([k,c])=>[k,{data:c.getContext('2d').getImageData(0,0,c.width,c.height).data,w:c.width,h:c.height}]));darkValue=dark;englishValue=english;currentKind=kind;
  const atlasText=materials.map(name=>`${name}.png\nsize: ${textures[name].width},${textures[name].height}\nfilter: Linear,Linear\n${name}\nbounds: 0,0,${textures[name].width},${textures[name].height}\n`).join('\n');
  const atlas=new spine.TextureAtlas(atlasText);for(const page of atlas.pages)page.setTexture(new spine.CanvasTexture(textures[page.name.replace('.png','')]));
  json=spineData(scene(kind,0));const data=new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(json);rig=new spine.Skeleton(data);
 }
 function value(material,tone,dark){
  if(material.startsWith('stamp'))return mix(dark?100:34,dark?218:97,tone);
  if(material.startsWith('rubber'))return dark?52:24;
  if(material==='paper_edge')return dark?72:205;
  return dark?56:253;
 }
 function polygon(ps){ctx.beginPath();ps.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();}
 // A depth buffer resolves per-pixel surface/letter/prop occlusion. Painter
 // sorting by a quad's centre cannot do this correctly on a curved surface.
 function rasterTriangle(p,ps,indices,dark){
  const [a,b,c]=indices.map(i=>[ps[i][0]*2,ps[i][1]*2]),area=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);if(Math.abs(area)<.00001)return;
  const x0=Math.max(0,Math.floor(Math.min(a[0],b[0],c[0]))),x1=Math.min(1519,Math.ceil(Math.max(a[0],b[0],c[0]))),y0=Math.max(0,Math.floor(Math.min(a[1],b[1],c[1]))),y1=Math.min(799,Math.ceil(Math.max(a[1],b[1],c[1])));
  const texture=['body','eye','pupil','text','logo'].includes(p.material)?texels[p.material]:null,uv=p.uvs??[0,0,1,0,1,1,0,1];
  const inv=indices.map(i=>1/(stage.cameraZ-p.points[i][2])),tones=p.tones?.length===4?p.tones:Array(4).fill(p.tones?.[0]??(.3+.7*Math.max(0,p.normal[2])));
  for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
   const px=x+.5,py=y+.5,w0=((b[0]-px)*(c[1]-py)-(b[1]-py)*(c[0]-px))/area,w1=((c[0]-px)*(a[1]-py)-(c[1]-py)*(a[0]-px))/area,w2=1-w0-w1;
   if(w0<-.000001||w1<-.000001||w2<-.000001)continue;
   const iz=w0*inv[0]+w1*inv[1]+w2*inv[2],index=y*1520+x;if(iz<depth[index]-1e-10)continue;
   const k0=w0*inv[0]/iz,k1=w1*inv[1]/iz,k2=w2*inv[2]/iz,at=index*4;let r,g,bv,alpha=1;
   if(texture){const u=k0*uv[indices[0]*2]+k1*uv[indices[1]*2]+k2*uv[indices[2]*2],v=k0*uv[indices[0]*2+1]+k1*uv[indices[1]*2+1]+k2*uv[indices[2]*2+1],tx=Math.max(0,Math.min(texture.w-1,Math.floor(u*texture.w))),ty=Math.max(0,Math.min(texture.h-1,Math.floor(v*texture.h))),ti=(ty*texture.w+tx)*4;alpha=texture.data[ti+3]/255;if(alpha<.01)continue;r=texture.data[ti];g=texture.data[ti+1];bv=texture.data[ti+2];}
   else {r=g=bv=value(p.material,k0*tones[indices[0]]+k1*tones[indices[1]]+k2*tones[indices[2]],dark);}
   const oldAlpha=pixels.data[at+3]/255;if(oldAlpha===0)paintedPixels++;const combined=alpha+oldAlpha*(1-alpha);
   pixels.data[at]=(r*alpha+pixels.data[at]*oldAlpha*(1-alpha))/combined;pixels.data[at+1]=(g*alpha+pixels.data[at+1]*oldAlpha*(1-alpha))/combined;pixels.data[at+2]=(bv*alpha+pixels.data[at+2]*oldAlpha*(1-alpha))/combined;pixels.data[at+3]=combined*255;depth[index]=iz;
  }
 }
 function shadow(x,y,z,rx,ry,alpha,dark){const p=project([x+z*.20,y+z*.25,0]);ctx.save();ctx.translate(...p);ctx.scale(rx,ry);const g=ctx.createRadialGradient(0,0,.2,0,0,1);g.addColorStop(0,`rgba(0,0,0,${alpha*(dark?.9:1)})`);g.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=g;ctx.beginPath();ctx.arc(0,0,1,0,Math.PI*2);ctx.fill();ctx.restore();}
 return {draw(kind,time,w,h,config){
  const started=performance.now();const dark=config.dark,english=config.language==='en';if(kind!==currentKind||darkValue!==dark||englishValue!==english)setup(kind,dark,english);
  const frame=scene(kind,time);applyScene(rig,frame);const map=new Map(frame.patches.map(p=>[p.id,p]));
  const fit=Math.min(w/stage.width,h/stage.height);ctx.save();ctx.translate((w-stage.width*fit)/2,(h-stage.height*fit)/2);ctx.scale(fit,fit);
  const m=frame.meta;shadow(m.body[0],m.body[1]+(kind==='walk_study'?78:68),0,94,12,.25,dark);
  if(kind==='stamp_study'){shadow(m.card.x,m.card.y,m.card.z,100,70,.15,dark);shadow(m.stamp.x,m.stamp.y,m.stamp.z,44+m.stamp.z*.2,36+m.stamp.z*.2,.24/(1+m.stamp.z*.016),dark);}
  pixels.data.fill(0);depth.fill(0);paintedPixels=0;const wires=[];
  // Opaque surfaces first, then alpha textures with the same depth test.
  const slots=[...rig.drawOrder].sort((a,b)=>Number(['body','eye','pupil','text','logo'].includes(map.get(a.data.name).material))-Number(['body','eye','pupil','text','logo'].includes(map.get(b.data.name).material)));
  for(const slot of slots){if(slot.color.a===0)continue;const p=map.get(slot.data.name),a=slot.getAttachment(),v=new Float32Array(8);a.computeWorldVertices(slot,0,8,v,0,2);const ps=Array.from({length:4},(_,i)=>[v[i*2],v[i*2+1]]);
   rasterTriangle(p,ps,[0,1,2],dark);rasterTriangle(p,ps,[2,3,0],dark);
   if(config.debugMesh&&p.id.startsWith('bread_'))wires.push(ps);
  }
  rctx.putImageData(pixels,0,0);ctx.drawImage(raster,0,0,760,400);
  if(config.debugMesh)for(const ps of wires){polygon(ps);ctx.strokeStyle=dark?'rgba(70,220,220,.5)':'rgba(0,120,125,.4)';ctx.lineWidth=.65;ctx.stroke();}
  if(config.debugMesh){const pos=project([...m.contact,0]);ctx.strokeStyle='#eb7133';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(pos[0]-16,pos[1]);ctx.lineTo(pos[0]+16,pos[1]);ctx.moveTo(pos[0],pos[1]-16);ctx.lineTo(pos[0],pos[1]+16);ctx.stroke();ctx.fillStyle=dark?'#ccc':'#555';ctx.font='12px -apple-system';ctx.fillText(`${frame.time.toFixed(2)} s · ${m.phase}`,26,378);}
  ctx.restore();return {drawMilliseconds:performance.now()-started,paintedPixels,phase:m.phase,patches:frame.patches.length,visible:rig.slots.filter(s=>s.color.a>0).length,meta:m};
 },exportTextures:()=>textures,duration:kind=>studyDuration[kind]};
}
