import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("\(message)\n".utf8))
    exit(1)
}

guard CommandLine.arguments.count == 2 else { fail("Expected check or the virtual display ID") }
var count: UInt32 = 0
guard CGGetActiveDisplayList(0, nil, &count) == .success else { fail("Cannot list displays") }
var displays = [CGDirectDisplayID](repeating: 0, count: Int(count))
guard CGGetActiveDisplayList(count, &displays, &count) == .success else { fail("Cannot list displays") }
if CommandLine.arguments[1] == "check" {
    guard displays.count == 1, CGDisplayIsBuiltin(displays[0]) != 0 else { fail("A single built-in display is required") }
    exit(0)
}
guard let virtualID = UInt32(CommandLine.arguments[1]),
      displays.count == 2,
      displays.contains(virtualID),
      let builtIn = displays.first(where: { CGDisplayIsBuiltin($0) != 0 }),
      builtIn != virtualID else { fail("A single built-in display is required") }
let physical = CGDisplayBounds(builtIn)
let virtual = CGDisplayBounds(virtualID)
guard virtual.width >= 1180, virtual.height >= 880 else { fail("Virtual display is too small") }
var config: CGDisplayConfigRef?
guard CGBeginDisplayConfiguration(&config) == .success else { fail("Cannot begin display configuration") }
guard CGConfigureDisplayOrigin(config, virtualID, Int32(physical.maxX), Int32(physical.maxY)) == .success else {
    CGCancelDisplayConfiguration(config)
    fail("Cannot arrange virtual display")
}
guard CGCompleteDisplayConfiguration(config, .forSession) == .success else { fail("Cannot apply display configuration") }
let placed = CGDisplayBounds(virtualID)
guard CGDisplayBounds(builtIn) == physical,
      placed.origin.x == physical.maxX, placed.origin.y == physical.maxY else { fail("Unexpected display arrangement") }
let result: [String: Int] = ["left": Int(placed.minX) + 40, "top": Int(placed.minY) + 40]
print(String(data: try JSONSerialization.data(withJSONObject: result), encoding: .utf8)!)
