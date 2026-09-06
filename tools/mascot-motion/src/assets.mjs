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
    ['eye',svg('<rect x="2" y="2" width="140" height="76" rx="38" fill="#fffefa"/>',144,80)],
    ['pupil',svg('<circle cx="24" cy="24" r="22" fill="#116360"/>',48,48)],
    ['fragment',svg('<ellipse cx="72" cy="60" rx="68" ry="56" fill="#146d69"/>',144,120)]
  ];
  for(const [name,input] of entries){await writeFile(resolve(previewRoot,`assets/${name}.svg`),input);await sharp(input).png().toFile(resolve(previewRoot,`data/images/${name}.png`));}
  // A multi-page atlas keeps editable source layers separate and avoids repacking them.
  let atlas='';
  for(const [name,w,h] of [['body',1254,1254],['eye',144,80],['pupil',48,48],['fragment',144,120]])
    atlas+=`${name}.png\nsize: ${w},${h}\nfilter: Linear,Linear\npma: false\n${name}\n  bounds: 0,0,${w},${h}\n\n`;
  await writeFile(resolve(previewRoot,'data/images/mascot.atlas'),atlas.trimEnd()+'\n');
  await writeFile(resolve(previewRoot,'assets/contour.json'),JSON.stringify(contour));
  await mkdir(resolve(previewRoot,'vendor'),{recursive:true});
  await copyFile(resolve(toolRoot,'node_modules/@esotericsoftware/spine-canvas/dist/iife/spine-canvas.js'),resolve(previewRoot,'vendor/spine-canvas.js'));
  await copyFile(resolve(toolRoot,'node_modules/@esotericsoftware/spine-core/LICENSE'),resolve(previewRoot,'vendor/SPINE-LICENSE'));
  return contour;
}
