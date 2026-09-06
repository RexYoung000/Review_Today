// Editable, periodic weighted deformation for the same mascot. No baked sprite motion.
export function voiceAnimations(mesh,contourLength,recipe){
  const result={};
  for(const mode of ['listening','speaking']){
    const a={bones:{},attachments:{default:{body:{body:{deform:[]}},shadow_clip:{clip:{deform:[]}}}}};
    const add=(name,prop,frame)=>((a.bones[name]??={})[prop]??=[]).push(frame);
    const count=recipe.fps*4,round=x=>Math.round(x*1e5)/1e5;
    for(let f=0;f<=count;f++){
      const u=f/count,t=u*4,q=u*Math.PI*2,k=recipe.strength*(mode==='speaking'?1.25:.65);
      const sway=Math.sin(q),beat=Math.sin(q*3),echo=Math.sin(q*3-.6);
      add('body','translate',{time:t,x:round(sway*2*k),y:round((1-Math.cos(q*3))*2*k)});
      add('body','rotate',{time:t,value:round(sway*1.8*k)});
      for(const [i,name] of ['left','crown','right'].entries()){
        add(name,'rotate',{time:t,value:round(Math.sin(q*3-i*.7)*[2.3,1.4,-2.3][i]*k)});
        add(name,'translate',{time:t,x:round(beat*[-1.2,0,1.2][i]*k),y:round(Math.sin(q*3-i*.7)*[5,7,5][i]*k)});
      }
      add('face','translate',{time:t,x:round(sway*2*recipe.gaze),y:round(echo*1.3*k)});
      // A brief glance, then attention returns; eyes move independently of body sway.
      const glance=Math.sin(q)*Math.sin(q),blink=Math.max(0,1-Math.abs(u-.7)/.035);
      for(const side of ['left','right']){
        add('pupil_'+side,'translate',{time:t,x:round((-8+5*glance)*recipe.gaze),y:round(Math.sin(q*2)*1.8*recipe.gaze)});
        add('eye_'+side,'scale',{time:t,x:1,y:round(1-.92*blink)});
      }
      const offsets=[];
      for(const v of mesh.points){
        const upper=Math.max(0,(v.y+95)/205);
        const dx=recipe.wave*1.25*k*Math.sin(q*3-v.y/65)*upper;
        const dy=recipe.wave*1.6*k*Math.sin(q*3-v.x/70)*( .3+.7*upper);
        for(let i=0;i<3;i++)offsets.push(round(dx),round(dy));
      }
      a.attachments.default.body.body.deform.push({time:t,vertices:offsets});
      a.attachments.default.shadow_clip.clip.deform.push({time:t,vertices:offsets.slice(0,contourLength*6)});
    }
    result[mode]=a;
  }
  return result;
}
