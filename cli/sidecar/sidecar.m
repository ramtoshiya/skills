#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <IOKit/graphics/IOGraphicsTypes.h>
#import <dlfcn.h>

// SidecarCore has no public connection API. Check these selectors at runtime.
@interface NSObject (SidecarFactory)
+ (id)sharedManager;
@end
@protocol SidecarDevice <NSObject>
- (NSString *)name;
@end
@protocol SidecarConfig <NSObject>
- (NSNumber *)displayID;
@end
@protocol SidecarManager <NSObject>
- (NSArray<id<SidecarDevice>> *)devices;
- (NSArray<id<SidecarDevice>> *)connectedDevices;
- (id<SidecarConfig>)configForDevice:(id<SidecarDevice>)device;
- (void)connectToDevice:(id<SidecarDevice>)device completion:(void (^)(NSError *))completion;
- (void)disconnectFromDevice:(id<SidecarDevice>)device completion:(void (^)(NSError *))completion;
@end

static int fail(int code, NSString *message) {
    fprintf(stderr, "%s\n", message.UTF8String);
    return code;
}

static NSArray<NSNumber *> *onlineDisplays(void) {
    uint32_t count = 0;
    if (CGGetOnlineDisplayList(0, NULL, &count) != kCGErrorSuccess) return @[];
    CGDirectDisplayID *displays = calloc(MAX(count, 1), sizeof(*displays));
    if (!displays) return @[];
    NSMutableArray *result = [NSMutableArray array];
    if (CGGetOnlineDisplayList(count, displays, &count) == kCGErrorSuccess)
        for (uint32_t i = 0; i < count; i++) [result addObject:@(displays[i])];
    free(displays);
    return result;
}

static CGDirectDisplayID deviceDisplay(id<SidecarManager> manager, id<SidecarDevice> device) {
    id<SidecarConfig> config = [manager configForDevice:device];
    if (![config respondsToSelector:@selector(displayID)]) return kCGNullDirectDisplay;
    return [config displayID].unsignedIntValue;
}

static CGDirectDisplayID sourceDisplay(id<SidecarManager> manager) {
    NSMutableSet *sidecarIDs = [NSMutableSet set];
    for (id<SidecarDevice> device in [manager connectedDevices])
        [sidecarIDs addObject:@(deviceDisplay(manager, device))];
    NSArray *displays = onlineDisplays();
    CGDirectDisplayID main = CGMainDisplayID();
    if ([displays containsObject:@(main)] && ![sidecarIDs containsObject:@(main)]) return main;
    for (NSNumber *display in displays)
        if (![sidecarIDs containsObject:display]) return display.unsignedIntValue;
    return kCGNullDirectDisplay;
}

static BOOL mirroredTogether(CGDirectDisplayID a, CGDirectDisplayID b) {
    if (!a || !b || a == b) return NO;
    CGDirectDisplayID primaryA = CGDisplayMirrorsDisplay(a);
    CGDirectDisplayID primaryB = CGDisplayMirrorsDisplay(b);
    return (primaryA ? primaryA : a) == (primaryB ? primaryB : b);
}

static void poll(void) {
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
}

static CGDisplayModeRef copyPreferredMode(CGDirectDisplayID display) {
    NSDictionary *options = @{(__bridge NSString *)kCGDisplayShowDuplicateLowResolutionModes: @YES};
    CFArrayRef modes = CGDisplayCopyAllDisplayModes(display, (__bridge CFDictionaryRef)options);
    CGDisplayModeRef preferred = NULL;
    int bestRank = -1;
    if (!modes) return NULL;
    for (CFIndex i = 0; i < CFArrayGetCount(modes); i++) {
        CGDisplayModeRef mode = (CGDisplayModeRef)CFArrayGetValueAtIndex(modes, i);
        uint32_t flags = CGDisplayModeGetIOFlags(mode);
        if (!(flags & kDisplayModeNativeFlag) || !CGDisplayModeIsUsableForDesktopGUI(mode)) continue;
        int rank = ((flags & kDisplayModeDefaultFlag) ? 2 : 0) +
                   (CGDisplayModeGetPixelWidth(mode) > CGDisplayModeGetWidth(mode) ? 1 : 0);
        if (rank > bestRank) {
            preferred = mode;
            bestRank = rank;
        }
    }
    if (preferred) CGDisplayModeRetain(preferred);
    CFRelease(modes);
    return preferred;
}

