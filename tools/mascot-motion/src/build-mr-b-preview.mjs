import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {root,toolRoot,previewRoot} from './paths.mjs';
import {addMrBRig} from './mr-b-rig.mjs';
const imports={};
for(const name of ['material.mjs','mesh-renderer.mjs','return-state.mjs']){
 let source=await readFile(resolve(previewRoot,name),'utf8');
 source=source.replace(/(['"])\.\/([\w-]+\.mjs)\1/g,(_,q,file)=>`${q}@review-motion/${file}${q}`);
 imports['@review-motion/'+name]='data:text/javascript;base64,'+Buffer.from(source).toString('base64');
}
const character=(await readFile(resolve(toolRoot,'src/settlement-character.mjs'),'utf8')).replace(/import contour .*?;\n/, 'const contour='+await readFile(resolve(previewRoot,'assets/contour.json'),'utf8')+';\n');
imports['@review-motion/settlement-character.mjs']='data:text/javascript;base64,'+Buffer.from(character).toString('base64');
for(const name of ['settlement-scene.mjs','settlement-player.mjs','settlement-flow.mjs']) imports['@review-motion/'+name]='data:text/javascript;base64,'+Buffer.from((await readFile(resolve(toolRoot,'src',name),'utf8')).replaceAll("'./settlement-scene.mjs'","'@review-motion/settlement-scene.mjs'").replaceAll("'./settlement-character.mjs'","'@review-motion/settlement-character.mjs'").replaceAll("'../../../brand/refresh-2026-09/motion-rig/mesh-renderer.mjs'","'@review-motion/mesh-renderer.mjs'")).toString('base64');
const logo='data:image/png;base64,'+(await readFile(resolve(root,'brand/refresh-2026-09/masters/mark-alpha.png'))).toString('base64');
imports['@review-motion/mr-b-state.mjs']='data:text/javascript;base64,'+Buffer.from(await readFile(resolve(toolRoot,'src/mr-b-state.mjs'),'utf8')).toString('base64');
const json=addMrBRig(JSON.parse(await readFile(resolve(previewRoot,'data/mascot.json'),'utf8')));
const atlas=await readFile(resolve(previewRoot,'data/images/mascot.atlas'),'utf8'),images={};
for(const name of ['body.png','eye.png','pupil.png','fragment.png','shadow.png','book.png','book-back.png','book-spine.png','page.png'])images[name]='data:image/png;base64,'+(await readFile(resolve(previewRoot,'data/images',name))).toString('base64');
const runtime=await readFile(resolve(toolRoot,'node_modules/@esotericsoftware/spine-canvas/dist/iife/spine-canvas.min.js'),'utf8');
const entry=await readFile(resolve(toolRoot,'src/mr-b-player.mjs'),'utf8');
const safe=x=>x.replace(/<\/script/gi,'<\\/script');
const html=`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' data:; img-src data:; style-src 'unsafe-inline'; connect-src 'none'"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}canvas{width:100%;height:100%;display:block}</style><canvas></canvas><script type="importmap">${JSON.stringify({imports})}</script><script id="study-logo" type="application/json">${JSON.stringify(logo)}</script><script id="rig-data" type="application/json">${safe(JSON.stringify({json,atlas,images}))}</script><script>${safe(runtime)}</script><script type="module">${safe(entry)}</script>`;
const folder=resolve(root,'output/mr-b-preview');await mkdir(folder,{recursive:true});
await writeFile(resolve(folder,'MrBMotion.html'),html);
await writeFile(resolve(folder,'mr-b.spine.json'),JSON.stringify(json));
console.log('Isolated Mr. B resource:',html.length,'bytes');
