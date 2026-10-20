import Foundation
import RailVeloCore

public enum RideMode: String, Codable, Sendable { case live, replay }

public struct SpeedPoint: Identifiable, Sendable {
    public let id: String
    public let timestamp: Double
    public let speedKmh: Double?
    public let reason: String?
    public let segment: Int
    public init(id: String, timestamp: Double, speedKmh: Double?, reason: String?, segment: Int) {
        self.id = id; self.timestamp = timestamp; self.speedKmh = speedKmh
        self.reason = reason; self.segment = segment
    }
}

public struct RecordedSample: Sendable {
    public let observation: Observation
    public let result: MatchResult
    public let speedKmh: Double?
    public let exclusionReason: String?
    public init(observation: Observation, result: MatchResult, speedKmh: Double?, exclusionReason: String?) {
        self.observation = observation; self.result = result
        self.speedKmh = speedKmh; self.exclusionReason = exclusionReason
    }
}

public struct RideSummary: Identifiable, Sendable {
    public let id: String
    public let mode: RideMode
    public let startedAt: Double
    public let endedAt: Double?
    public let maximumSpeedKmh: Double
    public let status: String
    public init(id: String, mode: RideMode, startedAt: Double, endedAt: Double?, maximumSpeedKmh: Double, status: String) {
        self.id = id; self.mode = mode; self.startedAt = startedAt; self.endedAt = endedAt
        self.maximumSpeedKmh = maximumSpeedKmh; self.status = status
    }
}

/// Own on one serial executor. Displayed speed is measured speed, never matcher prediction.
public final class RideProcessor {
    private let matcher: MapMatcher
    private var lastTimestamp: Double?
    private var lastSpeed: (timestamp: Double, value: Double, accuracy: Double)?
    private var lastLocation: (timestamp: Double, lat: Double, lon: Double, accuracy: Double)?
    public private(set) var maximumSpeedKmh = 0.0

    public init(network: Network) { matcher = MapMatcher(network: network) }

    /// Pause/resume breaks arrival dwell and speed continuity; the session maximum remains.
    public func resetContinuity() {
        matcher.reset(); lastSpeed = nil; lastLocation = nil
    }

    public func process(_ observation: Observation, receivedAt: Double? = nil) -> RecordedSample {
        let t = observation.timestamp
        if !t.isFinite || (lastTimestamp != nil && t <= lastTimestamp!) {
            let reason = t.isFinite ? "non_monotonic_timestamp" : "invalid_timestamp"
            return RecordedSample(observation: observation,
                                  result: MatchResult(timestamp: t.isFinite ? t : nil, status: "rejected", reason: reason),
                                  speedKmh: nil, exclusionReason: reason)
        }
        if let receivedAt, observation.timestamp.isFinite {
            let receiptReason: String?
            if !receivedAt.isFinite { receiptReason = "invalid_receipt_timestamp" }
            else if receivedAt - observation.timestamp > 10 { receiptReason = "stale_fix" }
            else if observation.timestamp - receivedAt > 5 { receiptReason = "future_fix" }
            else { receiptReason = nil }
            if let receiptReason {
                return RecordedSample(observation: observation,
                                      result: MatchResult(timestamp: observation.timestamp, status: "rejected", reason: receiptReason),
                                      speedKmh: nil, exclusionReason: receiptReason)
            }
        }
        lastTimestamp = t
        var reason: String?
        if reason == nil {
            if observation.lat == nil && observation.lon == nil { reason = "missing_fix" }
            else if let lat = observation.lat, let lon = observation.lon,
                    lat.isFinite, lon.isFinite, abs(lat) <= 90, abs(lon) <= 180 {} else { reason = "invalid_coordinates" }
        }
        if reason == nil && (!observation.horizontalAccuracyM.isFinite || observation.horizontalAccuracyM <= 0 || observation.horizontalAccuracyM > 150) {
            reason = "poor_accuracy"
        }
        if reason == nil {
            if let speed = observation.speedMps, speed.isFinite, speed >= 0, speed <= 60 {} else { reason = "invalid_speed" }
        }
        if reason == nil {
            if let accuracy = observation.speedAccuracyMps, accuracy.isFinite, accuracy >= 0, accuracy <= 8 {} else {
                reason = "poor_speed_accuracy"
            }
        }
        if reason == nil, let speed = observation.speedMps, let accuracy = observation.speedAccuracyMps,
           let previous = lastSpeed {
            let elapsed = t - previous.timestamp
            if elapsed > 0 && elapsed <= 15 && abs(speed - previous.value) > 4 * elapsed + 2 * (accuracy + previous.accuracy) {
                reason = "implausible_acceleration"
            }
        }
        if reason == nil, let speed = observation.speedMps,
           let lat = observation.lat, let lon = observation.lon, let previous = lastLocation {
            let elapsed = t - previous.timestamp
            if elapsed > 0 && elapsed <= 10 {
                let p1 = previous.lat * .pi / 180, p2 = lat * .pi / 180
                let dp = p2 - p1, dl = (lon - previous.lon) * .pi / 180
                let h = pow(sin(dp / 2), 2) + cos(p1) * cos(p2) * pow(sin(dl / 2), 2)
                let distance = 6_371_008.8 * 2 * asin(min(1, sqrt(h)))
                let tolerance = 3 * (previous.accuracy + observation.horizontalAccuracyM) + 15
                if speed * elapsed > distance + tolerance { reason = "speed_position_disagreement" }
            }
        }
        // Keep raw values in history, but do not let an implausible speed bias direction or station events.
        let inferenceObservation: Observation
        if let reason, ["invalid_speed", "poor_speed_accuracy", "implausible_acceleration", "speed_position_disagreement"].contains(reason) {
            inferenceObservation = Observation(timestamp: t, lat: observation.lat, lon: observation.lon,
                                               horizontalAccuracyM: observation.horizontalAccuracyM,
                                               speedMps: nil, speedAccuracyMps: nil, courseDeg: nil)
        } else { inferenceObservation = observation }
        let result = matcher.update(inferenceObservation)
        if result.status == "rejected" { reason = result.reason }
        // A predicted result can follow a rejected jump: prediction does not make that raw fix safe.
        if result.reason.hasPrefix("coordinate_jump") || result.reason.hasPrefix("unreachable_transition") { reason = result.reason }
        let speedKmh: Double?
        if reason == nil, let speed = observation.speedMps, let accuracy = observation.speedAccuracyMps {
            speedKmh = speed * 3.6
            maximumSpeedKmh = max(maximumSpeedKmh, speed * 3.6)
            lastSpeed = (t, speed, accuracy)
        } else { speedKmh = nil }
        // Rejected coordinates must never become the next corroborating position.
        if t.isFinite, result.status != "rejected", !result.reason.hasPrefix("coordinate_jump"),
           !result.reason.hasPrefix("unreachable_transition"), observation.horizontalAccuracyM.isFinite,
           observation.horizontalAccuracyM > 0, observation.horizontalAccuracyM <= 150,
           let lat = observation.lat, let lon = observation.lon,
           lat.isFinite, lon.isFinite, abs(lat) <= 90, abs(lon) <= 180,
           lastLocation == nil || t > lastLocation!.timestamp {
            lastLocation = (t, lat, lon, observation.horizontalAccuracyM)
        }
        return RecordedSample(observation: observation, result: result, speedKmh: speedKmh, exclusionReason: reason)
    }
}
