import {createServer} from 'node:http';
import {readFile,realpath} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import {previewRoot} from './paths.mjs';
import {current,author} from './project.mjs';
import {recipeSchema} from './rig.mjs';
const port=Number(process.env.MASCOT_PORT??8769);
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.png':'image/png','.svg':'image/svg+xml','.gif':'image/gif','.mp4':'video/mp4'};
const server=createServer(async(req,res)=>{
  const hosts=[`127.0.0.1:${port}`,`localhost:${port}`];
  if(!hosts.includes(req.headers.host)){res.writeHead(403);res.end('Local host required');return;}
  const reply=(status,data)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
  try{
    const url=new URL(req.url,`http://${req.headers.host}`);
    if(req.method==='GET'&&url.pathname==='/api/status'){const p=await current();return reply(200,{revision:p.revision});}
    if(req.method==='GET'&&url.pathname==='/api/project')return reply(200,await current());
    if(req.method==='POST'&&url.pathname==='/api/author'){
      if(req.headers.origin!==`http://${req.headers.host}`||req.headers['content-type']!=='application/json')return reply(403,{error:'Same-origin JSON required'});
      let body='',size=0;for await(const chunk of req){size+=chunk.length;if(size>4096)return reply(413,{error:'Request too large'});body+=chunk;}
      return reply(200,await author(recipeSchema.partial().parse(JSON.parse(body))));
    }
    if(req.method!=='GET'&&req.method!=='HEAD')return reply(405,{error:'Method not allowed'});
    const relative=decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname);
    const target=await realpath(resolve(previewRoot,'.'+relative));
    if(!target.startsWith(previewRoot+sep))return reply(403,{error:'Outside preview root'});
    const content=await readFile(target);res.writeHead(200,{'Content-Type':types[extname(target)]??'text/plain','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(req.method==='HEAD'?undefined:content);
  }catch(e){reply(e.code==='ENOENT'?404:400,{error:e.message});}
});
server.listen(port,'127.0.0.1',()=>console.log(`Mascot preview: http://127.0.0.1:${port}/`));
