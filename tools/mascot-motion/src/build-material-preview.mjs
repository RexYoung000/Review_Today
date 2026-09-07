import {nativeHTML} from './build-native.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {root} from './paths.mjs';
const folder=resolve(root,'output/material-web');await mkdir(folder,{recursive:true});
let html=await nativeHTML();
html=html.replace('<canvas aria-hidden="true"></canvas>',`<div id="controls"><strong>黑白材质 · 灰白小球</strong><label><input id="graphite" type="checkbox" checked>试作版</label><label><input id="dark" type="checkbox">深色</label><label><input id="reduced" type="checkbox">减少动态</label><label><input id="slow" type="checkbox">半速</label><select id="surface"><option value="recall">思考环绕</option><option value="voice">语音</option></select><select id="mode"><option value="idle">停止</option><option value="thinking">思考</option><option value="listening">聆听</option><option value="speaking">回答</option></select><input id="level" type="range" min="0" max="1" step=".01" value=".65" aria-label="模拟声量"><span id="status">方向暂留 · 细节后续调整</span></div><canvas aria-hidden="true"></canvas>`);
html+=`<style>body{background:#f6f6f6;color:#252525;font:14px system-ui}body.dark{background:#131313;color:#eee}#controls{padding:20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}canvas{height:calc(100% - 130px);min-height:220px}select{padding:5px;color:inherit;background:inherit}input:focus-visible,select:focus-visible{outline:2px solid currentColor;outline-offset:2px}label{white-space:nowrap}input,select{accent-color:#262626}body.dark input{accent-color:#eee}#status{font-size:12px}</style><script>
const el=id=>document.getElementById(id);function update(){document.body.classList.toggle('dark',el('dark').checked);window.mascotMotion?.setState({surface:el('surface').value,mode:el('mode').value,level:+el('level').value,material:el('graphite').checked?'graphite':'current',dark:el('dark').checked,reduced:el('reduced').checked,rate:el('slow').checked?.5:1,visible:!document.hidden});}
for(const element of document.querySelectorAll('input,select'))element.addEventListener('input',update);document.addEventListener('visibilitychange',update);const ready=setInterval(()=>{if(window.mascotMotion){clearInterval(ready);update();}},50);
</script>`;
await writeFile(resolve(folder,'index.html'),html);console.log(folder);
