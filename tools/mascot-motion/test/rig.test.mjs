import test from 'node:test';import assert from 'node:assert/strict';import {readFile,mkdtemp} from 'node:fs/promises';import {resolve} from 'node:path';import {tmpdir} from 'node:os';
import {compile,defaults,validate} from '../src/rig.mjs';
import {loadRig,sample,verticesOf,verifyRuntime} from '../src/runtime.mjs';
import {previewRoot,toolRoot} from '../src/paths.mjs';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
const contour=JSON.parse(await readFile(resolve(previewRoot,'assets/contour.json'),'utf8'));
test('official parser loads weighted deformation; all sampled triangles remain positive and loop closes',async()=>{
 const {json}=compile(contour,defaults);assert.equal(validate(json).ok,true);const report=await verifyRuntime(json);assert.equal(report.endpointError,0);assert.ok(report.minTriangleArea>0);
 const rig=await loadRig(json);const start=Array.from(verticesOf(sample(rig,0)));const middle=Array.from(verticesOf(sample(rig,1.6)));assert.ok(middle.some((x,i)=>Math.abs(x-start[i])>2));
 // Disable only FFD: compare actual runtime geometry to prove deform track was parsed.
 const bonesOnly=structuredClone(json);delete bonesOnly.animations.recall.attachments;
 const other=await loadRig(bonesOnly);const noFFD=verticesOf(sample(other,1.6));assert.ok(middle.some((x,i)=>Math.abs(x-noFFD[i])>1));
});
test('eye leads body and pupils move within independent eye coordinates',async()=>{
 const rig=await loadRig(compile(contour,defaults).json);sample(rig,.45);const p=rig.skeleton.findBone('pupil_left');assert.ok(p.x<0);assert.ok(Math.abs(rig.skeleton.findBone('crown').rotation)<.15);assert.equal(rig.skeleton.findSlot('fragment').color.a,0);
});
test('weight corruption, malformed frames and unsafe parameter budgets are rejected',()=>{
 const {json}=compile(contour,defaults);json.skins[0].attachments.body.body.vertices[4]=3;assert.equal(validate(json).ok,false);
 assert.throws(()=>compile(contour,{...defaults,duration:999}));assert.throws(()=>compile(contour,{...defaults,softness:NaN}));
 const broken=compile(contour,defaults).json;broken.animations.recall.attachments.default.body.body.deform[4].vertices.pop();assert.equal(validate(broken).ok,false);
});
test('zero motion remains valid; excessive combined deformation is detected before saving',async()=>{
 assert.ok((await verifyRuntime(compile(contour,{...defaults,strength:0,gaze:0}).json)).minTriangleArea>0);
 await assert.rejects(verifyRuntime(compile(contour,{...defaults,strength:1.5,bend:18,wave:12,softness:35}).json),/folded/);
});
test('MCP handshake, tools, versioned edits, image response, export and rejection work through stdio',async()=>{
 const work=await mkdtemp(resolve(tmpdir(),'mascot-mcp-test-'));
 const client=new Client({name:'mascot-integration-test',version:'1.0.0'});
 const transport=new StdioClientTransport({command:process.execPath,args:[resolve(toolRoot,'src/mcp.mjs')],env:{...process.env,MASCOT_WORK_DIR:work},stderr:'pipe'});
 await client.connect(transport);
 try{
  const tools=await client.listTools();assert.equal(tools.tools.length,7);
  const inspect=await client.callTool({name:'rig_inspect',arguments:{}});assert.ok(JSON.parse(inspect.content[0].text).validation.ok);
  const changed=await client.callTool({name:'motion_author',arguments:{gaze:.65,wave:6}});assert.ok(!changed.isError);assert.equal(JSON.parse(changed.content[0].text).recipe.gaze,.65);
  const bound=await client.callTool({name:'weights_bind',arguments:{softness:70}});assert.ok(!bound.isError);
  const image=await client.callTool({name:'preview_frame',arguments:{time:1.7,size:320,dark:true}});assert.equal(image.content[0].type,'image');assert.ok(Buffer.from(image.content[0].data,'base64').subarray(1,4).equals(Buffer.from('PNG')));
  const exported=await client.callTool({name:'motion_export',arguments:{name:'test'}});assert.ok(!exported.isError);const dest=JSON.parse(exported.content[0].text).destination;assert.ok(dest.startsWith(work));assert.ok(JSON.parse(await readFile(resolve(dest,'validation.json'),'utf8')).report.ok);
  const bad=await client.callTool({name:'motion_author',arguments:{strength:100}});assert.ok(bad.isError);
  const folded=await client.callTool({name:'motion_author',arguments:{strength:1.5,bend:18,wave:12,softness:35}});assert.ok(folded.isError);
  const state=JSON.parse((await client.callTool({name:'rig_inspect',arguments:{}})).content[0].text);assert.equal(state.recipe.strength,1);assert.equal(state.recipe.gaze,.65);
 }finally{await client.close();}
});
