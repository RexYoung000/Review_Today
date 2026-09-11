// Authored paragraph patterns, independent of language and real progress.
// Stable absolute row identities make seeking and A -> B deterministic.
export const rowLayout={x:310,y:234,maxWidth:140,gap:28,paragraphGap:40,lead:.25};
const pattern=[[140,false],[112,false],[64,true],[124,false],[76,true],[136,false],[100,false],[52,true]];
export function rowSpec(index){
 const [width,paragraphEnd]=pattern[((index%pattern.length)+pattern.length)%pattern.length];
 const ratio=width/rowLayout.maxWidth,prepare=.48*(.7+.3*ratio),stroke=.32*ratio,recover=.75+.25*ratio;
 const holdEnd=prepare+stroke+.18*recover,pause=paragraphEnd?.22:0;
 const keys=[[0,0],[prepare,.48],[prepare+stroke,.80],[holdEnd,.98],[holdEnd+pause,.98],[holdEnd+pause+.18*recover,1.16],[holdEnd+pause+.22*recover,1.2]];
 return {index,width,paragraphEnd,gap:paragraphEnd?rowLayout.paragraphGap:rowLayout.gap,keys,duration:keys.at(-1)[0],prepare,stroke,pause,liftScale:.7+.3*ratio};
}
const prefix=[0];for(let i=0;i<pattern.length;i++)prefix.push(prefix.at(-1)+rowSpec(i).duration);
export const paragraphPeriod=prefix.at(-1);
export function rowStart(index){return rowLayout.lead+Math.floor(index/pattern.length)*paragraphPeriod+prefix[index%pattern.length];}
export function rowAt(time){
 const elapsed=Math.max(0,time-rowLayout.lead),round=Math.floor(elapsed/paragraphPeriod),local=elapsed-round*paragraphPeriod;
 return round*pattern.length+Math.max(0,prefix.slice(0,-1).findLastIndex(t=>t<=local+1e-10));
}
export function rowOffset(from,to){let y=0;for(let i=from;i<to;i++)y+=rowSpec(i).gap;return y;}
export function beatTime(index,local){
 const keys=rowSpec(index).keys;if(local<0)return local;
 for(let i=1;i<keys.length;i++){const [b,y]=keys[i],[a,x]=keys[i-1];if(local<=b)return b===a?y:x+(y-x)*(local-a)/(b-a);}
 return 1.2;
}
// Map a canonical beat landmark into actual seconds for authoring/tests.
export function rowTime(index,beat){
 const keys=rowSpec(index).keys;
 for(let i=1;i<keys.length;i++){const [b,y]=keys[i],[a,x]=keys[i-1];if(beat<=y)return rowStart(index)+(y===x?a:a+(b-a)*(beat-x)/(y-x));}
 return rowStart(index)+rowSpec(index).duration;
}
