import AppKit
import CoreGraphics
import Foundation

switch CommandLine.arguments[1] {
case "capture":
    let app = NSWorkspace.shared.frontmostApplication!
    let point = CGEvent(source: nil)!.location
    print("\(app.processIdentifier) \(point.x) \(point.y)")
case "sample":
    while true {
        let app = NSWorkspace.shared.frontmostApplication
        print("\(Date().timeIntervalSince1970) \(app?.localizedName ?? "unknown") [\(app?.processIdentifier ?? 0)]")
        fflush(stdout)
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
case "restore":
    let pid = pid_t(CommandLine.arguments[2])!
    let x = Double(CommandLine.arguments[3])!
    let y = Double(CommandLine.arguments[4])!
    NSRunningApplication(processIdentifier: pid)?.activate(options: [])
    CGWarpMouseCursorPosition(CGPoint(x: x, y: y))
default:
    fatalError("Expected capture, sample, or restore")
}
