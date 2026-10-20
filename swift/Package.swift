// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "RailVelo",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "RailVeloCore", targets: ["RailVeloCore"]),
        .library(name: "RailVeloSQLite", targets: ["RailVeloSQLite"]),
        .library(name: "RailVeloLocation", targets: ["RailVeloLocation"]),
        .library(name: "RailVeloRecording", targets: ["RailVeloRecording"]),
        .executable(name: "railvelo-replay", targets: ["RailVeloReplay"])
    ],
    targets: [
        .target(name: "RailVeloCore"),
        // SDK SQLite must be used when cross-compiling iOS. Host pkg-config
        // flags can accidentally select Homebrew's macOS-only dylib.
        .systemLibrary(name: "CSQLite", providers: [.apt(["libsqlite3-dev"])]),
        .target(name: "RailVeloSQLite", dependencies: ["RailVeloCore", "CSQLite"]),
        .target(name: "RailVeloLocation", dependencies: ["RailVeloCore"]),
        .target(name: "RailVeloRecording", dependencies: ["RailVeloCore", "CSQLite"]),
        .executableTarget(name: "RailVeloReplay", dependencies: ["RailVeloCore", "RailVeloSQLite"]),
        .testTarget(name: "RailVeloCoreTests", dependencies: ["RailVeloCore", "RailVeloSQLite"]),
        .testTarget(name: "RailVeloRecordingTests", dependencies: ["RailVeloCore", "RailVeloRecording", "CSQLite"])
    ]
)
