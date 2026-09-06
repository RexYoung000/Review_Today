import test from 'node:test';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';import {mkdtemp,readFile} from 'node:fs/promises';import {resolve} from 'node:path';import {tmpdir} from 'node:os';import {toolRoot} from '../src/paths.mjs';
test('local preview rejects cross-origin mutation, traversal and malformed edits without changing revision',async()=>{
 const dir=await mkdtemp(resolve(tmpdir(),'mascot-http-test-')),port=19869,url=`http://127.0.0.1:${port}`;
 const child=spawn(process.execPath,[resolve(toolRoot,'src/serve.mjs')],{env:{...process.env,MASCOT_WORK_DIR:dir,MASCOT_PORT:String(port)},stdio:['ignore','pipe','pipe']});
 await new Promise((resolve,reject)=>{child.once('error',reject);child.stdout.once('data',resolve);child.once('exit',code=>reject(Error('Preview exited '+code)));});
 try{
  assert.equal((await fetch(url)).status,200);const before=await(await fetch(url+'/api/status')).json();
  assert.equal((await fetch(url+'/api/author',{method:'POST',headers:{Origin:'https://example.com','Content-Type':'application/json'},body:'{"gaze":0}'})).status,403);
  assert.equal((await fetch(url+'/..%2f..%2f..%2fDESIGN.md')).status,403);
  assert.equal((await fetch(url+'/api/author',{method:'POST',headers:{Origin:url,'Content-Type':'application/json'},body:'{'})).status,400);
  assert.deepEqual(await(await fetch(url+'/api/status')).json(),before);
  const ok=await fetch(url+'/api/author',{method:'POST',headers:{Origin:url,'Content-Type':'application/json'},body:'{"gaze":0.5}'});assert.equal(ok.status,200);const result=await ok.json();assert.equal(result.recipe.gaze,.5);assert.ok(result.runtime.sampledFrames>135);
 }finally{child.kill();}
});
test('simultaneous MCP clients preserve each other’s distinct parameter updates',async()=>{
 const dir=await mkdtemp(resolve(tmpdir(),'mascot-concurrent-'));
 const invoke=args=>new Promise((resolve,reject)=>{const child=spawn(process.execPath,[toolRoot+'/src/call.mjs','motion_author',JSON.stringify(args)],{env:{...process.env,MASCOT_WORK_DIR:dir},stdio:['ignore','pipe','pipe']});let error='';child.stderr.on('data',b=>error+=b);child.stdout.resume();child.on('error',reject);child.on('close',code=>code===0?resolve():reject(Error(error)));});
 await Promise.all([invoke({gaze:.6}),invoke({wave:6})]);const p=JSON.parse(await readFile(resolve(dir,'current.json'),'utf8'));assert.equal(p.recipe.gaze,.6);assert.equal(p.recipe.wave,6);
});
