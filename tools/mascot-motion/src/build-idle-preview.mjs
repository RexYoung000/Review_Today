import {nativeHTML} from './build-native.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {root} from './paths.mjs';
const folder=resolve(root,'output/idle-web');await mkdir(folder,{recursive:true});
let html=await nativeHTML();
html=html.replace('<canvas aria-hidden="true"></canvas>',`<header><strong>Review Today · 待机动作</strong><select id="clip" aria-label="动作"><option value="random">随机轮播</option><option value="idle_look">左右看看</option><option value="idle_hop">弹跳</option><option value="idle_stretch">眨眼伸展</option><option value="idle_book">翻看本子</option></select><button id="restart">重新开始</button><label><input type="checkbox" id="dark">深色</label><label><input type="checkbox" id="slow">半速</label><label><input type="checkbox" id="reduced">减少动态效果</label><label><input type="checkbox" id="small">App 尺寸</label></header><main><canvas aria-hidden="true"></canvas></main><footer id="status" role="status"></footer>`);
html+=`<style>body{background:#f6f6f6;color:#222;font:14px system-ui;display:flex;flex-direction:column}body.dark{background:#131313;color:#eee}header{padding:20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}button,select{font:inherit;color:inherit;background:transparent;border:1px solid #888;border-radius:8px;padding:7px}input{accent-color:#777}label{white-space:nowrap}main{flex:1;min-height:200px;display:grid;place-items:center}canvas{width:min(640px,100%);height:480px;max-height:100%}body.small canvas{width:150px;height:170px}footer{text-align:center;padding:20px;color:#888;min-height:22px}:focus-visible{outline:2px solid currentColor;outline-offset:3px}</style><script>
const el=id=>document.getElementById(id),names={idle_look:'左右看看',idle_hop:'弹跳',idle_stretch:'眨眼伸展',idle_book:'翻看本子'};let token=0;
function update(){document.body.classList.toggle('dark',el('dark').checked);document.body.classList.toggle('small',el('small').checked);window.mascotMotion?.setState({surface:'recall',mode:'idle',ambient:true,idleClip:el('clip').value,restartToken:token,material:'graphite',dark:el('dark').checked,reduced:el('reduced').checked,rate:el('slow').checked?.5:1,visible:!document.hidden});}
for(const input of document.querySelectorAll('input,select'))input.addEventListener('change',update);el('restart').onclick=()=>{token++;update();};document.addEventListener('visibilitychange',update);
const ready=setInterval(()=>{if(window.mascotMotion){clearInterval(ready);update();}},50);
setInterval(()=>{const s=window.mascotMotion?.inspect().idle;if(s)el('status').textContent=el('reduced').checked?'减少动态效果 · 静态姿态':s.phase==='play'?names[s.clip]+' · 剩余 '+s.remaining.toFixed(1)+' 秒':s.phase==='done'?'本段结束 · 可重新开始':'待机停顿 · '+s.remaining.toFixed(1)+' 秒后选择下一段';},100);
</script>`;
await writeFile(resolve(folder,'index.html'),html);console.log(folder);
