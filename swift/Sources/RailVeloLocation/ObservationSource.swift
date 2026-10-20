import Foundation
import RailVeloCore

/// Both sensor and replay adapters deliver the same immutable observations.
@MainActor public protocol ObservationSource: AnyObject {
    var onObservations: (([Observation]) -> Void)? { get set }
    var onFailure: ((String) -> Void)? { get set }
    func start()
    func stop()
}

#if canImport(CoreLocation)
extension CoreLocationSource: ObservationSource {}
#endif

/// A bounded fixture is read once; observation timestamps are never replaced by wall time.
@MainActor public final class ReplayObservationSource: ObservationSource {
    public var onObservations: (([Observation]) -> Void)?
    public var onFailure: ((String) -> Void)?
    public var onCompletion: (() -> Void)?
    private let observations: [Observation]
    private let rate: Double
    private var index = 0
    private var task: Task<Void, Never>?
    public init(url: URL, rate: Double = 25) throws {
        guard rate.isFinite, rate > 0 else { throw ReplayError.invalidRate }
        let data = try Data(contentsOf: url)
        guard data.count <= 20_000_000 else { throw ReplayError.tooLarge }
        let decoder = RailVeloJSON.decoder()
        let decoded = try data.split(separator: 10).filter { !$0.isEmpty }.map {
            try decoder.decode(Observation.self, from: Data($0))
        }
        guard !decoded.isEmpty,
              decoded.allSatisfy({ $0.timestamp.isFinite }),
              zip(decoded, decoded.dropFirst()).allSatisfy({ $0.timestamp < $1.timestamp }) else {
            throw ReplayError.invalidTimestamps
        }
        self.observations = decoded; self.rate = rate
    }
    public func start() {
        guard task == nil else { return }
        task = Task { [weak self] in
            guard let self else { return }
            while self.index < self.observations.count && !Task.isCancelled {
                let current = self.observations[self.index]
                self.index += 1
                self.onObservations?([current])
                if self.index < self.observations.count {
                    let seconds = (self.observations[self.index].timestamp - current.timestamp) / self.rate
                    do { try await Task.sleep(nanoseconds: UInt64(min(seconds, 86_400) * 1_000_000_000)) }
                    catch { return }
                }
            }
            if !Task.isCancelled { self.task = nil; self.onCompletion?() }
        }
    }
    public func stop() { task?.cancel(); task = nil }
    public enum ReplayError: Error { case invalidRate, tooLarge, invalidTimestamps }
}
