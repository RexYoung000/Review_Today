import sharp from 'sharp';
import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {previewRoot,toolRoot} from './paths.mjs';
export async function prepareAssets(){
  const image=resolve(previewRoot,'assets/body-source.png');
  const {data,info}=await sharp(image).raw().toBuffer({resolveWithObject:true});
  // Read a conservative interior contour from the source; the bitmap is NOT edited.
  // RGB source has no alpha: triangles define the visible boundary, UVs never sample black.
  const inside=(x,y)=>{const i=(Math.round(y)*info.width+Math.round(x))*info.channels;return data[i+1]>30&&data[i+1]>data[i]*1.4;};
  const contour=[];
  for(let i=0;i<48;i++){
    const a=i/48*Math.PI*2;let radius=0;
    for(let r=0;r<610;r++){const x=629+Math.cos(a)*r,y=614-Math.sin(a)*r;if(x<0||y<0||x>=info.width||y>=info.height||!inside(x,y))break;radius=r;}
    radius=Math.max(0,radius-3);contour.push({x:Math.cos(a)*radius/999*280,y:Math.sin(a)*radius/999*280});
  }
  if(contour.some(p=>Math.hypot(p.x,p.y)<70))throw Error('Body contour extraction failed');
  await mkdir(resolve(previewRoot,'data/images'),{recursive:true});
  await copyFile(image,resolve(previewRoot,'data/images/body.png'));
  const svg=(inner,w,h)=>Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${inner}</svg>`);
  const entries=[
    ['book',svg('<path d="M4 10 Q60 0 126 16 Q190 0 248 10 L248 132 Q190 120 126 136 Q60 120 4 132Z" fill="#474747"/><path d="M12 16 Q65 8 122 22 L122 125 Q65 111 12 121Z" fill="#ededed"/><path d="M130 22 Q190 8 240 16 L240 121 Q190 111 130 125Z" fill="#fafafa"/><path d="M126 22V130" stroke="#8b8b8b" stroke-width="3"/>',252,144)],
    ['page',svg('<path d="M1 9 Q58 -1 111 8 L111 117 Q58 108 1 122Z" fill="#f3f3f3" stroke="#aaaaaa" stroke-width="1.5"/>',112,124)],
    ['eye',svg('<rect x="2" y="2" width="140" height="76" rx="38" fill="#fffefa"/>',144,80)],
    ['pupil',svg('<circle cx="24" cy="24" r="22" fill="#116360"/>',48,48)],
    ['fragment',svg('<defs><radialGradient id="ball" cx="32%" cy="25%" r="80%"><stop offset="0" stop-color="#d3eee4"/><stop offset=".46" stop-color="#9fd2c4"/><stop offset="1" stop-color="#70ad9f"/></radialGradient></defs><circle cx="72" cy="72" r="66" fill="url(#ball)"/>',144,144)],
    ['shadow',svg('<defs><radialGradient id="shade"><stop offset="0" stop-color="#020908" stop-opacity=".42"/><stop offset=".4" stop-color="#020908" stop-opacity=".22"/><stop offset="1" stop-color="#020908" stop-opacity="0"/></radialGradient></defs><ellipse cx="128" cy="64" rx="126" ry="62" fill="url(#shade)"/>',256,128)]
  ];
  for(const [name,input] of entries){await writeFile(resolve(previewRoot,`assets/${name}.svg`),input);await sharp(input).png().toFile(resolve(previewRoot,`data/images/${name}.png`));}
  // A multi-page atlas keeps editable source layers separate and avoids repacking them.
  let atlas='';
  for(const [name,w,h] of [['body',1254,1254],['eye',144,80],['pupil',48,48],['fragment',144,144],['shadow',256,128],['book',252,144],['page',112,124]])
    atlas+=`${name}.png\nsize: ${w},${h}\nfilter: Linear,Linear\npma: false\n${name}\n  bounds: 0,0,${w},${h}\n\n`;
  await writeFile(resolve(previewRoot,'data/images/mascot.atlas'),atlas.trimEnd()+'\n');
  await writeFile(resolve(previewRoot,'assets/contour.json'),JSON.stringify(contour));
  await mkdir(resolve(previewRoot,'vendor'),{recursive:true});
  await copyFile(resolve(toolRoot,'node_modules/@esotericsoftware/spine-canvas/dist/iife/spine-canvas.js'),resolve(previewRoot,'vendor/spine-canvas.js'));
  await copyFile(resolve(toolRoot,'node_modules/@esotericsoftware/spine-core/LICENSE'),resolve(previewRoot,'vendor/SPINE-LICENSE'));
  return contour;
}
