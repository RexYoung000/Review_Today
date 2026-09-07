import {seamlessRenderer} from './mesh-renderer.mjs';
import {createVoiceState,advanceVoice,applyVoice,drawVoiceScene,contactMoving} from './voice-scene.mjs';
const $=id=>document.getElementById(id),pref=matchMedia('(prefers-reduced-motion: reduce)'),MeshRenderer=seamlessRenderer(spine.SkeletonRenderer);
let mode='thinking',rig,raf=0,last=0,reduced=pref.matches,downloadURL;
const state=createVoiceState(),labels={listening:'正在聆听',thinking:'正在思考',speaking:'正在回答',idle:'已停止'};
$('reduce').checked=reduced;
function draw(canvas,compact=false){const box=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2),w=Math.round(box.width*d),h=Math.round(box.height*d);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}const ctx=canvas.getContext('2d');ctx.setTransform(d,0,0,d,0,0);const renderer=new MeshRenderer(ctx);renderer.triangleRendering=true;drawVoiceScene(ctx,renderer,rig,state,box.width,box.height,{compact,reduced,dark:document.body.classList.contains('dark')});}
function status(){const announcement=labels[mode]+(reduced?' · 减少动态效果':'');if($('modeStatus').textContent!==announcement)$('modeStatus').textContent=announcement;const label=(mode==='thinking'?({charge:'压低波面 · 准备起跳',flight:'腾空 · 看向落点',land:'落地挤压 · 波浪回弹'}[state.contact.phase]??'正在思考'):mode==='idle'&&contactMoving(state.contact)?'已停止 · 落稳并收住余波':labels[mode])+(reduced?' · 减少动态效果':Number($('volume').value)===0&&['listening','speaking'].includes(mode)?' · 等待声音':'');$('phase').textContent=label;$('hero').setAttribute('aria-label',label+'，语音角色与波浪预览');}
function frame(now){raf=0;if(!rig||document.hidden)return;const dt=Math.min(.05,(now-(last||now))/1000);last=now;advanceVoice(state,dt,mode,Number($('volume').value)/100,reduced);applyVoice(spine,rig,state,reduced);draw($('hero'));draw($('compact'),true);status();if(!reduced&&(contactMoving(state.contact)||mode==='thinking'||(['listening','speaking'].includes(mode)&&Number($('volume').value)>0)||state.level>0||state.think>0||(mode==='idle'&&(state.listen>0||state.speak>0))))raf=requestAnimationFrame(frame);else last=0;}
function wake(){if(!raf&&rig&&!document.hidden){last=0;raf=requestAnimationFrame(frame);}}
for(const button of document.querySelectorAll('[data-mode]'))button.addEventListener('click',()=>{mode=button.dataset.mode;for(const b of document.querySelectorAll('[data-mode]'))b.setAttribute('aria-pressed',String(b===button));status();wake();});
$('volume').addEventListener('input',()=>{$('volumeValue').textContent=$('volume').value+'%';status();wake();});
function setReduced(value){reduced=value;$('reduce').checked=value;status();wake();}
$('reduce').addEventListener('change',e=>setReduced(e.target.checked));pref.addEventListener('change',e=>setReduced(e.matches));
$('theme').addEventListener('click',()=>{const dark=document.body.classList.toggle('dark');$('theme').textContent=dark?'浅色':'深色';$('theme').setAttribute('aria-pressed',String(dark));wake();});
new ResizeObserver(wake).observe(document.querySelector('.workspace'));
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(raf);raf=0;last=0;}else wake();});
async function json(url){const r=await fetch(url);if(!r.ok)throw Error(`${url}: ${r.status}`);return r.json();}
(async()=>{try{const atlas=new spine.TextureAtlas(await(await fetch('data/images/mascot.atlas')).text());await Promise.all(atlas.pages.map(async page=>{const image=new Image();image.src='data/images/'+page.name;await image.decode();page.setTexture(new spine.CanvasTexture(image));}));
  let source=await json('data/mascot.json');try{const p=await json('/api/project');if(p.json.animations.speaking)source=p.json;}catch{}
  const data=new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(source);rig={data,skeleton:new spine.Skeleton(data)};downloadURL=URL.createObjectURL(new Blob([JSON.stringify(source)],{type:'application/json'}));$('download').href=downloadURL;
  for(const b of document.querySelectorAll('[data-mode]'))b.disabled=false;$('health').textContent='本轮试作：思考跳跃 → 落地 → 停止';wake();
}catch(e){$('health').textContent='加载失败：'+e.message;}})();
