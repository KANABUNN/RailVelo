import Foundation

public enum NetworkError: Error, CustomStringConvertible {
    case invalid(String)
    public var description: String { switch self { case .invalid(let detail): return detail } }
}

/// Immutable topology. Loading validates the complete graph before inference.
public final class Network {
    public let document: NetworkDocument
    public let nodes: [String: NetworkNode]
    public let edges: [String: NetworkEdge]
    public let routes: [String: NetworkRoute]
    public let stations: [String: NetworkStation]
    let geometry: [String: EdgeGeometry]
    let adjacency: [String: [(node: String, edge: String, length: Double)]]
    let routeEdges: [String: [RouteEdge]]
    let routeStations: [String: [RouteStation]]
    private let spatialIndex: [String: [String]]
    private static let cellSize = 0.01

    public convenience init(jsonURL: URL) throws {
        let document = try RailVeloJSON.decoder().decode(NetworkDocument.self, from: Data(contentsOf: jsonURL))
        try self.init(document: document)
    }

    public init(document: NetworkDocument) throws {
        guard document.schemaVersion == 1 else { throw NetworkError.invalid("Unsupported schema version") }
        func index<T>(_ values: [T], _ key: (T) -> String) throws -> [String: T] {
            var result: [String: T] = [:]
            for value in values {
                let id = key(value)
                guard !id.isEmpty, result[id] == nil else { throw NetworkError.invalid("Duplicate or empty ID: \(id)") }
                result[id] = value
            }
            return result
        }
        let nodes = try index(document.nodes, { $0.id })
        let edges = try index(document.edges, { $0.id })
        let routes = try index(document.routes, { $0.id })
        let stations = try index(document.stations, { $0.id })
        guard !edges.isEmpty else { throw NetworkError.invalid("Empty graph") }
        for node in nodes.values {
            guard node.lat.isFinite, node.lon.isFinite, abs(node.lat) <= 90, abs(node.lon) <= 180 else {
                throw NetworkError.invalid("Invalid node coordinate")
            }
        }
        var geometry: [String: EdgeGeometry] = [:]
        var adjacency: [String: [(node: String, edge: String, length: Double)]] = [:]
        var spatialIndex: [String: [String]] = [:]
        for edge in edges.values {
            guard let from = nodes[edge.fromNode], let to = nodes[edge.toNode], edge.lengthM.isFinite,
                  edge.lengthM > 0, edge.coordinates.count >= 2,
                  edge.coordinates.allSatisfy({ $0.count == 2 && $0[0].isFinite && $0[1].isFinite && abs($0[0]) <= 90 && abs($0[1]) <= 180 }),
                  !edge.routeIds.isEmpty, edge.routeIds.allSatisfy({ routes[$0] != nil }) else { throw NetworkError.invalid("Invalid edge: \(edge.id)") }
            let rawLength = zip(edge.coordinates, edge.coordinates.dropFirst()).reduce(0.0) {
                $0 + Geometry.distance(Point(lat: $1.0[0], lon: $1.0[1]), Point(lat: $1.1[0], lon: $1.1[1]))
            }
            guard rawLength > 0 else { throw NetworkError.invalid("Zero geometry length") }
            let shape = EdgeGeometry(edge)
            guard shape.cumulative.count == edge.coordinates.count,
                  abs(shape.cumulative.first!) < 0.01, abs(shape.cumulative.last! - edge.lengthM) < 0.05,
                  shape.cumulative.allSatisfy({ $0.isFinite }),
                  zip(shape.cumulative, shape.cumulative.dropFirst()).allSatisfy({ $0.0 <= $0.1 }),
                  Geometry.distance(shape.points.first!, Point(lat: from.lat, lon: from.lon)) <= 1,
                  Geometry.distance(shape.points.last!, Point(lat: to.lat, lon: to.lon)) <= 1 else {
                throw NetworkError.invalid("Edge length or endpoint mismatch: \(edge.id)")
            }
            geometry[edge.id] = shape
            adjacency[edge.fromNode, default: []].append((edge.toNode, edge.id, edge.lengthM))
            adjacency[edge.toNode, default: []].append((edge.fromNode, edge.id, edge.lengthM))
            let xs = shape.points.map { Int(floor($0.lon / Self.cellSize)) }
            let ys = shape.points.map { Int(floor($0.lat / Self.cellSize)) }
            for x in xs.min()!...xs.max()! {
                for y in ys.min()!...ys.max()! { spatialIndex["\(x):\(y)", default: []].append(edge.id) }
            }
        }
        var routeEdges = Dictionary(grouping: document.routeEdges, by: { $0.routeId })
        for routeId in routeEdges.keys {
            routeEdges[routeId]!.sort { $0.sequence < $1.sequence }
            var endpoint: String?, measure = 0.0
            var seenEdges = Set<String>()
            guard routes[routeId] != nil else { throw NetworkError.invalid("Missing route") }
            for (sequence, item) in routeEdges[routeId]!.enumerated() {
                guard let edge = edges[item.edgeId], edge.routeIds.contains(routeId), [-1, 1].contains(item.direction),
                      item.sequence == sequence, item.startM.isFinite, abs(item.startM - measure) <= 0.1,
                      !seenEdges.contains(item.edgeId) else {
                    throw NetworkError.invalid("Invalid route edge measure/order")
                }
                seenEdges.insert(item.edgeId)
                let start = item.direction == 1 ? edge.fromNode : edge.toNode
                if let endpoint, endpoint != start { throw NetworkError.invalid("Non-contiguous route") }
                endpoint = item.direction == 1 ? edge.toNode : edge.fromNode
                measure += edge.lengthM
            }
        }
        var routeStations = Dictionary(grouping: document.routeStations, by: { $0.routeId })
        for routeId in routeStations.keys {
            routeStations[routeId]!.sort { $0.sequence < $1.sequence }
            guard let path = routeEdges[routeId], let end = path.last, let edge = edges[end.edgeId] else {
                throw NetworkError.invalid("Station route has no path")
            }
            let total = end.startM + edge.lengthM
            var previous = -Double.infinity
            for (sequence, station) in routeStations[routeId]!.enumerated() {
                guard stations[station.stationId] != nil, station.sequence == sequence,
                      station.measureM.isFinite, station.measureM > previous, station.measureM >= 0,
                      station.measureM <= total + 1, station.radiusM.isFinite, station.radiusM > 0, station.radiusM <= 1000 else {
                    throw NetworkError.invalid("Invalid station measure/order")
                }
                previous = station.measureM
            }
        }
        self.document = document; self.nodes = nodes; self.edges = edges; self.routes = routes; self.stations = stations
        self.geometry = geometry; self.adjacency = adjacency; self.routeEdges = routeEdges
        self.routeStations = routeStations; self.spatialIndex = spatialIndex
    }

