import AppKit
let p = URL(fileURLWithPath: CommandLine.arguments[1])
let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:1200,pixelsHigh:850,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
rep.size = NSSize(width:1200,height:850)
NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
NSColor(white:0.95,alpha:1).setFill(); NSRect(x:0,y:0,width:1200,height:850).fill()
func label(_ s:String,_ x:CGFloat,_ y:CGFloat,_ size:CGFloat=18) { (s as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:size,weight:.medium),.foregroundColor:NSColor(white:0.15,alpha:1)]) }
func draw(_ f:String,_ x:CGFloat,_ y:CGFloat,_ size:CGFloat) { NSImage(contentsOf:p.appendingPathComponent(f))!.draw(in:NSRect(x:x,y:y,width:size,height:size)) }
label("REVIEW TODAY / 黑白材质",40,791,28)
label("石墨底 · 银白 R · 无点睛色 · Icon Composer 原生导出",40,754)
for (i,kind) in ["original","glass"].enumerated() {
 let x:CGFloat = 60 + CGFloat(i)*590
 draw("\(kind)/default-512.png",x,290,420)
 label(i==0 ? "原版质感 / 克制渐变、轻微厚度" : "已确认 / 银白 R、无内侧边圈",x,262,21)
 var sx=x
 for size in [16,32,64,128] {draw("\(kind)/default-\(size).png",sx,94,CGFloat(size)); label("\(size) px",sx,70,12); sx += CGFloat(size)+28}
}
label("绿色原版与高清母版已单独保留 · 本轮为独立小样",40,24,15)
NSGraphicsContext.restoreGraphicsState()
try rep.representation(using:.png,properties:[:])!.write(to:p.appendingPathComponent("comparison.png"))
print("Saved comparison.png")
