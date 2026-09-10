import {stage,scene,spineData,applyScene,studyDuration} from './settlement-scene.mjs';
import {seamlessRenderer} from '../../../brand/refresh-2026-09/motion-rig/mesh-renderer.mjs';
const materials=['body','eye','pupil','line','paper','stamp','puff','shadow','logo'];
export async function createStudyPlayer(spine,ctx,logoURL,platform={}){
 const logo=platform.loadImage?await platform.loadImage(logoURL):await (async()=>{const image=new Image();image.src=logoURL;await image.decode();return image;})();
 function canvas(w,h){if(platform.createCanvas)return platform.createCanvas(w,h);const c=document.createElement('canvas');c.width=w;c.height=h;return c;}
 const raster=canvas(1520,800),g=raster.getContext('2d'),Renderer=seamlessRenderer(spine.SkeletonRenderer),renderer=new Renderer(g);renderer.triangleRendering=true;
 let rig,currentKind,textures,darkValue;
 function makeTextures(dark){const map={};for(const material of materials){
  const [w,h]=material==='body'?[1254,1254]:material==='eye'?[144,80]:material==='pupil'?[48,48]:material==='stamp'?[144,180]:material==='shadow'?[256,48]:material==='puff'?[104,64]:[512,512];
  const c=canvas(w,h),g=c.getContext('2d');g.lineWidth=2;
  if(material==='body'){const original=platform.bodyTexture?.(dark);if(!original)throw new Error('Missing original Mr. B body material');g.drawImage(original,0,0,w,h);}
  else if(material==='logo'){g.fillStyle=dark?'#dddddd':'#323232';g.fillRect(0,0,w,h);g.globalCompositeOperation='destination-in';g.drawImage(logo,0,0,w,h);}
  else if(material==='eye'){g.fillStyle='#f7f7f7';g.beginPath();g.roundRect(2,2,140,76,38);g.fill();if(dark){g.strokeStyle='#777';g.stroke();}}
  else if(material==='pupil'){g.fillStyle='#232323';g.beginPath();g.arc(24,24,22,0,Math.PI*2);g.fill();}
  else if(material==='line'){g.fillStyle=dark?'#9b9b9b':'#b2b2b2';g.fillRect(0,0,w,h);}
  else if(material==='paper'){
   g.fillStyle=dark?'#343434':'#ffffff';g.strokeStyle=dark?'#555555':'#dedede';g.beginPath();g.roundRect(2,2,w-4,h-4,22);g.fill();g.stroke();
  }else if(material==='stamp'){
   // A book-like flat attachment: knob, stem and pad form one rigid silhouette.
   g.fillStyle=dark?'#c5c5c5':'#353535';g.beginPath();g.roundRect(46,3,52,51,16);g.fill();
   g.fillRect(61,43,22,74);g.beginPath();g.roundRect(7,108,130,61,15);g.fill();
   g.fillStyle=dark?'#777777':'#666666';g.fillRect(10,156,124,13);
   g.fillStyle=dark?'#454545':'#252525';g.beginPath();g.roundRect(13,169,118,10,4);g.fill();
  }else if(material==='shadow'){
   g.save();g.scale(w/2,h/2);g.translate(1,1);const gradient=g.createRadialGradient(0,0,0,0,0,1);gradient.addColorStop(0,'rgba(0,0,0,.28)');gradient.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=gradient;g.beginPath();g.arc(0,0,1,0,Math.PI*2);g.fill();g.restore();
  }else if(material==='puff'){
   g.fillStyle=dark?'#aaaaaa':'#cccccc';g.beginPath();g.ellipse(30,39,21,16,0,0,Math.PI*2);g.ellipse(52,28,24,22,0,0,Math.PI*2);g.ellipse(77,41,20,14,0,0,Math.PI*2);g.fill();
  }
  map[material]=c;
 }return map;}
 function setup(kind,dark,frame){textures=makeTextures(dark);darkValue=dark;currentKind=kind;
  const atlasText=materials.map(name=>`${name}.png\nsize: ${textures[name].width},${textures[name].height}\nfilter: Linear,Linear\n${name}\nbounds: 0,0,${textures[name].width},${textures[name].height}\n`).join('\n');
  const atlas=new spine.TextureAtlas(atlasText);for(const page of atlas.pages)page.setTexture(new spine.CanvasTexture(textures[page.name.replace('.png','')]));
  const data=new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(spineData(frame));rig=new spine.Skeleton(data);
 }
 return {draw(kind,time,w,h,config,providedFrame){
  const started=performance.now(),dark=config.dark,frame=providedFrame??scene(kind,time);if(kind!==currentKind||darkValue!==dark)setup(kind,dark,frame);
  applyScene(rig,frame);g.clearRect(0,0,1520,800);g.save();g.scale(2,2);renderer.draw(rig);
  if(config.debugMesh){const p=frame.patches.find(p=>p.id==='body');g.strokeStyle=dark?'rgba(70,220,220,.6)':'rgba(0,120,125,.5)';g.lineWidth=.55;
   for(let i=0;i<p.triangles.length;i+=3){g.beginPath();for(let j=0;j<3;j++){const [x,y]=p.points[p.triangles[i+j]];j?g.lineTo(x,y):g.moveTo(x,y);}g.closePath();g.stroke();}
   const [x,y]=frame.meta.contact;g.strokeStyle='#eb7133';g.lineWidth=1.5;g.beginPath();g.moveTo(x-14,y);g.lineTo(x+14,y);g.moveTo(x,y-14);g.lineTo(x,y+14);g.stroke();
   g.fillStyle=dark?'#ccc':'#555';g.font='12px -apple-system';g.fillText(`${frame.time.toFixed(2)} s · ${frame.meta.phase}`,26,378);
  }
  g.restore();const fit=Math.min(w/stage.width,h/stage.height);ctx.drawImage(raster,(w-stage.width*fit)/2,(h-stage.height*fit)/2,stage.width*fit,stage.height*fit);
  const pixels=g.getImageData(0,0,1520,800).data;let paintedPixels=0;for(let i=3;i<pixels.length;i+=4)if(pixels[i])paintedPixels++;
  return {kind:frame.kind,time:frame.time,drawMilliseconds:performance.now()-started,paintedPixels,phase:frame.meta.phase,patches:frame.patches.length,visible:rig.slots.filter(s=>s.color.a>0).length,meta:frame.meta};
 },exportTextures:()=>textures,duration:kind=>studyDuration[kind]};
}