static BOOL sameResolution(CGDisplayModeRef a, CGDisplayModeRef b) {
    return a && b && CGDisplayModeGetWidth(a) == CGDisplayModeGetWidth(b) &&
        CGDisplayModeGetHeight(a) == CGDisplayModeGetHeight(b) &&
        CGDisplayModeGetPixelWidth(a) == CGDisplayModeGetPixelWidth(b) &&
        CGDisplayModeGetPixelHeight(a) == CGDisplayModeGetPixelHeight(b);
}

static BOOL ipadPrimary(CGDirectDisplayID ipad, CGDirectDisplayID macDisplay) {
    return ipad && macDisplay && CGMainDisplayID() == ipad &&
        CGDisplayMirrorsDisplay(ipad) == kCGNullDirectDisplay &&
        CGDisplayMirrorsDisplay(macDisplay) == ipad;
}

static int ensureMirroring(CGDirectDisplayID target, CGDirectDisplayID source) {
    if (!target || !source || target == source)
        return fail(6, @"Connected, but a Mac display could not be identified for mirroring.");
    CGDisplayModeRef preferred = copyPreferredMode(target);
    if (!preferred) return fail(6, @"Connected, but the iPad's native display mode could not be identified.");
    CGDisplayModeRef current = CGDisplayCopyDisplayMode(target);
    BOOL correct = ipadPrimary(target, source) && sameResolution(current, preferred);
    CGDisplayModeRelease(current);
    if (correct) {
        CGDisplayModeRelease(preferred);
        return 0;
    }
    CGDisplayConfigRef config = NULL;
    CGError error = CGBeginDisplayConfiguration(&config);
    if (error == kCGErrorSuccess) {
        // The iPad owns the desktop; the Mac's monitor mirrors the iPad.
        error = CGConfigureDisplayMirrorOfDisplay(config, target, kCGNullDirectDisplay);
        if (error == kCGErrorSuccess)
            error = CGConfigureDisplayWithDisplayMode(config, target, preferred, NULL);
        if (error == kCGErrorSuccess)
            error = CGConfigureDisplayOrigin(config, target, 0, 0);
        if (error == kCGErrorSuccess)
            error = CGConfigureDisplayMirrorOfDisplay(config, source, target);
        if (error == kCGErrorSuccess)
            error = CGCompleteDisplayConfiguration(config, kCGConfigureForSession);
        else
            CGCancelDisplayConfiguration(config);
    }
    if (error != kCGErrorSuccess) {
        CGDisplayModeRelease(preferred);
        return fail(6, [NSString stringWithFormat:@"Connected, but mirroring failed (CoreGraphics %d).", error]);
    }
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:5];
    while ([deadline timeIntervalSinceNow] > 0) {
        current = CGDisplayCopyDisplayMode(target);
        correct = ipadPrimary(target, source) && sameResolution(current, preferred);
        CGDisplayModeRelease(current);
        if (correct) {
            CGDisplayModeRelease(preferred);
            return 0;
        }
        poll();
    }
    CGDisplayModeRelease(preferred);
    return fail(6, @"Connected, but iPad-primary mirroring at the iPad's native resolution could not be verified.");
}

