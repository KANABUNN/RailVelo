import Foundation

/// Interchange uses WGS84, metres, m/s and UTC Unix seconds.
public enum RailVeloJSON {
    public static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
    public static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}

public struct Observation: Codable, Sendable {
    public let timestamp: Double
    public let lat: Double?
    public let lon: Double?
    public let horizontalAccuracyM: Double
    public let speedMps: Double?
    public let speedAccuracyMps: Double?
    public let courseDeg: Double?

    public init(timestamp: Double, lat: Double?, lon: Double?, horizontalAccuracyM: Double,
                speedMps: Double? = nil, speedAccuracyMps: Double? = nil, courseDeg: Double? = nil) {
        self.timestamp = timestamp; self.lat = lat; self.lon = lon
        self.horizontalAccuracyM = horizontalAccuracyM; self.speedMps = speedMps
        self.speedAccuracyMps = speedAccuracyMps; self.courseDeg = courseDeg
    }
}

public struct NetworkNode: Codable, Sendable {
    public let id: String
    public let lat: Double
    public let lon: Double
    public init(id: String, lat: Double, lon: Double) { self.id = id; self.lat = lat; self.lon = lon }
}
public struct NetworkEdge: Codable, Sendable {
    public let id: String
    public let fromNode: String
    public let toNode: String
    public let routeIds: [String]
    public let coordinates: [[Double]]
    public let lengthM: Double
    public let pointMeasuresM: [Double]?
    public init(id: String, fromNode: String, toNode: String, routeIds: [String],
                coordinates: [[Double]], lengthM: Double, pointMeasuresM: [Double]? = nil) {
        self.id = id; self.fromNode = fromNode; self.toNode = toNode; self.routeIds = routeIds
        self.coordinates = coordinates; self.lengthM = lengthM; self.pointMeasuresM = pointMeasuresM
    }
}
public struct NetworkRoute: Codable, Sendable {
    public let id: String
    public let name: String
    public let forwardLabel: String
    public let reverseLabel: String
    public init(id: String, name: String, forwardLabel: String, reverseLabel: String) {
        self.id = id; self.name = name; self.forwardLabel = forwardLabel; self.reverseLabel = reverseLabel
    }
}
public struct RouteEdge: Codable, Sendable {
    public let routeId: String
    public let edgeId: String
    public let sequence: Int
    public let direction: Int
    public let startM: Double
    public init(routeId: String, edgeId: String, sequence: Int, direction: Int, startM: Double) {
        self.routeId = routeId; self.edgeId = edgeId; self.sequence = sequence
        self.direction = direction; self.startM = startM
    }
}
public struct NetworkStation: Codable, Sendable {
    public let id: String
    public let name: String
    public init(id: String, name: String) { self.id = id; self.name = name }
}
public struct RouteStation: Codable, Sendable {
    public let routeId: String
    public let stationId: String
    public let sequence: Int
    public let measureM: Double
    public let radiusM: Double
    public init(routeId: String, stationId: String, sequence: Int, measureM: Double, radiusM: Double) {
        self.routeId = routeId; self.stationId = stationId; self.sequence = sequence
        self.measureM = measureM; self.radiusM = radiusM
    }
}
public struct NetworkDocument: Codable, Sendable {
    public let schemaVersion: Int
    public let nodes: [NetworkNode]
    public let edges: [NetworkEdge]
    public let routes: [NetworkRoute]
    public let routeEdges: [RouteEdge]
    public let stations: [NetworkStation]
    public let routeStations: [RouteStation]
    public init(schemaVersion: Int = 1, nodes: [NetworkNode], edges: [NetworkEdge], routes: [NetworkRoute],
                routeEdges: [RouteEdge], stations: [NetworkStation], routeStations: [RouteStation]) {
        self.schemaVersion = schemaVersion; self.nodes = nodes; self.edges = edges; self.routes = routes
        self.routeEdges = routeEdges; self.stations = stations; self.routeStations = routeStations
    }
}

public struct MatchCandidate: Codable, Sendable {
    public var edgeId: String
    public var routeId: String?
    public var direction: Int
    public var offsetM: Double
    public var probability: Double
}
public struct StationEvent: Codable, Sendable {
    public let type: String
    public let timestamp: Double
    public let stationId: String?
    public let confidence: Double
    public init(type: String, timestamp: Double, stationId: String?, confidence: Double) {
        self.type = type; self.timestamp = timestamp; self.stationId = stationId; self.confidence = confidence
    }
    enum CodingKeys: String, CodingKey { case type, timestamp, stationId, confidence }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(type, forKey: .type); try c.encode(timestamp, forKey: .timestamp)
        try c.encode(stationId, forKey: .stationId); try c.encode(confidence, forKey: .confidence)
    }
}
public struct MatchResult: Codable, Sendable {
    public var timestamp: Double?
    public var status: String
    public var edgeId: String?
    public var lat: Double?
    public var lon: Double?
    public var offsetM: Double?
    public var routeId: String?
    public var direction: Int
    public var directionLabel: String?
    public var previousStationId: String?
    public var nextStationId: String?
    public var distanceToNextM: Double?
    public var progress: Double?
    public var confidence: Double
    public var uncertaintyM: Double?
    public var reason: String
    public var candidates: [MatchCandidate]
    public var events: [StationEvent]

    init(timestamp: Double?, status: String, reason: String, uncertaintyM: Double? = nil) {
        self.timestamp = timestamp; self.status = status; self.reason = reason
        self.direction = 0; self.confidence = 0; self.uncertaintyM = uncertaintyM
        self.candidates = []; self.events = []
    }

    enum CodingKeys: String, CodingKey {
        case timestamp, status, edgeId, lat, lon, offsetM, routeId, direction, directionLabel
        case previousStationId, nextStationId, distanceToNextM, progress, confidence, uncertaintyM, reason, candidates, events
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(timestamp, forKey: .timestamp); try c.encode(status, forKey: .status)
        try c.encode(edgeId, forKey: .edgeId); try c.encode(lat, forKey: .lat); try c.encode(lon, forKey: .lon)
        try c.encode(offsetM, forKey: .offsetM); try c.encode(routeId, forKey: .routeId)
        try c.encode(direction, forKey: .direction); try c.encode(directionLabel, forKey: .directionLabel)
        try c.encode(previousStationId, forKey: .previousStationId); try c.encode(nextStationId, forKey: .nextStationId)
        try c.encode(distanceToNextM, forKey: .distanceToNextM); try c.encode(progress, forKey: .progress)
        try c.encode(confidence, forKey: .confidence); try c.encode(uncertaintyM, forKey: .uncertaintyM)
        try c.encode(reason, forKey: .reason); try c.encode(candidates, forKey: .candidates); try c.encode(events, forKey: .events)
    }
}
