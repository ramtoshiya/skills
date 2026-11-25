#import <AppKit/AppKit.h>
#include <stdio.h>

int main(void) {
    @autoreleasepool {
        [NSApplication.sharedApplication setActivationPolicy:NSApplicationActivationPolicyProhibited];
        // A denied process still exits normally and sees no screen. Counting it would report the leak as fixed.
        if (NSScreen.screens.count == 0) {
            fputs("windowserver-ports-probe: no screen is visible, so WindowServer was not reached\n", stderr);
            return 1;
        }
    }
    return 0;
}
