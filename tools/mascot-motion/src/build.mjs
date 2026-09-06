import {writeFile,readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {compile,defaults,validate} from './rig.mjs';
import {prepareAssets} from './assets.mjs';
import {previewRoot} from './paths.mjs';
import {verifyRuntime} from './runtime.mjs';
export async function build(){
  const contour=await prepareAssets();
  let recipe=defaults;try{recipe=JSON.parse(await readFile(resolve(previewRoot,'recipe.json'),'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
  const result=compile(contour,recipe),report=validate(result.json);
  if(!report.ok)throw Error(JSON.stringify(report));
  const runtime=await verifyRuntime(result.json);
  await writeFile(resolve(previewRoot,'data/mascot.json'),JSON.stringify(result.json));
  await writeFile(resolve(previewRoot,'recipe.json'),JSON.stringify(recipe,null,2)+'\n');
  await writeFile(resolve(previewRoot,'data/rig-debug.json'),JSON.stringify({points:result.mesh.points,weights:result.mesh.weights}));
  await writeFile(resolve(previewRoot,'data/validation.json'),JSON.stringify({...report,runtime},null,2)+'\n');
  return report;
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))console.log(await build());
