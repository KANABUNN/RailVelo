// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "RailVelo",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "RailVeloCore", targets: ["RailVeloCore"]),
        .library(name: "RailVeloSQLite", targets: ["RailVeloSQLite"]),
        .library(name: "RailVeloLocation", targets: ["RailVeloLocation"]),
        .executable(name: "railvelo-replay", targets: ["RailVeloReplay"])
    ],
    targets: [
        .target(name: "RailVeloCore"),
        .systemLibrary(name: "CSQLite", pkgConfig: "sqlite3",
                       providers: [.brew(["sqlite3"]), .apt(["libsqlite3-dev"])]),
        .target(name: "RailVeloSQLite", dependencies: ["RailVeloCore", "CSQLite"]),
        .target(name: "RailVeloLocation", dependencies: ["RailVeloCore"]),
        .executableTarget(name: "RailVeloReplay", dependencies: ["RailVeloCore", "RailVeloSQLite"]),
        .testTarget(name: "RailVeloCoreTests", dependencies: ["RailVeloCore", "RailVeloSQLite"])
    ]
)
