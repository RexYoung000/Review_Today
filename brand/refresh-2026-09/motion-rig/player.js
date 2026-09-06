import {seamlessRenderer} from './mesh-renderer.mjs';
const MeshRenderer=seamlessRenderer(spine.SkeletonRenderer);
const $=id=>document.getElementById(id),motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
let rig,atlas,debug,recipe,revision='baseline',duration=5.6,time=0,playing=false,returning=false,returnState,returnElapsed=0,raf=0,last=0,assetReady=false;
let reduced=motionPreference.matches,downloadURL;
$('reduce').checked=reduced;
const status=message=>$('editStatus').textContent=message;
async function getJSON(url){const r=await fetch(url);if(!r.ok)throw Error(`${url}: ${r.status}`);return r.json();}
function createRig(json){const data=new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(json);return {data,skeleton:new spine.Skeleton(data)};}
function setData(json,meta){rig=createRig(json);duration=rig.data.findAnimation('recall').duration;recipe=meta.recipe;revision=meta.revision??'baseline';if(meta.debug)debug=meta.debug;time=Math.min(time,duration);$('timeline').max=duration;
  if(recipe){for(const key of ['strength','gaze']){$(key).value=recipe[key];$(key+'Value').textContent=Math.round(recipe[key]*100)+'%';}}
  if(downloadURL)URL.revokeObjectURL(downloadURL);downloadURL=URL.createObjectURL(new Blob([JSON.stringify(json)],{type:'application/json'}));$('download').href=downloadURL;
}
function pose(){const s=rig.skeleton;s.setToSetupPose();if(!reduced&&returning){returnState.apply(s);}else if(!reduced){rig.data.findAnimation('recall').apply(s,0,time,false,[],1,spine.MixBlend.replace,spine.MixDirection.mixIn);}s.updateWorldTransform(spine.Physics.none);}
function draw(canvas,small=0){const box=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2),w=Math.round(box.width*d),h=Math.round(box.height*d);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}const ctx=canvas.getContext('2d');ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,box.width,box.height);const scale=small?small/410:Math.min(box.width/465,box.height/360);
  ctx.save();ctx.translate(box.width/2,box.height*.52);ctx.scale(scale,-scale);const renderer=new MeshRenderer(ctx);renderer.triangleRendering=true;renderer.draw(rig.skeleton);
  if(!small&&($('mesh').checked||$('weights').checked)){
    const slot=rig.skeleton.findSlot('body'),a=slot.getAttachment(),v=new Float32Array(a.worldVerticesLength);a.computeWorldVertices(slot,0,v.length,v,0,2);
    for(let i=0;i<a.triangles.length;i+=3){const ids=a.triangles.slice(i,i+3);ctx.beginPath();ids.forEach((n,j)=>j?ctx.lineTo(v[n*2],v[n*2+1]):ctx.moveTo(v[n*2],v[n*2+1]));ctx.closePath();
      if($('weights').checked&&debug){const ws=[0,1,2].map(k=>ids.reduce((sum,n)=>sum+debug.weights[n][k],0)/3);const colors=[[229,143,106],[140,182,117],[143,170,221]];const rgb=[0,1,2].map(k=>Math.round(ws.reduce((sum,x,j)=>sum+x*colors[j][k],0)));ctx.fillStyle=`rgba(${rgb.join(',')},.72)`;ctx.fill();}
      if($('mesh').checked){ctx.lineWidth=.65/scale;ctx.strokeStyle='rgba(255,254,250,.45)';ctx.stroke();}
    }
    if($('mesh').checked)for(const b of rig.skeleton.bones.slice(2,5)){ctx.beginPath();ctx.arc(b.worldX,b.worldY,3.5/scale,0,Math.PI*2);ctx.fillStyle='#fffefa';ctx.fill();ctx.beginPath();ctx.moveTo(b.worldX,b.worldY);ctx.lineTo(b.worldX+b.a*19,b.worldY+b.c*19);ctx.strokeStyle='#e4b57c';ctx.lineWidth=2/scale;ctx.stroke();}
  }ctx.restore();
}
function phase(){if(reduced)return '减少动态效果 · 静止';if(returning)return '正在收拢';if(time===0)return '准备好了';const u=time/duration;return u<.14?'眼睛先瞟动':u<.29?'身体跟随 · 局部弯曲':u<.75?'分出一个念头':u<.9?'收拢 · 回弹':'回到原处';}
function paint(){if(!assetReady)return;pose();draw($('hero'));for(const size of [18,24,32])draw($('size'+size),size);$('timeline').value=time;$('time').textContent=`${time.toFixed(2)} / ${duration.toFixed(2)} s`;$('phase').textContent=phase();$('hero').setAttribute('aria-label',phase()+'，吉祥物动画放大预览');$('play').textContent=playing?'暂停':'播放小样';}
function frame(now){raf=0;if(document.hidden)return;const dt=Math.min(.05,(now-(last||now))/1000);last=now;
  if(returning){returnElapsed+=dt;returnState.update(dt);if(returnElapsed>=.24){returning=false;time=0;}}
  else if(playing&&!reduced){time+=dt*Number($('speed').value);if(time>=duration){if($('loop').checked)time%=duration;else {time=duration;playing=false;}}}
  paint();if((playing||returning)&&!reduced)raf=requestAnimationFrame(frame);else last=0;
}
function wake(){if(!raf&&!document.hidden){last=0;raf=requestAnimationFrame(frame);}}
$('play').addEventListener('click',()=>{if(reduced){status('减少动态效果已开启，角色保持静止。');return;}if(returning){returning=false;time=0;}if(time>=duration)time=0;playing=!playing;wake();});
$('return').addEventListener('click',()=>{playing=false;if(reduced||time===0||returning){returning=false;time=0;wake();return;}const data=new spine.AnimationStateData(rig.data);data.defaultMix=.22;returnState=new spine.AnimationState(data);const old=returnState.setAnimation(0,'recall',false);old.trackTime=time;old.timeScale=0;returnState.apply(rig.skeleton);returnState.setAnimation(0,'rest',false);returnElapsed=0;returning=true;wake();});
$('timeline').addEventListener('input',e=>{playing=false;returning=false;time=Number(e.target.value);wake();});
for(const key of ['mesh','weights','speed','loop'])$(key).addEventListener('change',wake);
function setReduced(value){reduced=value;$('reduce').checked=value;if(value){playing=false;returning=false;time=0;}$('timeline').disabled=value||!assetReady;wake();}
$('reduce').addEventListener('change',e=>setReduced(e.target.checked));motionPreference.addEventListener('change',e=>setReduced(e.matches));
$('theme').addEventListener('click',()=>{const dark=document.body.classList.toggle('dark');$('theme').textContent=dark?'浅色':'深色';$('theme').setAttribute('aria-pressed',String(dark));wake();});
for(const key of ['strength','gaze'])$(key).addEventListener('input',()=>{$(key+'Value').textContent=Math.round($(key).value*100)+'%';});
$('apply').addEventListener('click',async()=>{const button=$('apply');button.disabled=true;status('正在生成并校验…');try{const r=await fetch('/api/author',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({strength:Number($('strength').value),gaze:Number($('gaze').value)})});const result=await r.json();if(!r.ok)throw Error(result.error);await reloadProject();playing=false;returning=false;time=reduced?0:duration*.22;status('已生成。原版保留，可播放或拖动时间轴查看。');wake();}catch(e){status('生成失败，当前动画保留：'+e.message);}finally{button.disabled=false;}});
async function reloadProject(){const project=await getJSON('/api/project');setData(project.json,project);wake();}
new ResizeObserver(wake).observe(document.querySelector('.workspace'));
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(raf);raf=0;last=0;}else wake();});
(async()=>{try{
  const atlasText=await(await fetch('data/images/mascot.atlas')).text();atlas=new spine.TextureAtlas(atlasText);
  await Promise.all(atlas.pages.map(async page=>{const image=new Image();image.src='data/images/'+page.name;await image.decode();page.setTexture(new spine.CanvasTexture(image));}));
  const [json,meta,debugData]=await Promise.all([getJSON('data/mascot.json'),getJSON('recipe.json'),getJSON('data/rig-debug.json')]);debug=debugData;setData(json,{recipe:meta});
  let connected=false;try{await reloadProject();connected=true;}catch{}assetReady=true;$('play').disabled=false;$('return').disabled=false;$('timeline').disabled=reduced;$('apply').disabled=!connected;
  $('health').textContent='11 根骨骼 · 193 个顶点 · 独立眼神 · 加权形变';status(connected?'调整后生成可编辑动画；原版保留。':'静态预览模式；启动本地制作服务可调整。');wake();
  if(connected)setInterval(async()=>{if(document.hidden)return;try{const s=await getJSON('/api/status');if(s.revision!==revision){await reloadProject();returning=false;status('已载入新的 MCP 制作版本。');}}catch{}},2500);
}catch(e){$('health').textContent='加载失败：'+e.message;$('phase').textContent='加载失败';}})();
