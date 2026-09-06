import {readFile,writeFile,mkdir,rename,cp,rm} from 'node:fs/promises';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {compile,validate,recipeSchema} from './rig.mjs';
import {verifyRuntime} from './runtime.mjs';
import {previewRoot,workRoot} from './paths.mjs';
let queue=Promise.resolve();
const readJSON=async p=>JSON.parse(await readFile(p,'utf8'));
export async function current(){
  try{return await readJSON(resolve(workRoot,'current.json'));}catch(e){if(e.code!=='ENOENT')throw e;}
  return {revision:'baseline',recipe:await readJSON(resolve(previewRoot,'recipe.json')),json:await readJSON(resolve(previewRoot,'data/mascot.json'))};
}
async function withLock(fn){
  await mkdir(workRoot,{recursive:true});const lock=resolve(workRoot,'author.lock');
  for(let i=0;;i++){
    try{await mkdir(lock);break;}catch(e){if(e.code!=='EEXIST')throw e;if(i>=50)throw Error('Another authoring operation is busy; current version preserved');await new Promise(r=>setTimeout(r,100));}
  }
  try{return await fn();}finally{await rm(lock,{recursive:true});}
}
export function author(patch){
  const task=queue.then(()=>withLock(async()=>{
    const previous=await current(),recipe=recipeSchema.parse({...previous.recipe,...patch});
    const contour=await readJSON(resolve(previewRoot,'assets/contour.json'));
    const result=compile(contour,recipe),report=validate(result.json);if(!report.ok)throw Error(report.errors.join('; '));
    const runtime=await verifyRuntime(result.json),revision=randomUUID();
    const project={revision,recipe,json:result.json,report,runtime,debug:{points:result.mesh.points,weights:result.mesh.weights}};
    await mkdir(resolve(workRoot,'history'),{recursive:true});
    await writeFile(resolve(workRoot,'history',revision+'.json'),JSON.stringify(project));
    const tmp=resolve(workRoot,'current-'+revision+'.tmp');await writeFile(tmp,JSON.stringify(project));await rename(tmp,resolve(workRoot,'current.json'));
    return {revision,recipe,report,runtime};
  }));queue=task.catch(()=>{});return task;
}
export async function exportProject(name){
  if(!/^[a-z0-9][a-z0-9_-]{0,47}$/.test(name))throw Error('Use a short lowercase export name');
  const project=await current();const destination=resolve(workRoot,'exports',name+'-'+randomUUID().slice(0,8));
  const report=validate(project.json);if(!report.ok)throw Error(report.errors.join('; '));
  const runtime=await verifyRuntime(project.json);await mkdir(destination,{recursive:true});
  await writeFile(resolve(destination,'mascot.json'),JSON.stringify(project.json));
  await writeFile(resolve(destination,'recipe.json'),JSON.stringify(project.recipe,null,2));
  await writeFile(resolve(destination,'validation.json'),JSON.stringify({report,runtime,editorImport:'not verified'},null,2));
  await cp(resolve(previewRoot,'data/images'),resolve(destination,'images'),{recursive:true});
  return {destination,format:'Spine 4.2 JSON + atlas + images',editorImport:'not verified; no .spine generated'};
}
