// hwr: handwriting recognition for IDEmu's iDrive Touch Controller (address and search input). Reads strokes on stdin, one stroke per
// line as "x,y x,y ..." (0..1, top-left origin), draws them black on white and asks macOS Vision (VNRecognizeTextRequest) what they say.
// Prints up to 5 candidates, best first: "<character> <confidence 0..100>" (one character each: the controller recognises one at a time).
// Build: tools/hwr/build.sh -> bin/hwr. Usage: printf '0.2,0.9 0.2,0.1 0.5,0.6 0.8,0.1 0.8,0.9\n' | bin/hwr [--lang en-US,de-DE] [--png out.png]
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>

int main(int argc, const char **argv) {
    @autoreleasepool {
        NSArray *langs = nil; NSString *png = nil;
        for (int i = 1; i + 1 < argc; i++) {
            if (!strcmp(argv[i], "--lang")) langs = [@(argv[++i]) componentsSeparatedByString:@","];
            else if (!strcmp(argv[i], "--png")) png = @(argv[++i]);
        }
        NSData *in = [[NSFileHandle fileHandleWithStandardInput] readDataToEndOfFile];
        NSString *txt = [[NSString alloc] initWithData:in encoding:NSUTF8StringEncoding];
        NSMutableArray<NSArray<NSValue *> *> *strokes = [NSMutableArray array];
        double minx = 1, miny = 1, maxx = 0, maxy = 0;
        for (NSString *line in [txt componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet]) {
            NSMutableArray *pts = [NSMutableArray array];
            for (NSString *p in [line componentsSeparatedByString:@" "]) {
                NSArray *xy = [p componentsSeparatedByString:@","]; if (xy.count != 2) continue;
                double x = [xy[0] doubleValue], y = [xy[1] doubleValue];
                [pts addObject:[NSValue valueWithPoint:NSMakePoint(x, y)]];
                minx = MIN(minx, x); miny = MIN(miny, y); maxx = MAX(maxx, x); maxy = MAX(maxy, y);
            }
            if (pts.count) [strokes addObject:pts];
        }
        if (!strokes.count) return 1;
        // the character, 120 px high, in the middle of a wide white line: Vision finds no text in one glyph that fills the image
        const int W = 640, S = 320; const double CH = 120;
        double w = MAX(maxx - minx, 1e-3), h = MAX(maxy - miny, 1e-3), sc = CH / MAX(h, w * 0.8);
        double ox = (W - w * sc) / 2, oy = (S - h * sc) / 2;
        CGImageRef (^render)(int) = ^CGImageRef(int copies) {     // the character once, or twice side by side (Vision reads a "word" better)
            CGColorSpaceRef cs = CGColorSpaceCreateDeviceGray();
            CGContextRef cg = CGBitmapContextCreate(NULL, W, S, 8, W, cs, (CGBitmapInfo)kCGImageAlphaNone);
            CGContextSetGrayFillColor(cg, 1, 1); CGContextFillRect(cg, CGRectMake(0, 0, W, S));
            CGContextSetGrayStrokeColor(cg, 0, 1); CGContextSetLineWidth(cg, 9); CGContextSetLineCap(cg, kCGLineCapRound); CGContextSetLineJoin(cg, kCGLineJoinRound);
            for (int k = 0; k < copies; k++) {
                double dx = (k - (copies - 1) / 2.0) * (w * sc + 40);
                for (NSArray<NSValue *> *pts in strokes) {
                    for (NSUInteger i = 0; i < pts.count; i++) {
                        NSPoint p = pts[i].pointValue; CGFloat x = dx + ox + (p.x - minx) * sc, y = S - (oy + (p.y - miny) * sc);
                        if (i == 0) CGContextMoveToPoint(cg, x, y); else CGContextAddLineToPoint(cg, x, y);
                        if (pts.count == 1) CGContextAddLineToPoint(cg, x + 0.5, y);
                    }
                    CGContextStrokePath(cg);
                }
            }
            CGImageRef im = CGBitmapContextCreateImage(cg); CGContextRelease(cg); CGColorSpaceRelease(cs); return im;
        };
        CGImageRef img = render(1);
        if (png) {
            CGImageDestinationRef d = CGImageDestinationCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:png], CFSTR("public.png"), 1, NULL);
            CGImageDestinationAddImage(d, img, NULL); CGImageDestinationFinalize(d); CFRelease(d);
        }
        NSMutableOrderedSet *seen = [NSMutableOrderedSet orderedSet]; NSMutableArray *out = [NSMutableArray array];
        for (int pass = 0; pass < 4 && !out.count; pass++) {        // accurate, fast, then both on the character drawn twice
        int level = pass & 1; if (pass == 2) { CGImageRelease(img); img = render(2); }
        VNRecognizeTextRequest *rq = [VNRecognizeTextRequest new];
        rq.recognitionLevel = level ? VNRequestTextRecognitionLevelFast : VNRequestTextRecognitionLevelAccurate; rq.usesLanguageCorrection = NO;
        if (langs) rq.recognitionLanguages = langs;
        NSError *err = nil;
        [[[VNImageRequestHandler alloc] initWithCGImage:img options:@{}] performRequests:@[rq] error:&err];
        if (err) { fprintf(stderr, "vision: %s\n", err.localizedDescription.UTF8String); return 2; }
        for (VNRecognizedTextObservation *o in rq.results)
            for (VNRecognizedText *t in [o topCandidates:10]) {
                NSString *s = [t.string stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
                if (s.length < 1) continue;
                NSString *c = [s substringWithRange:[s rangeOfComposedCharacterSequenceAtIndex:0]];
                if ([seen containsObject:c]) continue;
                [seen addObject:c]; [out addObject:[NSString stringWithFormat:@"%@ %d", c, (int)lround(t.confidence * 100)]];
                if (out.count >= 5) break;
            }
        }
        for (NSString *l in out) printf("%s\n", l.UTF8String);
        CGImageRelease(img);
        return out.count ? 0 : 3;
    }
}
