// One source for authoring, scheduling, preview labels and framing.
export const idleDurations={idle_look:4,idle_hop:3.2,idle_stretch:3.6,idle_book:8};
export const idleNames=Object.keys(idleDurations);
export function idleFraming(width,height){return {x:width/2,y:height*.53,scale:Math.min(width/410,height/460)};}
