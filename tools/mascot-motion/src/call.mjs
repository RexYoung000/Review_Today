// CLI adapter for agents whose host cannot dynamically register a new MCP server.
// Every action still goes through the real MCP stdio transport and tool schemas.
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {mkdir,writeFile} from 'node:fs/promises';import {resolve} from 'node:path';import {randomUUID} from 'node:crypto';
import {toolRoot,workRoot} from './paths.mjs';
const name=process.argv[2]??'rig_inspect',args=JSON.parse(process.argv[3]??'{}');
const client=new Client({name:'review-today-motion-cli',version:'0.1.0'});
try{
 await client.connect(new StdioClientTransport({command:process.execPath,args:[resolve(toolRoot,'src/mcp.mjs')],env:{...(process.env.MASCOT_WORK_DIR?{MASCOT_WORK_DIR:process.env.MASCOT_WORK_DIR}:{}),...(process.env.MASCOT_PORT?{MASCOT_PORT:process.env.MASCOT_PORT}:{})},stderr:'pipe'}));
 const result=await client.callTool({name,arguments:args});
 if(result.isError)process.exitCode=1;
 for(const block of result.content??[]){
  if(block.type==='image'){const dir=resolve(workRoot,'renders');await mkdir(dir,{recursive:true});const destination=resolve(dir,'frame-'+randomUUID()+'.png');await writeFile(destination,Buffer.from(block.data,'base64'));console.log(JSON.stringify({destination,mimeType:block.mimeType}));}
  else if(block.type==='text')console.log(block.text);
 }
}catch(e){process.exitCode=1;console.error(e.message);}finally{await client.close();}
