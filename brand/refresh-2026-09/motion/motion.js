'use strict';
// Motion study only. All state changes are local; no audio or model connection.
const $ = id => document.getElementById(id);
const sprite = new Image();
let ready = false, crop = {x:0,y:0,w:1,h:1}, reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
let raf = 0, last = 0, volume = .55;
const models = {
  thinking: {mode:'idle', split:0, wave:0, phase:0},
  voice: {mode:'idle', split:0, wave:0, phase:0}
};
const labels = {idle:'准备好了',thinking:'正在思考 · 模拟',listening:'正在聆听 · 模拟',speaking:'正在回应 · 模拟',error:'已暂停 · 模拟异常，可重新开始'};
$('reduced').checked = reduced;
function setMode(panel, mode) {
  const model = models[panel];
  model.mode = mode;
  $(panel+'Status').textContent = mode === 'idle' ? '已收拢 · 静止' : labels[mode];
  $(panel+'Hero').setAttribute('aria-label',`${labels[mode]}，吉祥物动效预览`);
  $(panel+'Hero').closest('.study').classList.toggle('error', mode === 'error');
  document.querySelectorAll(`[data-panel="${panel}"]`).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  // State text and target change in the input event. No animation completion gate.
  wake();
}
document.querySelectorAll('[data-panel]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.panel,b.dataset.mode)));
$('reduced').addEventListener('change', e => { reduced=e.target.checked; wake(); });
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',e => {reduced=e.matches;$('reduced').checked=reduced;wake();});
$('theme').addEventListener('click', () => { const dark=document.body.classList.toggle('dark'); $('theme').textContent=dark?'浅色':'深色';$('theme').setAttribute('aria-pressed',String(dark)); wake(); });
$('volume').addEventListener('input',e => {volume=Number(e.target.value)/100;$('volumeValue').textContent=e.target.value+'%';wake();});
function approach(current,target,dt) {const v=current+(target-current)*(1-Math.exp(-dt*15));return Math.abs(v-target)<.0008?target:v;}
function setup(canvas) {
  const r=canvas.getBoundingClientRect(), d=Math.min(devicePixelRatio||1,2);
  const w=Math.round(r.width*d),h=Math.round(r.height*d);
  if(canvas.width!==w || canvas.height!==h){canvas.width=w;canvas.height=h;}
  const c=canvas.getContext('2d');c.setTransform(d,0,0,d,0,0);c.clearRect(0,0,r.width,r.height);
  return {c,w:r.width,h:r.height};
}
function drawSprite(c,x,y,w,sx=1,sy=1,angle=0) {
  const h=w*crop.h/crop.w;
  c.save();c.translate(x,y);c.rotate(angle);c.scale(sx,sy);
  c.drawImage(sprite,crop.x,crop.y,crop.w,crop.h,-w/2,-h/2,w,h);c.restore();
}
// A masked piece buds from the same sprite while the main body's volume contracts.
function thinker(c,x,y,w,model) {
  const h=w*crop.h/crop.w, q=reduced?0:model.split;
  if(q===0){drawSprite(c,x,y,w);return;}
  const theta=model.phase*2*Math.PI/2.3;
  const cutX=w*.35, cutY=h*.15, radius=w*.16;
  const orbitX=Math.cos(theta)*w*.58, orbitY=Math.sin(theta)*h*.78;
  const pieceX=cutX+(orbitX-cutX)*q, pieceY=cutY+(orbitY-cutY)*q;
  c.save();c.translate(x,y);
  const drawPiece = () => {
    c.save();c.translate(pieceX-cutX,pieceY-cutY);
    c.beginPath();c.arc(cutX,cutY,radius,0,Math.PI*2);c.clip();
    c.drawImage(sprite,crop.x,crop.y,crop.w,crop.h,-w/2,-h/2,w,h);c.restore();
  };
  if(orbitY<0)drawPiece();
  c.save();
  const swell=1-q*.055+q*.014*Math.sin(theta*2);
  c.scale(swell,1-q*.025);
  c.drawImage(sprite,crop.x,crop.y,crop.w,crop.h,-w/2,-h/2,w,h);c.restore();
  if(orbitY>=0)drawPiece();
  c.restore();
}
function speaker(c,w,h,model,compact=false) {
  const q=reduced?0:model.wave, split=reduced?0:model.split;
  const t=model.phase, amplitude=volume*q;
  const barCount=15, spacing=compact?8:16, cx=w/2, baseline=compact?h-7:h*.78;
  const barWidth=compact?3:5;
  const tint=getComputedStyle(document.body).getPropertyValue('--teal');
  c.fillStyle=tint.trim();
  const heights=[];
  for(let i=0;i<barCount;i++){
    const envelope=.4+.6*Math.sin(t*2.1-i*.37)**2;
    const wave=(compact?5:9)+(compact?17:43)*amplitude*envelope;
    heights.push(wave);
    c.globalAlpha=(.22+.32*volume)*(1-split);
    c.beginPath();c.roundRect(cx+(i-7)*spacing-barWidth/2,baseline-wave,barWidth,wave,barWidth/2);c.fill();
  }
  c.globalAlpha=1;
  const xShift=Math.sin(t*1.3)*(compact?24:65)*amplitude;
  const ix=Math.max(0,Math.min(13,7+xShift/spacing)),lo=Math.floor(ix);
  const waveTop=heights[lo]+(heights[lo+1]-heights[lo])*(ix-lo);
  const bodyW=compact?29:82, bodyH=bodyW*crop.h/crop.w;
  const bounce=(.5+.5*Math.sin(t*3.1))*(compact?3:10)*amplitude;
  const sy=1+Math.sin(t*3.1)*.085*amplitude, sx=1/sy;
  const voiceY=baseline-waveTop-bodyH*sy/2-5-bounce;
  // Morph at the same location; transitions can reverse at any frame.
  const idleY=compact?h*.42:h*.45;
  const y=idleY+(voiceY-idleY)*q;
  const x=cx+xShift*(1-split);
  if(split>0 || model.mode==='thinking') {
    thinker(c,x,y,bodyW,model);
  } else {
    drawSprite(c,x,y,bodyW,sx,sy,Math.cos(t*1.3)*.06*amplitude);
  }
}
function paint() {
  if(!ready)return;
  let p=setup($('thinkingHero'));thinker(p.c,p.w/2,p.h*.46,116,models.thinking);
  for(const size of [18,24,32]){p=setup($('size'+size));thinker(p.c,p.w/2,p.h/2,size/1.55,models.thinking);}
  p=setup($('voiceHero'));speaker(p.c,p.w,p.h,models.voice);
  p=setup($('voiceSmall'));speaker(p.c,p.w,p.h,models.voice,true);
}
function frame(now) {
  raf=0;if(document.hidden)return;
  const dt=Math.min((now-(last||now))/1000,.04);last=now;
  let active=false;
  for(const model of Object.values(models)) {
    const spin=!reduced&&model.mode==='thinking', wave=!reduced&&['listening','speaking'].includes(model.mode);
    model.split=approach(model.split,spin?1:0,dt);model.wave=approach(model.wave,wave?1:0,dt);
    if(reduced){model.split=0;model.wave=0;}
    if(spin||wave||model.split||model.wave){model.phase+=dt;active=true;}
  }
  paint();
  if(active&&!reduced)raf=requestAnimationFrame(frame);else last=0;
}
function wake(){if(!raf&&!document.hidden){last=0;raf=requestAnimationFrame(frame);}}
new ResizeObserver(wake).observe(document.querySelector('.studies'));
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(raf);raf=0;last=0;}else wake();});
sprite.onload=()=>{
  // Crop metadata is generated from the transparent sprite for file:// support.
  crop=SPRITE_BOUNDS;ready=true;$('assetStatus').textContent='角色已载入 · 点击开始预览';wake();
};
sprite.onerror=()=>{$('assetStatus').textContent='角色素材未载入，请保留同目录的 sprite.png';document.querySelectorAll('[data-panel]').forEach(b=>b.disabled=true);};
const SPRITE_BOUNDS={"x": 129, "y": 227, "w": 999, "h": 774};
sprite.src='sprite.png';
