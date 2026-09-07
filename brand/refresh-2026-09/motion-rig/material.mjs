// Rendering-only material: atlas, geometry, UVs and source pixels are immutable.
const clamp=v=>Math.max(0,Math.min(1,v));
export function materialPalette(dark=false,override){
 const fallback={accent:dark?[238,238,238]:[38,38,38],wave:dark?[142,142,142]:[104,104,104]};
 const valid=a=>Array.isArray(a)&&a.length===3&&a.every(v=>Number.isFinite(v)&&v>=0&&v<=255);
 return {accent:valid(override?.accent)?override.accent:fallback.accent,wave:valid(override?.wave)?override.wave:fallback.wave};
}
export function materialPixel(name,r,g,b,active=false,palette=materialPalette(),x=.5,y=.5){
 const luminance=.2126*r+.7152*g+.0722*b;
 if(name==='body.png'){const v=Math.round(Math.max(0,Math.min(255,37-24*clamp((y-.18)/.62)-4*Math.pow((x-.5)/.42,2)+(luminance-70)*.35)));return [v,v,v];}
 if(name==='eye.png')return [247,247,247];
 if(name==='pupil.png')return [35,35,35];
 if(name==='shadow.png'){const v=Math.round(luminance);return [v,v,v];}
 if(name==='fragment.png'){
  const t=clamp((luminance-100)/145);
  if(active)return palette.accent.map(v=>Math.round(Math.min(255,v*(.78+.30*t))));
  const v=Math.round(100+140*t);return [v,v,v];
 }
 return [r,g,b];
}
export function createMaterials(images,makeCanvas){
 const cached=new Map();
 return function materialImages(style,dark,active=false,override){
  if(style!=='graphite')return undefined;
  const palette=materialPalette(dark,override),key=JSON.stringify(palette);
  if(!cached.has(key)){
   const neutral=new Map(),highlighted=new Map();
   for(const [name,image] of images){
    const render=active=>{
     const canvas=makeCanvas(image.width,image.height),ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
     const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),data=pixels.data;
     for(let i=0;i<data.length;i+=4){const rgb=materialPixel(name,data[i],data[i+1],data[i+2],active,palette,(i/4%canvas.width)/canvas.width,Math.floor(i/4/canvas.width)/canvas.height);data[i]=rgb[0];data[i+1]=rgb[1];data[i+2]=rgb[2];}
     ctx.putImageData(pixels,0,0);return canvas;
    };
    const base=render(false);neutral.set(image,base);highlighted.set(image,name==='fragment.png'?render(true):base);
   }
   cached.set(key,{neutral,highlighted});
  }
  return cached.get(key)[active?'highlighted':'neutral'];
 };
}
// Only the existing activity changes color. No extra clock or simulated audio.
export function waveColor(near,{material='current',dark=false,palette}={}){
 const t=clamp(near),p=materialPalette(dark,palette);
 const start=material==='graphite'?p.wave:(dark?[71,95,86]:[187,207,196]);
 const end=material==='graphite'?p.accent:(dark?[145,210,186]:[49,123,102]);
 return start.map((v,k)=>Math.round(v+(end[k]-v)*t));
}
