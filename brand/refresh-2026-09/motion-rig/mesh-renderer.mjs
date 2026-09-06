// Small rasterization adapter: Spine still owns skeletons, skinning and deformation.
// Overlap the triangle clip by a fraction of a pixel to hide Canvas antialias seams.
// UV mapping stays on the original triangle, so the texture itself is not stretched.
export function seamlessRenderer(Base){return class extends Base{
  draw(skeleton){
    for(const slot of skeleton.drawOrder){
      this.ctx.save();const attachment=slot.getAttachment();
      if(attachment?.triangles&&attachment.hullLength){
        const v=new Float32Array(attachment.worldVerticesLength);attachment.computeWorldVertices(slot,0,v.length,v,0,2);
        this.ctx.beginPath();for(let i=0;i<attachment.hullLength;i+=2)i?this.ctx.lineTo(v[i],v[i+1]):this.ctx.moveTo(v[i],v[i+1]);this.ctx.closePath();this.ctx.clip();
      }
      super.draw({color:skeleton.color,drawOrder:[slot]});this.ctx.restore();
    }
  }

  drawTriangle(image,x0,y0,u0,v0,x1,y1,u1,v1,x2,y2,u2,v2){
    const ctx=this.ctx,us=[u0,u1,u2].map(u=>u*(image.width-1)),vs=[v0,v1,v2].map(v=>v*(image.height-1));
    const dx1=x1-x0,dx2=x2-x0,dy1=y1-y0,dy2=y2-y0,du1=us[1]-us[0],du2=us[2]-us[0],dv1=vs[1]-vs[0],dv2=vs[2]-vs[0];
    const det=du1*dv2-du2*dv1;if(Math.abs(det)<1e-8)return;
    const a=(dx1*dv2-dx2*dv1)/det,b=(dy1*dv2-dy2*dv1)/det,c=(dx2*du1-dx1*du2)/det,d=(dy2*du1-dy1*du2)/det;
    const e=x0-a*us[0]-c*vs[0],f=y0-b*us[0]-d*vs[0];
    const tr=ctx.getTransform(),screenScale=Math.max(.01,Math.hypot(tr.a,tr.b));
    const pad=.7/screenScale,points=[[x0,y0],[x1,y1],[x2,y2]];
    const winding=Math.sign(dx1*dy2-dy1*dx2);
    const normals=points.map(([x,y],i)=>{const q=points[(i+1)%3],dx=q[0]-x,dy=q[1]-y,len=Math.hypot(dx,dy)||1;return [winding*dy/len,-winding*dx/len];});
    ctx.save();ctx.beginPath();
    points.forEach(([x,y],i)=>{const previous=normals[(i+2)%3],next=normals[i],den=Math.max(.005,1+previous[0]*next[0]+previous[1]*next[1]);
      const xx=x+(previous[0]+next[0])*pad/den,yy=y+(previous[1]+next[1])*pad/den;i?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy);});
    ctx.closePath();ctx.clip();ctx.transform(a,b,c,d,e,f);ctx.drawImage(image,0,0);ctx.restore();
  }
};}
