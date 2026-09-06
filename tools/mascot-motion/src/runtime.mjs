import {TextureAtlas,AtlasAttachmentLoader,SkeletonJson,Skeleton,Physics,MixBlend,MixDirection,FakeTexture,MeshAttachment} from '@esotericsoftware/spine-core';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {previewRoot} from './paths.mjs';
export async function loadRig(json,textureLoader){
  const atlas=new TextureAtlas(await readFile(resolve(previewRoot,'data/images/mascot.atlas'),'utf8'));
  for(const page of atlas.pages){const image=textureLoader?await textureLoader(resolve(previewRoot,'data/images',page.name)):{width:page.width,height:page.height};page.setTexture(new FakeTexture(image));}
  const data=new SkeletonJson(new AtlasAttachmentLoader(atlas)).readSkeletonData(json);
  return {data,skeleton:new Skeleton(data),atlas};
}
export function sample(rig,time){
  rig.skeleton.setToSetupPose();
  rig.data.findAnimation('recall').apply(rig.skeleton,0,time,false,[],1,MixBlend.replace,MixDirection.mixIn);
  rig.skeleton.updateWorldTransform(Physics.none);return rig.skeleton;
}
export function verticesOf(skeleton,slotName='body'){
  const slot=skeleton.findSlot(slotName),a=slot.getAttachment();
  const vertices=new Float32Array(a.worldVerticesLength??8);
  if(a.worldVerticesLength!=null)a.computeWorldVertices(slot,0,vertices.length,vertices,0,2);
  else a.computeWorldVertices(slot,vertices,0,2);
  return vertices;
}
export async function verifyRuntime(json){
  const rig=await loadRig(json);const duration=rig.data.findAnimation('recall').duration;
  const steps=Math.ceil(duration*json.skeleton.fps)*2;
  let minArea=Infinity,maxCoordinate=0;
  for(let i=0;i<=steps;i++){
    const skeleton=sample(rig,duration*i/steps),v=verticesOf(skeleton),tris=skeleton.findSlot('body').getAttachment().triangles;
    for(const n of v){if(!Number.isFinite(n))throw Error('Non-finite runtime vertex');maxCoordinate=Math.max(maxCoordinate,Math.abs(n));}
    for(let t=0;t<tris.length;t+=3){const a=tris[t]*2,b=tris[t+1]*2,c=tris[t+2]*2;const area=((v[b]-v[a])*(v[c+1]-v[a+1])-(v[b+1]-v[a+1])*(v[c]-v[a]))/2;minArea=Math.min(minArea,area);}
  }
  const first=verticesOf(sample(rig,0)),last=verticesOf(sample(rig,duration));
  const endpointError=Math.max(...first.map((x,i)=>Math.abs(x-last[i])));
  if(minArea<=0)throw Error('Mesh triangle folded: '+minArea);
  if(endpointError>.001)throw Error('Loop endpoint drift');
  return {parser:'official spine-core 4.2.120',sampledFrames:steps+1,minTriangleArea:minArea,maxCoordinate,endpointError,duration};
}
