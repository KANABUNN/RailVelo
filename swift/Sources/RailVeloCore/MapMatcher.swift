import Foundation

private struct State {
    var projection: Projection
    var routeId: String
    var direction: Int
    var score: Double
    var logp = 0.0
    var probability = 0.0
}
private struct Fix {
    var timestamp: Double
    var point: Point
    var accuracy: Double
    var speed: Double
    var state: State
}
private struct ConfirmedFix {
    var timestamp: Double
    var state: State
    var speed: Double
    var accuracy: Double
    var confidence: Double
}

/// Stateful online HMM forward filter. Call update serially, once per observation.
/// Confidence is relative graph support, not a calibrated real-world probability.
public final class MapMatcher {
    public let network: Network
    private let events: StationEventDetector
    private var lastTimestamp: Double?
    private var states: [State] = []
    private var lastFix: Fix?
    private var lastConfirmed: ConfirmedFix?
    private var origin: Point?
    private var accepted = 0
    private var hasMoved = false
    private static let maxSpeed = 60.0
    private static let maxGap = 15.0
    private static let resetGap = 30.0

    public init(network: Network) { self.network = network; events = StationEventDetector(network: network) }
    /// Start an independent trip; timestamp ordering is reset too.
    public func reset() { clearHistory(); lastTimestamp = nil }
    private func clearHistory() {
        states = []; lastFix = nil; lastConfirmed = nil; origin = nil; accepted = 0; hasMoved = false; events.reset()
    }
    private func empty(_ time: Double?, _ status: String, _ reason: String) -> MatchResult {
        MatchResult(timestamp: time, status: status, reason: reason)
    }
    private func logsumexp(_ values: [Double]) -> Double {
        guard let m = values.max(), m.isFinite else { return -.infinity }
        return m + log(values.reduce(0) { $0 + exp($1 - m) })
    }

