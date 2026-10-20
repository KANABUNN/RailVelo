import Foundation

private struct PassageKey: Hashable {
    let routeId: String
    let stationId: String
    let direction: Int
}

/// Dwell alone cannot establish arrival: a recent approach from outside is required.
final class StationEventDetector {
    private let network: Network
    private var previous: (time: Double, route: String, measure: Double, speed: Double, direction: Int)?
    private var outside: [String: Double] = [:]
    private var stop: (time: Double, measure: Double)?
    private var arrived: (station: String, measure: Double)?
    private var between = false
    private var recentMotion: Double?
    private var movingSince: Double?
    private var passed = Set<PassageKey>()
    private var served = Set<String>()
    private var halted = Set<String>()
    // Preserve crossing order when more than one station is pending.
    private var pendingPasses: [(key: PassageKey, event: StationEvent)] = []

    init(network: Network) { self.network = network }
    func reset() {
        previous = nil; outside = [:]; stop = nil; arrived = nil; between = false
        recentMotion = nil; movingSince = nil; passed = []; served = []; halted = []; pendingPasses = []
    }
    func update(timestamp: Double, routeId: String, measure: Double, direction: Int,
                speed: Double, confidence: Double) -> [StationEvent] {
        var events: [StationEvent] = []
        var prior = previous
        if let p = prior, p.route != routeId || timestamp - p.time > 10 { reset(); prior = nil }
        let stations = network.routeStations[routeId] ?? []
        let nearby = stations.first { abs(measure - $0.measureM) <= $0.radiusM }
        for station in stations where abs(measure - station.measureM) > station.radiusM + 20 {
            outside[station.stationId] = timestamp
            served.remove(station.stationId)
            halted.remove(station.stationId)
            passed.remove(PassageKey(routeId: routeId, stationId: station.stationId, direction: direction))
        }
        if speed >= 2 { recentMotion = timestamp }
        func event(_ type: String, _ time: Double, _ station: String?) -> StationEvent {
            StationEvent(type: type, timestamp: time, stationId: station, confidence: min(0.95, confidence))
        }
        if speed <= 0.8 {
            movingSince = nil
            if let nearby {
                halted.insert(nearby.stationId)
                pendingPasses.removeAll { $0.key.stationId == nearby.stationId }
            }
            if stop == nil || abs(measure - stop!.measure) > 30 { stop = (timestamp, measure) }
            let dwell = timestamp - stop!.time
            if let nearby, dwell >= 12, arrived == nil,
               abs(measure - nearby.measureM) <= min(50, nearby.radiusM * 0.5),
               let lastOutside = outside[nearby.stationId],
               (0...90).contains(stop!.time - lastOutside),
               let recentMotion, stop!.time - recentMotion <= 30 {
                arrived = (nearby.stationId, stop!.measure)
                served.insert(nearby.stationId)
                events.append(event("arrival", stop!.time, nearby.stationId))
            } else if nearby == nil, dwell >= 20, !between,
                      let recentMotion, stop!.time - recentMotion <= 30 {
                between = true
                events.append(event("between_station_stop", stop!.time, nil))
            }
        } else if speed >= 2 {
            if movingSince == nil { movingSince = timestamp }
            let moving = timestamp - movingSince! >= 3
            if moving, let arrived, abs(measure - arrived.measure) >= 25 {
                events.append(event("departure", movingSince!, arrived.station)); self.arrived = nil
            }
            if moving && between { events.append(event("resume", movingSince!, nil)); between = false }
            stop = nil
        } else { movingSince = nil; stop = nil }
        if let prior, speed >= 2, prior.speed >= 2, direction == prior.direction {
            for station in stations {
                let key = PassageKey(routeId: routeId, stationId: station.stationId, direction: direction)
                let a = prior.measure, b = measure
                let crossed = direction == 1 ? a < station.measureM && station.measureM <= b
                    : b <= station.measureM && station.measureM < a
                if crossed, !passed.contains(key), !served.contains(station.stationId), !halted.contains(station.stationId),
                   arrived == nil || arrived!.station != station.stationId, stop == nil {
                    let time = prior.time + (timestamp - prior.time) * abs((station.measureM - a) / (b - a))
                    let value = event("pass", time, station.stationId)
                    if let index = pendingPasses.firstIndex(where: { $0.key == key }) {
                        pendingPasses[index].event = value
                    } else { pendingPasses.append((key, value)) }
                }
            }
        }
        var retained: [(key: PassageKey, event: StationEvent)] = []
        for pending in pendingPasses {
            let key = pending.key
            guard key.routeId == routeId, key.direction == direction,
                  let station = stations.first(where: { $0.stationId == key.stationId }) else { continue }
            if (measure - station.measureM) * Double(direction) > station.radiusM + 20 {
                if !served.contains(key.stationId) && !halted.contains(key.stationId) {
                    events.append(pending.event); passed.insert(key)
                }
            } else { retained.append(pending) }
        }
        pendingPasses = retained
        previous = (timestamp, routeId, measure, speed, direction)
        return events
    }
}
