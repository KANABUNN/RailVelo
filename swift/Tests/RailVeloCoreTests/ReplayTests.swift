import XCTest
import Foundation
@testable import RailVeloCore
import RailVeloSQLite

final class ReplayTests: XCTestCase {
    private var repository: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
    }
    private func network() throws -> Network {
        try Network(jsonURL: repository.appendingPathComponent("fixtures/synthetic_network.json"))
    }
    private func replay(_ scenario: String) throws -> [MatchResult] {
        let matcher = MapMatcher(network: try network())
        let text = try String(contentsOf: repository.appendingPathComponent("fixtures/\(scenario).jsonl"), encoding: .utf8)
        return try text.split(whereSeparator: \.isNewline).map {
            matcher.update(try RailVeloJSON.decoder().decode(Observation.self, from: Data($0.utf8)))
        }
    }
    func testNormalForwardAndReverse() throws {
        for (scenario, direction) in [("normal", 1), ("reverse", -1)] {
            let rows = try replay(scenario)
            let matched = rows.filter { $0.status == "matched" }
            XCTAssertGreaterThan(matched.count, 40)
            XCTAssertTrue(matched.allSatisfy { $0.routeId == "main" && $0.direction == direction })
            XCTAssertTrue(matched.allSatisfy { $0.offsetM != nil && $0.confidence >= 0.8 })
        }
    }
    func testStationDwellAndDeparture() throws {
        let events = try replay("station_stop_depart").flatMap { $0.events }
        XCTAssertEqual(events.filter { $0.type == "arrival" }.count, 1)
        XCTAssertEqual(events.filter { $0.type == "departure" }.count, 1)
        XCTAssertNotNil(events.first { $0.type == "arrival" }?.stationId)
    }
    func testPassAndBetweenStationStop() throws {
        XCTAssertTrue(try replay("station_pass").flatMap { $0.events }.contains { $0.type == "pass" })
        let events = try replay("between_station_stop").flatMap { $0.events }
        XCTAssertTrue(events.contains { $0.type == "between_station_stop" })
        XCTAssertTrue(events.contains { $0.type == "resume" })
    }
    func testGapPredictionExpires() throws {
        let rows = try replay("long_signal_loss")
        XCTAssertTrue(rows.contains { $0.status == "predicted" })
        XCTAssertTrue(rows.contains { $0.status == "lost" })
        XCTAssertTrue(rows.filter { $0.status == "predicted" }.allSatisfy { $0.events.isEmpty && ($0.uncertaintyM ?? .infinity) <= 120 })
    }
    func testTimestampAndCoordinateValidation() throws {
        let matcher = MapMatcher(network: try network())
        let initial = Observation(timestamp: 100, lat: 33, lon: 130, horizontalAccuracyM: 8)
        _ = matcher.update(initial)
        XCTAssertEqual(matcher.update(initial).reason, "non_monotonic_timestamp")
        let invalid = matcher.update(Observation(timestamp: 101, lat: 91, lon: 130, horizontalAccuracyM: 8))
        XCTAssertEqual(invalid.status, "rejected")
        XCTAssertNil(invalid.routeId)
        XCTAssertEqual(matcher.update(Observation(timestamp: .nan, lat: nil, lon: nil, horizontalAccuracyM: 8)).reason, "invalid_timestamp")
    }
    func testNullOutputContract() throws {
        let matcher = MapMatcher(network: try network())
        let result = matcher.update(Observation(timestamp: 1, lat: nil, lon: nil, horizontalAccuracyM: 8))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: RailVeloJSON.encoder().encode(result)) as? [String: Any])
        XCTAssertTrue(object["edge_id"] is NSNull)
        XCTAssertTrue(object["route_id"] is NSNull)
        XCTAssertTrue(object["uncertainty_m"] is NSNull)
        let event = StationEvent(type: "resume", timestamp: 1, stationId: nil, confidence: 0.9)
        let eventObject = try XCTUnwrap(JSONSerialization.jsonObject(with: RailVeloJSON.encoder().encode(event)) as? [String: Any])
        XCTAssertTrue(eventObject["station_id"] is NSNull)
    }
    func testSQLiteSnapshotMatchesJSON() throws {
        let stored = try SQLiteNetworkLoader.load(url: repository.appendingPathComponent("data/railway.sqlite"))
        let json = try Network(jsonURL: repository.appendingPathComponent("data/network.json"))
        XCTAssertEqual(stored.document.nodes.count, json.document.nodes.count)
        XCTAssertEqual(stored.document.edges.count, json.document.edges.count)
        XCTAssertEqual(stored.document.routeStations.count, json.document.routeStations.count)
        for edge in json.document.edges {
            XCTAssertEqual(stored.edges[edge.id]?.coordinates, edge.coordinates)
            XCTAssertEqual(stored.edges[edge.id]?.pointMeasuresM, edge.pointMeasuresM)
        }
    }
    func testMalformedGraphFailsBeforeInference() throws {
        let document = try network().document
        let bad = NetworkDocument(nodes: [], edges: document.edges, routes: document.routes,
                                  routeEdges: document.routeEdges, stations: document.stations, routeStations: document.routeStations)
        XCTAssertThrowsError(try Network(document: bad))
    }

    func testStationStopBeyondCentreDoesNotEmitPass() throws {
        let net = try network()
        let detector = StationEventDetector(network: net)
        let station = try XCTUnwrap(net.routeStations["main"]?.first { $0.stationId == "main_s2" })
        var events: [StationEvent] = []
        let approach: [(Double, Double, Double)] = [(0, -200, 20), (4, -120, 20), (8, -40, 15), (12, 20, 10)]
        for (time, offset, speed) in approach {
            events += detector.update(timestamp: time, routeId: "main", measure: station.measureM + offset,
                                      direction: 1, speed: speed, confidence: 0.95)
        }
        XCTAssertFalse(events.contains { $0.type == "pass" })
        for time in stride(from: 14.0, through: 28.0, by: 2) {
            events += detector.update(timestamp: time, routeId: "main", measure: station.measureM + 20,
                                      direction: 1, speed: 0, confidence: 0.95)
        }
        for (time, offset) in [(30.0, 60.0), (34.0, 120.0)] {
            events += detector.update(timestamp: time, routeId: "main", measure: station.measureM + offset,
                                      direction: 1, speed: 20, confidence: 0.95)
        }
        XCTAssertEqual(events.filter { $0.type == "arrival" }.count, 1)
        XCTAssertEqual(events.filter { $0.type == "departure" }.count, 1)
        XCTAssertFalse(events.contains { $0.type == "pass" })
    }

    func testPassIsDeferredUntilStationEnvelopeExit() throws {
        let net = try network()
        let detector = StationEventDetector(network: net)
        let station = try XCTUnwrap(net.routeStations["main"]?.first { $0.stationId == "main_s2" })
        _ = detector.update(timestamp: 0, routeId: "main", measure: station.measureM - 20,
                            direction: 1, speed: 10, confidence: 0.9)
        let crossing = detector.update(timestamp: 2, routeId: "main", measure: station.measureM + 20,
                                       direction: 1, speed: 10, confidence: 0.9)
        XCTAssertTrue(crossing.isEmpty)
        let exit = detector.update(timestamp: 4, routeId: "main", measure: station.measureM + 120,
                                   direction: 1, speed: 20, confidence: 0.9)
        XCTAssertEqual(exit.map { $0.type }, ["pass"])
        XCTAssertEqual(exit.first?.timestamp, 1)
    }

    func testReturnToAcquisitionPositionKeepsAcquiredState() throws {
        let net = try network()
        let matcher = MapMatcher(network: net)
        let outward = Array(stride(from: 2200.0, through: 2400.0, by: 20))
        let returning = Array(stride(from: 2380.0, through: 2200.0, by: -20))
        var last: MatchResult?
        for (index, measure) in (outward + returning).enumerated() {
            let location = try XCTUnwrap(net.pointAlongRoute(routeId: "main", measure: measure))
            last = matcher.update(Observation(timestamp: Double(index) * 2, lat: location.point.lat,
                                               lon: location.point.lon, horizontalAccuracyM: 8, speedMps: 10,
                                               speedAccuracyMps: 0.5, courseDeg: index < outward.count ? 90 : 270))
        }
        XCTAssertEqual(last?.status, "matched")
        XCTAssertEqual(last?.routeId, "main")
        XCTAssertEqual(last?.direction, -1)
    }

    func testCreepingBreaksContinuousArrivalDwell() throws {
        let net = try network()
        let detector = StationEventDetector(network: net)
        let station = try XCTUnwrap(net.routeStations["main"]?.first { $0.stationId == "main_s2" })
        _ = detector.update(timestamp: 0, routeId: "main", measure: station.measureM - 200,
                            direction: 1, speed: 10, confidence: 0.95)
        var earlierEvents: [StationEvent] = []
        for (time, speed) in [(4.0, 0.0), (8.0, 1.0), (12.0, 0.0), (16.0, 0.0), (20.0, 0.0)] {
            earlierEvents += detector.update(timestamp: time, routeId: "main", measure: station.measureM + 20,
                                             direction: 1, speed: speed, confidence: 0.95)
        }
        XCTAssertFalse(earlierEvents.contains { $0.type == "arrival" })
        let events = detector.update(timestamp: 24, routeId: "main", measure: station.measureM + 20,
                                     direction: 1, speed: 0, confidence: 0.95)
        XCTAssertEqual(events.map { $0.type }, ["arrival"])
        XCTAssertEqual(events.first?.timestamp, 12)
    }
}