    public func update(_ observation: Observation) -> MatchResult {
        let t = observation.timestamp
        guard t.isFinite else { return empty(nil, "rejected", "invalid_timestamp") }
        if let lastTimestamp, t <= lastTimestamp { return empty(t, "rejected", "non_monotonic_timestamp") }
        if observation.lat == nil && observation.lon == nil { lastTimestamp = t; return gap(t, reason: "missing_fix") }
        guard let lat = observation.lat, let lon = observation.lon,
              lat.isFinite, lon.isFinite, abs(lat) <= 90, abs(lon) <= 180 else {
            return empty(t, "rejected", "invalid_coordinates")
        }
        lastTimestamp = t
        let accuracy = observation.horizontalAccuracyM
        guard accuracy.isFinite, accuracy > 0, accuracy <= 150 else { return gap(t, reason: "poor_accuracy", rejected: true) }
        let point = Point(lat: lat, lon: lon)
        var speed: Double?
        if let raw = observation.speedMps, raw.isFinite, raw >= 0, raw <= Self.maxSpeed,
           let speedAccuracy = observation.speedAccuracyMps, speedAccuracy.isFinite, speedAccuracy >= 0, speedAccuracy <= 8 {
            speed = raw
        }
        var reason = observation.speedMps.map { $0.isFinite && $0 > Self.maxSpeed } == true ? "speed_ignored" : "observed"
        var course = observation.courseDeg
        if course == nil || !course!.isFinite || course! < 0 || course! >= 360 || speed == nil || speed! < 3 { course = nil }
        if let lastFix, t - lastFix.timestamp > Self.resetGap { clearHistory(); reason = "reacquired" }
        let dt: Double, expectedSpeed: Double
        if let lastFix {
            dt = t - lastFix.timestamp
            let displacement = Geometry.distance(lastFix.point, point)
            if displacement > Self.maxSpeed * dt + max(100, 3 * (accuracy + lastFix.accuracy)) {
                return gap(t, reason: "coordinate_jump", rejected: true)
            }
            expectedSpeed = speed ?? min(Self.maxSpeed, displacement / dt)
        } else { dt = 0; expectedSpeed = speed ?? 0 }
        let projections = network.candidates(point, radius: min(500, max(80, 3 * accuracy)))
        if projections.isEmpty { return gap(t, reason: "off_network") }
        var candidates: [State] = []
        let sigma = max(8, accuracy)
        for projection in projections {
            for routeId in Set(network.edges[projection.edgeId]!.routeIds).sorted() {
                for direction in [1, -1] {
                    var state = State(projection: projection, routeId: routeId, direction: direction, score: 0)
                    var emission = -0.5 * pow(projection.distance / sigma, 2)
                    if let course {
                        let heading = (projection.heading + (direction == -1 ? 180 : 0)).truncatingRemainder(dividingBy: 360)
                        emission -= 0.5 * pow(Geometry.angleDifference(course, heading) / 40, 2)
                    }
                    if !states.isEmpty && lastFix != nil {
                        let terms = states.compactMap { prior -> Double? in
                            let value = transition(prior, state, dt: dt, speed: expectedSpeed, accuracy: accuracy)
                            return value.isFinite ? prior.logp + value : nil
                        }
                        state.score = emission + logsumexp(terms)
                    } else { state.score = emission }
                    if state.score.isFinite { candidates.append(state) }
                }
            }
        }
        if candidates.isEmpty { return gap(t, reason: "unreachable_transition", rejected: true) }
        candidates.sort {
            if $0.score != $1.score { return $0.score > $1.score }
            if $0.projection.edgeId != $1.projection.edgeId { return $0.projection.edgeId < $1.projection.edgeId }
            if $0.routeId != $1.routeId { return $0.routeId < $1.routeId }
            return $0.direction > $1.direction
        }
        candidates = Array(candidates.prefix(24))
        let normalizer = logsumexp(candidates.map { $0.score })
        for i in candidates.indices { candidates[i].logp = candidates[i].score - normalizer; candidates[i].probability = exp(candidates[i].logp) }
        states = candidates
        let best = candidates[0]
        accepted += 1
        if origin == nil { origin = point }
        hasMoved = hasMoved || Geometry.distance(origin!, point) >= 20
        lastFix = Fix(timestamp: t, point: point, accuracy: accuracy, speed: expectedSpeed, state: best)
        var routeMass: [String: Double] = [:], directionMass: [String: Double] = [:]
        var positionMass = 0.0
        for state in candidates {
            routeMass[state.routeId, default: 0] += state.probability
            if let position = network.routePosition(edgeId: state.projection.edgeId, offset: state.projection.offset, routeId: state.routeId) {
                directionMass["\(state.routeId)|\(position.orientation * state.direction)", default: 0] += state.probability
            }
            if Geometry.distance(best.projection.point, state.projection.point) <= 50 { positionMass += state.probability }
        }
        let location = network.routePosition(edgeId: best.projection.edgeId, offset: best.projection.offset, routeId: best.routeId)
        let dirMass = location.map { directionMass["\(best.routeId)|\($0.orientation * best.direction)", default: 0] } ?? 0
        let routeSupport = routeMass[best.routeId, default: 0]
        let confidence = min(positionMass, min(routeSupport, dirMass))
        let resolved = location != nil && accepted >= 3 && hasMoved
            && routeSupport >= 0.85 && dirMass >= 0.8 && positionMass >= 0.65
            && best.projection.distance <= max(50, 2 * accuracy)
        var result = empty(t, resolved ? "matched" : "uncertain", resolved ? reason : "insufficient_support")
        result.edgeId = best.projection.edgeId; result.offsetM = best.projection.offset
        result.lat = best.projection.point.lat; result.lon = best.projection.point.lon
        result.confidence = confidence; result.uncertaintyM = max(accuracy, best.projection.distance)
        result.candidates = candidates.map {
            MatchCandidate(edgeId: $0.projection.edgeId, routeId: $0.routeId, direction: $0.direction,
                           offsetM: $0.projection.offset, probability: $0.probability)
        }
        if resolved, let location {
            decorate(&result, best)
            result.events = events.update(timestamp: t, routeId: best.routeId, measure: location.measure,
                                          direction: location.orientation * best.direction, speed: expectedSpeed, confidence: confidence)
            lastConfirmed = ConfirmedFix(timestamp: t, state: best, speed: expectedSpeed, accuracy: accuracy, confidence: confidence)
        } else { events.reset(); lastConfirmed = nil }
        return result
    }

