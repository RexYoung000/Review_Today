import test from 'node:test';
import assert from 'node:assert/strict';
import {createCanvas,loadImage} from '@napi-rs/canvas';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createMaterials,materialPalette,materialPixel,waveColor} from '../../../brand/refresh-2026-09/motion-rig/material.mjs';
import {renderFrame} from '../src/render.mjs';
const dir=new URL('../../../brand/refresh-2026-09/motion-rig/',import.meta.url);
test('graphite texture keeps alpha, dimensions and shading without mutating source or geometry',async()=>{
 const names=['body','eye','pupil','fragment','shadow'],images=new Map();
 const geometry=await readFile(new URL('data/mascot.json',dir));
 for(const n of names)images.set(n+'.png',await loadImage(await readFile(new URL(`data/images/${n}.png`,dir))));
 const materials=createMaterials(images,createCanvas),neutral=materials('graphite',false),active=materials('graphite',false,true);
 assert.equal(materials('current',false),undefined);assert.equal(materials('graphite',false),neutral);
 for(const [name,img] of images){
  const original=createCanvas(img.width,img.height);original.getContext('2d').drawImage(img,0,0);
  const a=original.getContext('2d').getImageData(0,0,img.width,img.height).data;
  const target=neutral.get(img),b=target.getContext('2d').getImageData(0,0,img.width,img.height).data;
  assert.equal(target.width,img.width);assert.equal(target.height,img.height);
  const values=new Set();for(let i=0;i<a.length;i+=4){assert.equal(a[i+3],b[i+3]);assert.equal(b[i],b[i+1]);assert.equal(b[i],b[i+2]);if(b[i+3]>128)values.add(b[i]);}
  if(name==='body.png')assert.ok(values.size>30,'retain broad material shading');
  const activePixels=active.get(img).getContext('2d').getImageData(0,0,img.width,img.height).data;
  for(let i=0;i<activePixels.length;i+=4){assert.equal(activePixels[i],activePixels[i+1]);assert.equal(activePixels[i],activePixels[i+2]);}
  if(name!=='fragment.png')assert.equal(active.get(img),target,'only the active ball gets accent');
 }
 assert.deepEqual(await readFile(new URL('data/mascot.json',dir)),geometry);
});
test('wave rests in gray, active feedback uses supplied theme accent and legacy colors remain',()=>{
 for(const dark of [false,true]){
  const p=materialPalette(dark);assert.equal(new Set(p.accent).size,1);assert.deepEqual(waveColor(0,{material:'graphite',dark}),p.wave);
  assert.deepEqual(waveColor(1,{material:'graphite',dark}),p.accent);
  assert.deepEqual(waveColor(0,{dark}),dark?[71,95,86]:[187,207,196]);
 }
 assert.deepEqual(waveColor(1,{material:'graphite',palette:{accent:[2,3,4]}}),[2,3,4]);
});
test('native source and saved original assets are not changed by offline material rendering',async()=>{
 const json=JSON.parse(await readFile(new URL('data/mascot.json',dir))),file=new URL('assets/body-source.png',dir),before=createHash('sha256').update(await readFile(file)).digest('hex');
 const legacy=await renderFrame(json,1,256,false,'recall'),graphite=await renderFrame(json,1,256,false,'recall','graphite');assert.notDeepEqual(legacy,graphite);
 assert.equal(createHash('sha256').update(await readFile(file)).digest('hex'),before);
});

test('dark theme lightens body and keeps white eyes with dark pupils while preserving material shading and neutral fragments',()=>{
 const light=materialPalette(false),dark=materialPalette(true);
 for(const y of [.2,.5,.8]){
  const a=materialPixel('body.png',50,80,65,false,light,.5,y),b=materialPixel('body.png',50,80,65,false,dark,.5,y);
  assert.ok(a[0]<80);assert.ok(b[0]>200);assert.equal(new Set(b).size,1);
 }
 assert.deepEqual(materialPixel('eye.png',0,0,0,false,dark),[247,247,247]);
 assert.deepEqual(materialPixel('pupil.png',0,0,0,false,dark),[35,35,35]);
 assert.ok(materialPixel('fragment.png',200,200,200,false,dark)[0]>=100);
});