static int run(int argc, const char *argv[]) {
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("0.1.0");
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--help") == 0) {
        puts("Usage: sidecar devices | status NAME | connect NAME | disconnect NAME\n"
             "connect makes the iPad primary at its native Retina resolution; the Mac monitor mirrors it.\n"
             "An existing Sidecar connection stays active.\n"
             "The Mac must be logged in; the iPad must be awake and unlocked.\n"
             "Exit codes: 1 arguments, 2 device, 3 framework, 4 connection, 5 timeout, 6 mirroring.");
        return 0;
    }
    NSString *command = argc > 1 ? @(argv[1]) : @"";
    BOOL list = [command isEqualToString:@"devices"];
    if ((!list && ![@[@"connect", @"disconnect", @"status"] containsObject:command]) ||
        argc != (list ? 2 : 3) || (!list && !strlen(argv[2])))
        return fail(1, @"Usage: sidecar devices | status NAME | connect NAME | disconnect NAME");

    if (!dlopen("/System/Library/PrivateFrameworks/SidecarCore.framework/SidecarCore", RTLD_NOW))
        return fail(3, @"SidecarCore could not be loaded on this version of macOS.");
    Class factory = NSClassFromString(@"SidecarDisplayManager");
    if (![factory respondsToSelector:@selector(sharedManager)])
        return fail(3, @"SidecarDisplayManager is unavailable on this version of macOS.");
    id<SidecarManager> manager = [factory sharedManager];
    for (NSString *name in @[@"devices", @"connectedDevices", @"configForDevice:",
                             @"connectToDevice:completion:", @"disconnectFromDevice:completion:"])
        if (![manager respondsToSelector:NSSelectorFromString(name)])
            return fail(3, [@"Unsupported SidecarCore selector: " stringByAppendingString:name]);
    NSMutableOrderedSet *devices = [NSMutableOrderedSet orderedSetWithArray:[manager devices]];
    [devices addObjectsFromArray:[manager connectedDevices]];
    if (list) {
        for (id<SidecarDevice> device in devices) puts([device name].UTF8String);
        return devices.count ? 0 : fail(2, @"No Sidecar devices found. Wake and unlock the iPad, then retry.");
    }

    NSString *name = @(argv[2]);
    NSMutableArray *matches = [NSMutableArray array];
    for (id<SidecarDevice> device in devices)
        if ([[device name] isEqualToString:name]) [matches addObject:device];
    if (matches.count != 1)
        return fail(2, matches.count ? @"Multiple devices have that name. Rename the target iPad." :
                    @"Device not found. Run 'sidecar devices' and use the exact name; keep the iPad unlocked.");
    id<SidecarDevice> target = matches.firstObject;
    BOOL connected = [[manager connectedDevices] containsObject:target];
    CGDirectDisplayID source = sourceDisplay(manager);
    if ([command isEqualToString:@"status"]) {
        CGDirectDisplayID ipad = deviceDisplay(manager, target);
        NSString *state = !connected ? @"Disconnected" : ipadPrimary(ipad, source) ?
            @"iPad primary; Mac display mirrors iPad" :
            mirroredTogether(ipad, source) ? @"Mirroring, Mac display primary" : @"Connected, extended display";
        printf("%s: %s\n", state.UTF8String, name.UTF8String);
        if (connected) {
            CGDisplayModeRef mode = CGDisplayCopyDisplayMode(ipad);
            if (mode) printf("iPad desktop: %zux%zu; backing pixels: %zux%zu\n", CGDisplayModeGetWidth(mode),
                             CGDisplayModeGetHeight(mode), CGDisplayModeGetPixelWidth(mode), CGDisplayModeGetPixelHeight(mode));
            CGDisplayModeRelease(mode);
        }
        return 0;
    }
    BOOL connect = [command isEqualToString:@"connect"];
    if (connected != connect) {
        dispatch_semaphore_t finished = dispatch_semaphore_create(0);
        __block NSError *failure = nil;
        void (^completion)(NSError *) = ^(NSError *error) {
            failure = error;
            dispatch_semaphore_signal(finished);
        };
        if (connect) [manager connectToDevice:target completion:completion];
        else [manager disconnectFromDevice:target completion:completion];
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:30];
        while (dispatch_semaphore_wait(finished, DISPATCH_TIME_NOW) != 0) {
            if ([deadline timeIntervalSinceNow] <= 0)
                return fail(5, @"Sidecar timed out. Check 'sidecar status NAME' before retrying.");
            poll();
        }
        if (failure) {
            NSString *hint = failure.code == -203 ? @" Wake and unlock the iPad, then retry." : @"";
            return fail(4, [NSString stringWithFormat:@"Sidecar: %@ (%@ %ld).%@",
                            failure.localizedDescription, failure.domain, (long)failure.code, hint]);
        }
    }
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:5];
    while ([[manager connectedDevices] containsObject:target] != connect ||
           (connect && (!deviceDisplay(manager, target) ||
                        ![onlineDisplays() containsObject:@(deviceDisplay(manager, target))]))) {
        if ([deadline timeIntervalSinceNow] <= 0)
            return fail(5, @"Sidecar returned success, but the display state could not be verified.");
        poll();
    }
    if (connect) {
        int result = ensureMirroring(deviceDisplay(manager, target), source);
        if (result) return result;
    }
    printf("%s: %s\n", connect ? "iPad primary; Mac display mirrors iPad" : "Disconnected", name.UTF8String);
    return 0;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        @try { return run(argc, argv); }
        @catch (NSException *exception) {
            return fail(3, [@"SidecarCore is incompatible: " stringByAppendingString:exception.reason ?: exception.name]);
        }
    }
}
