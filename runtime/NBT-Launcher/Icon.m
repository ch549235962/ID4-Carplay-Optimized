#import <Cocoa/Cocoa.h>
int main(int argc,const char **argv){@autoreleasepool{
    NSString *folder=[NSString stringWithUTF8String:argv[1]];
    [[NSFileManager defaultManager] createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:nil];
    for(NSNumber *n in @[@16,@32,@128,@256,@512])for(int scale=1;scale<=2;scale++){
        int size=n.intValue*scale;
        NSBitmapImageRep *rep=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:size pixelsHigh:size
            bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
        NSGraphicsContext *context=[NSGraphicsContext graphicsContextWithBitmapImageRep:rep];
        [NSGraphicsContext saveGraphicsState]; NSGraphicsContext.currentContext=context;
        NSAffineTransform *transform=NSAffineTransform.transform; [transform scaleBy:size/1024.0];[transform concat];
        NSBezierPath *background=[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(40,40,944,944) xRadius:205 yRadius:205];
        NSGradient *gradient=[[NSGradient alloc] initWithStartingColor:[NSColor colorWithSRGBRed:.05 green:.13 blue:.25 alpha:1]
            endingColor:[NSColor colorWithSRGBRed:.12 green:.30 blue:.48 alpha:1]];
        [gradient drawInBezierPath:background angle:70];
        [[NSColor colorWithSRGBRed:.86 green:.95 blue:1 alpha:1] setStroke];
        NSBezierPath *ring=[NSBezierPath bezierPathWithOvalInRect:NSMakeRect(224,290,576,576)];ring.lineWidth=46;[ring stroke];
        NSBezierPath *spokes=NSBezierPath.bezierPath;spokes.lineWidth=42;spokes.lineCapStyle=NSLineCapStyleRound;
        for(NSValue *v in @[[NSValue valueWithPoint:NSMakePoint(247,602)],[NSValue valueWithPoint:NSMakePoint(777,602)],
                            [NSValue valueWithPoint:NSMakePoint(512,312)]]){
            [spokes moveToPoint:NSMakePoint(512,552)];[spokes lineToPoint:v.pointValue];
        }[spokes stroke];
        [[NSColor colorWithSRGBRed:.1 green:.25 blue:.4 alpha:1] setFill];
        [[NSBezierPath bezierPathWithOvalInRect:NSMakeRect(416,456,192,192)] fill];
        [[NSColor colorWithSRGBRed:.2 green:.92 blue:.7 alpha:1] setFill];
        [[NSBezierPath bezierPathWithOvalInRect:NSMakeRect(735,770,120,120)] fill];
        NSDictionary *attributes=@{NSFontAttributeName:[NSFont systemFontOfSize:114 weight:NSFontWeightBold],NSForegroundColorAttributeName:NSColor.whiteColor};
        NSString *title=@"NBT"; NSSize t=[title sizeWithAttributes:attributes];
        [title drawAtPoint:NSMakePoint((1024-t.width)/2,125) withAttributes:attributes];
        [NSGraphicsContext restoreGraphicsState];
        NSString *name=[NSString stringWithFormat:@"icon_%@x%@%@.png",n,n,scale==2?@"@2x":@""];
        [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:[folder stringByAppendingPathComponent:name] atomically:YES];
    }
}return 0;}
