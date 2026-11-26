#import <Cocoa/Cocoa.h>

@interface Launcher : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property NSWindow *window;
@property NSTextField *headline;
@property NSTextField *detail;
@property NSTextField *progress;
@property NSMutableArray<NSButton *> *buttons;
@property BOOL busy;
@property BOOL polling;
@property NSString *root;
@end

@implementation Launcher
- (NSTextField *)label:(NSString *)text y:(CGFloat)y size:(CGFloat)size {
    NSTextField *field = [NSTextField labelWithString:text];
    field.frame = NSMakeRect(30,y,500,size>20?42:52);
    field.font = [NSFont systemFontOfSize:size weight:size>20?NSFontWeightSemibold:NSFontWeightRegular];
    field.maximumNumberOfLines = 3;
    [self.window.contentView addSubview:field]; return field;
}
- (void)button:(NSString *)title x:(CGFloat)x y:(CGFloat)y action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.frame=NSMakeRect(x,y,238,40); button.bezelStyle=NSBezelStyleRounded;
    [self.window.contentView addSubview:button]; [self.buttons addObject:button];
}
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    self.root = [[NSBundle.mainBundle objectForInfoDictionaryKey:@"ControllerRoot"] stringByStandardizingPath];
    self.buttons = NSMutableArray.new;
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,560,510)
        styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title=@"NBT · CarPlay 控制台"; self.window.delegate=self;
    [self.window center];
    [self label:@"NBT + CarPlay" y:433 size:29];
    self.headline=[self label:@"正在检查服务…" y:393 size:17];
    self.headline.frame=NSMakeRect(30,393,500,28);
    self.detail=[self label:@"" y:341 size:13]; self.detail.textColor=NSColor.secondaryLabelColor;
    self.detail.frame=NSMakeRect(30,341,500,40);
    [self button:@"一键开启服务" x:26 y:285 action:@selector(start:)];
    [self button:@"全部停止" x:296 y:285 action:@selector(stop:)];
    [self button:@"重新连接 CarPlay" x:26 y:235 action:@selector(reconnect:)];
    [self button:@"打开 NBT 网页" x:26 y:185 action:@selector(openNBT:)];
    [self button:@"打开 CarPlay 状态页" x:296 y:185 action:@selector(openCarPlay:)];
    [self button:@"无线 CarPlay 测试" x:26 y:135 action:@selector(wireless:)];
    [self button:@"切回 USB" x:296 y:135 action:@selector(usb:)];
    self.progress=[self label:@"" y:65 size:13];
    self.progress.frame=NSMakeRect(30,65,500,40);
    NSButton *logs=[NSButton buttonWithTitle:@"查看日志" target:self action:@selector(logs:)];
    logs.frame=NSMakeRect(296,235,238,40); logs.bezelStyle=NSBezelStyleRounded;
    [self.window.contentView addSubview:logs];
    NSTextField *hint=[self label:@"网页仅在点击按钮时打开；关闭控制台会保留后台服务。" y:30 size:11];
    hint.frame=NSMakeRect(30,30,500,20); hint.textColor=NSColor.secondaryLabelColor;
    [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
    [NSTimer scheduledTimerWithTimeInterval:5 target:self selector:@selector(poll:) userInfo:nil repeats:YES];
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--no-autostart"]) [self poll:nil];
    else [self start:nil];
}
- (void)render:(NSDictionary *)state {
    BOOL all=[state[@"services_running"] boolValue], phone=[state[@"phone_connected"] boolValue];
    BOOL vm=[state[@"vm_running"] boolValue], receiver=[state[@"receiver_running"] boolValue];
    self.headline.stringValue=all?(phone?@"服务已开启 · CarPlay 已连接":@"服务已开启 · 等待 iPhone 连接"):
        ((!vm&&!receiver)?@"服务已停止":@"部分服务正在运行 · 可点击开启补齐");
    if(vm&&receiver&&![state[@"controller_ready"] boolValue])self.headline.stringValue=@"QNX 正在启动 · 手机接收服务已开启";
    self.detail.stringValue=[NSString stringWithFormat:@"NBT 虚拟机：%@    CarPlay：%@\n视频通道：%@    旋钮控制：%@",
        vm?@"运行中":@"停止",receiver?@"运行中":@"停止",
        [state[@"video_bridge_running"] boolValue]?@"运行中":@"停止",
        [state[@"controls_ready"] boolValue]?@"就绪":@"等待"];
}
- (void)run:(NSArray<NSString *> *)arguments polling:(BOOL)polling {
    if (polling) { if(self.busy||self.polling)return; self.polling=YES; }
    else { if(self.busy)return; self.busy=YES; for(NSButton *b in self.buttons)b.enabled=NO; self.progress.stringValue=@"正在处理…"; }
    NSTask *task=NSTask.new; task.executableURL=[NSURL fileURLWithPath:@"/opt/homebrew/bin/python3.13"];
    task.arguments=[@[[self.root stringByAppendingPathComponent:@"controller.py"]] arrayByAddingObjectsFromArray:arguments];
    NSPipe *pipe=NSPipe.pipe; task.standardOutput=pipe; task.standardError=[NSFileHandle fileHandleWithNullDevice];
    NSError *error=nil;
    if(![task launchAndReturnError:&error]) {
        if(polling)self.polling=NO; else {self.busy=NO;for(NSButton *b in self.buttons)b.enabled=YES;
            self.progress.stringValue=@"无法启动管理程序，请检查 Python 安装和文件路径。";} return;
    }
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
        NSMutableData *pending=NSMutableData.new;
        while(YES){
            NSData *data=[pipe.fileHandleForReading availableData]; if(data.length==0)break;
            [pending appendData:data];
            while(YES){
                const unsigned char *bytes=pending.bytes; NSUInteger position=NSNotFound;
                for(NSUInteger i=0;i<pending.length;i++)if(bytes[i]=='\n'){position=i;break;}
                if(position==NSNotFound)break;
                NSData *line=[pending subdataWithRange:NSMakeRange(0,position)];
                [pending replaceBytesInRange:NSMakeRange(0,position+1) withBytes:NULL length:0];
                NSDictionary *event=[NSJSONSerialization JSONObjectWithData:line options:0 error:nil];
                if(![event isKindOfClass:NSDictionary.class])continue;
                dispatch_async(dispatch_get_main_queue(), ^{
                    if(event[@"state"] && !(polling&&self.busy))[self render:event[@"state"]];
                    if(!polling){
                        if(event[@"message"])self.progress.stringValue=event[@"message"];
                        if(event[@"ok"])self.progress.stringValue=[event[@"ok"] boolValue]?@"操作完成。":(event[@"error"]?:@"操作失败，请查看日志。");
                    }
                });
            }
        }
        [task waitUntilExit];
        dispatch_async(dispatch_get_main_queue(), ^{
            if(polling)self.polling=NO;
            else {self.busy=NO; for(NSButton *b in self.buttons)b.enabled=YES;
                if(task.terminationStatus!=0 && [self.progress.stringValue isEqual:@"正在处理…"])self.progress.stringValue=@"操作失败，请查看日志。";
                [self poll:nil];}
        });
    });
}
- (void)start:(id)sender {[self run:@[@"start"] polling:NO];}
- (void)stop:(id)sender {[self run:@[@"stop"] polling:NO];}
- (void)reconnect:(id)sender {[self run:@[@"reconnect"] polling:NO];}
- (void)openNBT:(id)sender {[self run:@[@"open-nbt"] polling:NO];}
- (void)openCarPlay:(id)sender {[self run:@[@"open-carplay"] polling:NO];}
- (void)wireless:(id)sender {[self run:@[@"wireless"] polling:NO];}
- (void)usb:(id)sender {[self run:@[@"usb"] polling:NO];}
- (void)poll:(id)sender {[self run:@[@"status"] polling:YES];}
- (void)logs:(id)sender {
    for(NSString *folder in @[@"NBT-Original/logs",@"CarPlay-Wireless/logs",@"CarPlay-QNX-Native/logs"])
        [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:[[self.root stringByDeletingLastPathComponent] stringByAppendingPathComponent:folder]]];
}
- (BOOL)windowShouldClose:(NSWindow *)sender {return !self.busy;}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {return YES;}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {return self.busy?NSTerminateCancel:NSTerminateNow;}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    [self.window makeKeyAndOrderFront:nil]; if(!self.busy)[self start:nil]; return YES;
}
@end

int main(int argc,const char **argv){@autoreleasepool{
    NSApplication *app=NSApplication.sharedApplication; Launcher *delegate=Launcher.new;
    app.delegate=delegate; [app setActivationPolicy:NSApplicationActivationPolicyRegular]; [app run];
}return 0;}