    func candidates(_ point: Point, radius: Double) -> [Projection] {
        let latRadius = radius / 110_000
        let lonRadius = latRadius / max(0.01, cos(point.lat * Geometry.radians))
        let minX = Int(floor((point.lon - lonRadius) / Self.cellSize)), maxX = Int(floor((point.lon + lonRadius) / Self.cellSize))
        let minY = Int(floor((point.lat - latRadius) / Self.cellSize)), maxY = Int(floor((point.lat + latRadius) / Self.cellSize))
        var ids = Set<String>()
        for x in minX...maxX { for y in minY...maxY { ids.formUnion(spatialIndex["\(x):\(y)"] ?? []) } }
        return ids.map { geometry[$0]!.project(point, edgeId: $0) }
            .filter { $0.distance <= radius }
            .sorted { $0.distance == $1.distance ? $0.edgeId < $1.edgeId : $0.distance < $1.distance }
            .prefix(12).map { $0 }
    }

    func shortestDistance(from: String, to: String, limit: Double) -> Double {
        if from == to { return 0 }
        // Dijkstra is bounded by the observation's physical movement gate.
        var distances = [from: 0.0], queue = [(0.0, from)]
        while !queue.isEmpty {
            let i = queue.indices.min { queue[$0].0 < queue[$1].0 }!
            let (distance, node) = queue.remove(at: i)
            if distance > limit { break }
            if node == to { return distance }
            if distance > distances[node, default: .infinity] { continue }
            for item in adjacency[node] ?? [] {
                let value = distance + item.length
                if value <= limit && value < distances[item.node, default: .infinity] {
                    distances[item.node] = value; queue.append((value, item.node))
                }
            }
        }
        return .infinity
    }

    func routePosition(edgeId: String, offset: Double, routeId: String) -> (measure: Double, orientation: Int)? {
        guard let item = routeEdges[routeId]?.first(where: { $0.edgeId == edgeId }), let edge = edges[edgeId] else { return nil }
        return (item.startM + (item.direction == 1 ? offset : edge.lengthM - offset), item.direction)
    }

    func pointAlongRoute(routeId: String, measure: Double) -> (edgeId: String, offset: Double, point: Point)? {
        guard let items = routeEdges[routeId] else { return nil }
        for item in items {
            let edge = edges[item.edgeId]!
            if measure >= item.startM && measure <= item.startM + edge.lengthM {
                let local = measure - item.startM
                let offset = item.direction == 1 ? local : edge.lengthM - local
                return (edge.id, offset, geometry[edge.id]!.point(at: offset))
            }
        }
        return nil
    }
}
