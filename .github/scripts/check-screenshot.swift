import AppKit
import Foundation

// Check the rendered system-background gutter, rather than simctl's exit code alone.
guard CommandLine.arguments.count == 3,
      let data = FileManager.default.contents(atPath: CommandLine.arguments[1]),
      let bitmap = NSBitmapImageRep(data: data), bitmap.pixelsWide > 20 else {
    fputs("Cannot read the rendered Simulator screenshot.\n", stderr)
    exit(1)
}
let colors = [1, 2, 3].compactMap { part in
    bitmap.colorAt(x: 10, y: bitmap.pixelsHigh * part / 4)?.usingColorSpace(.sRGB)
}
guard colors.count == 3 else { exit(1) }
let brightness = colors.map { ($0.redComponent + $0.greenComponent + $0.blueComponent) / 3 }.reduce(0, +) / 3
let expected = CommandLine.arguments[2]
let passed = expected == "dark" ? brightness < 0.3 : expected == "light" && brightness > 0.7
print("Rendered appearance:", expected, "background brightness:", brightness, "passed:", passed)
exit(passed ? 0 : 1)
