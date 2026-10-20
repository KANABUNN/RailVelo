import Foundation
import RailVeloCore
import RailVeloSQLite
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

do {
    var options: [String: String] = [:]
    var arguments = Array(CommandLine.arguments.dropFirst())
    while !arguments.isEmpty {
        let flag = arguments.removeFirst()
        guard ["--network", "--input", "--output"].contains(flag), !arguments.isEmpty else {
            throw NetworkError.invalid("Usage: railvelo-replay --network network.json|railway.sqlite --input observations.jsonl [--output results.jsonl]")
        }
        options[flag] = arguments.removeFirst()
    }
    guard let networkPath = options["--network"], let inputPath = options["--input"] else {
        throw NetworkError.invalid("--network and --input are required")
    }
    let networkURL = URL(fileURLWithPath: networkPath)
    let network = try ["sqlite", "db"].contains(networkURL.pathExtension.lowercased())
        ? SQLiteNetworkLoader.load(url: networkURL) : Network(jsonURL: networkURL)
    let matcher = MapMatcher(network: network)
    let data = inputPath == "-" ? FileHandle.standardInput.readDataToEndOfFile() : try Data(contentsOf: URL(fileURLWithPath: inputPath))
    guard let text = String(data: data, encoding: .utf8) else { throw NetworkError.invalid("Input is not UTF-8") }
    var output = Data()
    for (index, line) in text.split(whereSeparator: \.isNewline).enumerated() {
        do {
            let observation = try RailVeloJSON.decoder().decode(Observation.self, from: Data(line.utf8))
            output.append(try RailVeloJSON.encoder().encode(matcher.update(observation)))
            output.append(0x0a)
        } catch { throw NetworkError.invalid("Observation line \(index + 1): \(error)") }
    }
    if let path = options["--output"] { try output.write(to: URL(fileURLWithPath: path), options: .atomic) }
    else { FileHandle.standardOutput.write(output) }
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