    private func transition(_ a: State, _ b: State, dt: Double, speed: Double, accuracy: Double) -> Double {
        let ea = network.edges[a.projection.edgeId]!, eb = network.edges[b.projection.edgeId]!
        let delta = b.projection.offset - a.projection.offset
        var penalty = 0.0, distance = 0.0
        if ea.id == eb.id && a.direction == b.direction && delta * Double(a.direction) >= -20 {
            distance = abs(delta)
            if delta * Double(a.direction) < 0 { penalty += speed >= 3 ? 4 : 0 }
        } else if ea.id == eb.id && a.direction != b.direction {
            distance = abs(delta); penalty += speed >= 3 ? 4 : 8
        } else {
            let exit = a.direction == 1 ? ea.toNode : ea.fromNode
            let entry = b.direction == 1 ? eb.fromNode : eb.toNode
            let gate = Self.maxSpeed * dt + 3 * (lastFix!.accuracy + accuracy) + 30
            distance = a.direction == 1 ? ea.lengthM - a.projection.offset : a.projection.offset
            distance += network.shortestDistance(from: exit, to: entry, limit: gate)
            distance += b.direction == 1 ? b.projection.offset : eb.lengthM - b.projection.offset
        }
        if a.routeId != b.routeId { penalty += 1.5 }
        let previousAccuracy = lastFix!.accuracy
        if distance > Self.maxSpeed * dt + 3 * (previousAccuracy + accuracy) + 30 { return -.infinity }
        let expected = speed * dt
        let beta = max(20, 0.35 * expected + previousAccuracy + accuracy + 3 * dt)
        return -abs(distance - expected) / beta - penalty
    }

    private func decorate(_ result: inout MatchResult, _ state: State) {
        guard let location = network.routePosition(edgeId: state.projection.edgeId, offset: state.projection.offset, routeId: state.routeId),
              let route = network.routes[state.routeId] else { return }
        let measure = location.measure, direction = location.orientation * state.direction
        result.routeId = state.routeId; result.direction = direction
        result.directionLabel = direction == 1 ? route.forwardLabel : route.reverseLabel
        let stations = network.routeStations[state.routeId] ?? []
        let ordered = direction == 1 ? stations : Array(stations.reversed())
        var previous: RouteStation?, upcoming: RouteStation?
        for station in ordered {
            if (station.measureM - measure) * Double(direction) >= -0.01 { upcoming = station; break }
            previous = station
        }
        result.previousStationId = previous?.stationId; result.nextStationId = upcoming?.stationId
        if let upcoming { result.distanceToNextM = max(0, (upcoming.measureM - measure) * Double(direction)) }
        if let previous, let upcoming {
            let length = abs(upcoming.measureM - previous.measureM)
            result.progress = max(0, min(1, abs(measure - previous.measureM) / length))
        }
    }

    private func gap(_ t: Double, reason: String, rejected: Bool = false) -> MatchResult {
        events.reset()
        let failedStatus = rejected ? "rejected" : "lost"
        guard let confirmed = lastConfirmed else { return empty(t, failedStatus, reason) }
        let elapsed = t - confirmed.timestamp
        let uncertainty = confirmed.accuracy + 5 * elapsed + 0.5 * elapsed * elapsed
        guard elapsed <= Self.maxGap, uncertainty <= 120 else { return empty(t, failedStatus, reason) }
        var state = confirmed.state
        var remaining = confirmed.speed * elapsed
        var visited = Set<String>()
        while remaining > 0 {
            let edge = network.edges[state.projection.edgeId]!
            let available = state.direction == 1 ? edge.lengthM - state.projection.offset : state.projection.offset
            if remaining <= available {
                let offset = state.projection.offset + Double(state.direction) * remaining
                state.projection = Projection(edgeId: edge.id, offset: offset, point: network.geometry[edge.id]!.point(at: offset), distance: 0, heading: 0)
                break
            }
            remaining -= available
            let node = state.direction == 1 ? edge.toNode : edge.fromNode
            let options = (network.adjacency[node] ?? []).filter { $0.edge != edge.id }
            if options.count != 1 || visited.contains(edge.id) { return empty(t, failedStatus, reason + ":ambiguous_continuation") }
            visited.insert(edge.id)
            let next = network.edges[options[0].edge]!
            guard next.routeIds.contains(state.routeId) else { return empty(t, "lost", reason + ":route_boundary") }
            state.direction = next.fromNode == node ? 1 : -1
            let offset = state.direction == 1 ? 0.0 : next.lengthM
            state.projection = Projection(edgeId: next.id, offset: offset, point: network.geometry[next.id]!.point(at: offset), distance: 0, heading: 0)
        }
        let point = network.geometry[state.projection.edgeId]!.point(at: state.projection.offset)
        var result = empty(t, "predicted", reason)
        result.edgeId = state.projection.edgeId; result.offsetM = state.projection.offset
        result.lat = point.lat; result.lon = point.lon; result.uncertaintyM = uncertainty
        result.confidence = confirmed.confidence * exp(-elapsed / 10)
        decorate(&result, state)
        return result
    }
}
