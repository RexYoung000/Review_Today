import sharp from 'sharp';
import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {previewRoot,toolRoot,root} from './paths.mjs';
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
  const logo=await sharp(resolve(root,'brand/refresh-2026-09/masters/mark-alpha.png')).ensureAlpha().raw().toBuffer({resolveWithObject:true});
  for(let i=0;i<logo.data.length;i+=4)logo.data[i]=logo.data[i+1]=logo.data[i+2]=239;
  const flatLogo=await sharp(logo.data,{raw:logo.info}).trim().resize(84,84,{fit:'inside'}).png().toBuffer();
  const entries=[
    ['book',svg(`<rect x="1" y="1" width="158" height="222" rx="8" fill="#797979" stroke="#b0b0b0" stroke-width="2"/><path d="M9 8V216" stroke="#5b5b5b" stroke-width="3"/><image href="data:image/png;base64,${flatLogo.toString('base64')}" x="38" y="70" width="84" height="84"/>`,160,224)],
    ['book-back',svg('<rect x="1" y="1" width="158" height="222" rx="8" fill="#666666" stroke="#9e9e9e" stroke-width="2"/>',160,224)],
    ['book-spine',svg('<rect width="24" height="224" rx="6" fill="#505050"/><path d="M5 5V219M20 5V219" stroke="#8c8c8c" stroke-width="2"/>',24,224)],
    ['page',svg('<rect width="160" height="224" rx="3" fill="#ededed"/><path d="M4 219H156M4 211H156" stroke="#b3b3b3" stroke-width="2"/>',160,224)],
    ['eye',svg('<rect x="2" y="2" width="140" height="76" rx="38" fill="#fffefa"/>',144,80)],
    ['pupil',svg('<circle cx="24" cy="24" r="22" fill="#116360"/>',48,48)],
    ['fragment',svg('<defs><radialGradient id="ball" cx="32%" cy="25%" r="80%"><stop offset="0" stop-color="#d3eee4"/><stop offset=".46" stop-color="#9fd2c4"/><stop offset="1" stop-color="#70ad9f"/></radialGradient></defs><circle cx="72" cy="72" r="66" fill="url(#ball)"/>',144,144)],
    ['shadow',svg('<defs><radialGradient id="shade"><stop offset="0" stop-color="#020908" stop-opacity=".42"/><stop offset=".4" stop-color="#020908" stop-opacity=".22"/><stop offset="1" stop-color="#020908" stop-opacity="0"/></radialGradient></defs><ellipse cx="128" cy="64" rx="126" ry="62" fill="url(#shade)"/>',256,128)]
  ];
  for(const [name,input] of entries){await writeFile(resolve(previewRoot,`assets/${name}.svg`),input);await sharp(input).png().toFile(resolve(previewRoot,`data/images/${name}.png`));}
  // A multi-page atlas keeps editable source layers separate and avoids repacking them.
  let atlas='';
  for(const [name,w,h] of [['body',1254,1254],['eye',144,80],['pupil',48,48],['fragment',144,144],['shadow',256,128],['book',160,224],['book-back',160,224],['book-spine',24,224],['page',160,224]])
    atlas+=`${name}.png\nsize: ${w},${h}\nfilter: Linear,Linear\npma: false\n${name}\n  bounds: 0,0,${w},${h}\n\n`;
  await writeFile(resolve(previewRoot,'data/images/mascot.atlas'),atlas.trimEnd()+'\n');
  await writeFile(resolve(previewRoot,'assets/contour.json'),JSON.stringify(contour));
  await mkdir(resolve(previewRoot,'vendor'),{recursive:true});
  await copyFile(resolve(toolRoot,'node_modules/@esotericsoftware/spine-canvas/dist/iife/spine-canvas.js'),resolve(previewRoot,'vendor/spine-canvas.js'));
  await copyFile(resolve(toolRoot,'node_modules/@esotericsoftware/spine-core/LICENSE'),resolve(previewRoot,'vendor/SPINE-LICENSE'));
  return contour;
}
