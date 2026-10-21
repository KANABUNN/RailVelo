import Foundation
import XCTest
import RailVeloCore
import CSQLite
@testable import RailVeloRecording

final class RecordingTests: XCTestCase {
    private var repository: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
    }
    private func network() throws -> Network {
        try Network(jsonURL: repository.appendingPathComponent("fixtures/synthetic_network.json"))
    }
    private func folder() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("RailVeloRecording-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
    private func observation(_ timestamp: Double, speed: Double? = 10, accuracy: Double? = 0.5,
                             lat: Double? = 33, lon: Double? = 130, positionAccuracy: Double = 8) -> Observation {
        Observation(timestamp: timestamp, lat: lat, lon: lon, horizontalAccuracyM: positionAccuracy,
                    speedMps: speed, speedAccuracyMps: accuracy, courseDeg: 90)
    }
    private func sample(_ timestamp: Double, speed: Double? = 36, reason: String? = nil) -> RecordedSample {
        RecordedSample(observation: observation(timestamp), result: MatchResult(timestamp: timestamp, status: "uncertain", reason: "test"),
                       speedKmh: speed, exclusionReason: reason)
    }

    private func withSQLDatabase<T>(_ url: URL, flags: Int32 = SQLITE_OPEN_READONLY,
                                    _ body: (OpaquePointer) throws -> T) throws -> T {
        var pointer: OpaquePointer?
        let code = sqlite3_open_v2(url.path, &pointer, flags, nil)
        guard code == SQLITE_OK, let database = pointer else {
            if let pointer { sqlite3_close(pointer) }
            throw NSError(domain: "RecordingTestSQLite", code: Int(code))
        }
        defer { sqlite3_close(database) }
        return try body(database)
    }

    /// Parse RFC 4180 quoting as a consumer, including UTF-8, escaped quotes and embedded newlines.
    private func parsedCSV(_ url: URL) throws -> (header: [String], records: [[String: String]]) {
        let bytes = Array(try Data(contentsOf: url))
        var cells: [[String]] = [], row: [String] = [], field: [UInt8] = []
        var quoted = false, index = 0
        while index < bytes.count {
            let byte = bytes[index]
            if quoted {
                if byte == 34 {
                    if index + 1 < bytes.count && bytes[index + 1] == 34 { field.append(34); index += 1 }
                    else { quoted = false }
                } else { field.append(byte) }
            } else if byte == 34 { quoted = true }
            else if byte == 44 { row.append(String(decoding: field, as: UTF8.self)); field = [] }
            else if byte == 13 || byte == 10 {
                if byte == 13 && index + 1 < bytes.count && bytes[index + 1] == 10 { index += 1 }
                row.append(String(decoding: field, as: UTF8.self)); cells.append(row); row = []; field = []
            } else { field.append(byte) }
            index += 1
        }
        XCTAssertFalse(quoted, "CSV ended inside a quoted field")
        if !field.isEmpty || !row.isEmpty { row.append(String(decoding: field, as: UTF8.self)); cells.append(row) }
        let header = try XCTUnwrap(cells.first)
        let records = cells.dropFirst().map { values -> [String: String] in
            XCTAssertEqual(values.count, header.count, "CSV record has the wrong column count")
            return Dictionary(uniqueKeysWithValues: zip(header, values))
        }
        return (header, records)
    }

    private func rowCount(_ table: String, at url: URL) throws -> Int {
        // Test-only table names are fixed by the callers below.
        try withSQLDatabase(url) { database in
            var pointer: OpaquePointer?
            XCTAssertEqual(sqlite3_prepare_v2(database, "SELECT COUNT(*) FROM \(table)", -1, &pointer, nil), SQLITE_OK)
            let statement = try XCTUnwrap(pointer)
            defer { sqlite3_finalize(statement) }
            XCTAssertEqual(sqlite3_step(statement), SQLITE_ROW)
            return Int(sqlite3_column_int64(statement, 0))
        }
    }

    func testInvalidMeasurementsAndSpikesDoNotPolluteMaximum() throws {
        let processor = RideProcessor(network: try network())
        XCTAssertEqual(processor.process(observation(100)).speedKmh, 36)
        let spike = processor.process(observation(101, speed: 50))
        XCTAssertNil(spike.speedKmh)
        XCTAssertEqual(spike.exclusionReason, "implausible_acceleration")
        for invalid in [observation(102, speed: -1), observation(103, speed: .nan),
                        observation(104, speed: 80), observation(105, accuracy: nil),
                        observation(106, accuracy: 9), observation(107, lat: 91),
                        observation(108, positionAccuracy: -1), observation(109, lat: nil, lon: nil)] {
            XCTAssertNil(processor.process(invalid).speedKmh)
        }
        XCTAssertNil(processor.process(observation(99, speed: 40)).speedKmh)
        XCTAssertEqual(processor.maximumSpeedKmh, 36)
    }

    func testCachedAndFutureFixesLeaveEngineTimelineUsable() throws {
        let processor = RideProcessor(network: try network())
        let old = processor.process(observation(100, speed: 40), receivedAt: 111)
        XCTAssertEqual(old.result.status, "rejected")
        XCTAssertEqual(old.exclusionReason, "stale_fix")
        let future = processor.process(observation(200, speed: 40), receivedAt: 101)
        XCTAssertEqual(future.exclusionReason, "future_fix")
        XCTAssertEqual(processor.process(observation(110), receivedAt: 110).speedKmh, 36)
        XCTAssertEqual(processor.maximumSpeedKmh, 36)
    }

    func testRejectedJumpAndMissingFixCannotBecomeCurrentSpeed() throws {
        let processor = RideProcessor(network: try network())
        _ = processor.process(observation(100))
        let jump = processor.process(observation(101, speed: 40, lat: 34, lon: 131))
        XCTAssertNil(jump.speedKmh)
        XCTAssertTrue(jump.exclusionReason?.hasPrefix("coordinate_jump") == true)
        let missing = processor.process(observation(102, speed: 40, lat: nil, lon: nil))
        XCTAssertNil(missing.speedKmh)
        XCTAssertEqual(processor.maximumSpeedKmh, 36)
    }

    func testPauseResumeBreaksContinuityButPreservesMaximum() throws {
        let processor = RideProcessor(network: try network())
        XCTAssertEqual(processor.process(observation(100)).speedKmh, 36)
        processor.resetContinuity()
        XCTAssertEqual(processor.process(observation(102, speed: 20)).speedKmh, 72)
        XCTAssertEqual(processor.maximumSpeedKmh, 72)
        XCTAssertNil(processor.process(observation(101, speed: 60)).speedKmh)
    }

    func testOutOfOrderFixAfterResumeDoesNotPoisonMatcherState() throws {
        let processor = RideProcessor(network: try network())
        _ = processor.process(observation(100))
        processor.resetContinuity()
        let old = processor.process(observation(99, lon: 130.032))
        XCTAssertEqual(old.result.reason, "non_monotonic_timestamp")
        let resumed = processor.process(observation(101))
        XCTAssertNotEqual(resumed.result.status, "rejected")
        XCTAssertEqual(resumed.speedKmh, 36)
    }

    func testSQLiteReopenModeSeparationAndRecovery() throws {
        let url = try folder().appendingPathComponent("rides.sqlite")
        var store: RideStore? = try RideStore(url: url)
        let live = try XCTUnwrap(store).begin(mode: .live, at: 100)
        let replay = try XCTUnwrap(store).begin(mode: .replay, at: 200)
        try store?.append(sample(101, speed: 36), to: live)
        try store?.append(sample(201, speed: 72), to: replay)
        try store?.setStatus("completed", session: replay, at: 202)
        store = nil
        let reopened = try RideStore(url: url)
        try reopened.recoverInterrupted(at: 300)
        let summaries = try reopened.summaries()
        let liveSummary = try XCTUnwrap(summaries.first { $0.id == live })
        let replaySummary = try XCTUnwrap(summaries.first { $0.id == replay })
        XCTAssertEqual(liveSummary.status, "interrupted")
        XCTAssertEqual(liveSummary.endedAt, 101)
        XCTAssertEqual(liveSummary.mode, .live)
        XCTAssertEqual(liveSummary.maximumSpeedKmh, 36)
        XCTAssertEqual(replaySummary.mode, .replay)
        XCTAssertEqual(replaySummary.status, "completed")
        XCTAssertEqual(replaySummary.maximumSpeedKmh, 72)
        XCTAssertEqual(try reopened.points(session: live, limit: 100).count, 1)
        XCTAssertEqual(try reopened.points(session: replay, limit: 100).count, 1)
    }

    func testReplayRecoveryUsesSavedWallClockWithoutChangingObservationTime() throws {
        let store = try RideStore(url: try folder().appendingPathComponent("rides.sqlite"))
        let startedAt = 1_800_000_000.0, observationTime = 1_700_000_000.0
        let id = try store.begin(mode: .replay, at: startedAt)
        try store.append(sample(observationTime), to: id, recordedAt: startedAt + 10)
        try store.append(sample(observationTime + 1), to: id, recordedAt: startedAt + 20)
        try store.recoverInterrupted(at: startedAt + 100)
        XCTAssertEqual(try store.summaries().first?.endedAt, startedAt + 20)
        XCTAssertEqual(try store.points(session: id, limit: 100).map { $0.timestamp }, [observationTime, observationTime + 1])
    }

    func testInvalidObservationClockCanStillSaveValidReceiptTime() throws {
        let store = try RideStore(url: try folder().appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .live, at: 100)
        try store.append(sample(.nan, speed: nil, reason: "invalid_timestamp"), to: id, recordedAt: 110)
        try store.append(sample(10_000, speed: nil, reason: "future_fix"), to: id, recordedAt: .infinity)
        try store.recoverInterrupted(at: 200)
        XCTAssertEqual(try store.summaries().first?.endedAt, 110)
        XCTAssertTrue(try store.points(session: id, limit: 100).isEmpty)
    }

    func testRecoveryNeverEndsBeforeStartWhenLegacyClockWasReplayTime() throws {
        let store = try RideStore(url: try folder().appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .replay, at: 200)
        try store.append(sample(100), to: id)
        try store.recoverInterrupted(at: 300)
        XCTAssertEqual(try store.summaries().first?.endedAt, 200)
    }

    func testExistingVersionOneDatabaseAddsSavedTimeColumn() throws {
        let url = try folder().appendingPathComponent("rides.sqlite")
        var pointer: OpaquePointer?
        XCTAssertEqual(sqlite3_open(url.path, &pointer), SQLITE_OK)
        let database = try XCTUnwrap(pointer)
        let sql = """
            PRAGMA user_version=1;
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, mode TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL,
                maximum_speed_kmh REAL NOT NULL DEFAULT 0, status TEXT NOT NULL,
                last_timestamp REAL, previous_speed REAL, segment INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO sessions(id,mode,started_at,status,last_timestamp)
                VALUES('11111111-1111-1111-1111-111111111111','replay',100,'recording',50);
            """
        let code = sqlite3_exec(database, sql, nil, nil, nil)
        sqlite3_close(database)
        XCTAssertEqual(code, SQLITE_OK)
        let store = try RideStore(url: url)
        try store.append(sample(51), to: "11111111-1111-1111-1111-111111111111", recordedAt: 110)
        try store.recoverInterrupted(at: 200)
        XCTAssertEqual(try store.summaries().first?.endedAt, 110)
    }

    func testAppendFailureRollsBackSampleAndMaximum() throws {
        let store = try RideStore(url: try folder().appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .live, at: 100)
        try store.append(sample(101), to: id)
        var result = MatchResult(timestamp: 102, status: "matched", reason: "test")
        result.events = [StationEvent(type: "arrival", timestamp: .nan, stationId: "station", confidence: 0.9)]
        let invalid = RecordedSample(observation: observation(102), result: result, speedKmh: 100, exclusionReason: nil)
        XCTAssertThrowsError(try store.append(invalid, to: id))
        XCTAssertEqual(try store.points(session: id, limit: 100).count, 1)
        XCTAssertEqual(try store.summaries().first?.maximumSpeedKmh, 36)
    }

    func testPauseCreatesGraphGapAndBlocksAppend() throws {
        let store = try RideStore(url: try folder().appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .live, at: 100)
        try store.append(sample(101), to: id)
        try store.setStatus("paused", session: id, at: 102)
        XCTAssertThrowsError(try store.append(sample(103), to: id))
        try store.setStatus("recording", session: id, at: 110)
        try store.append(sample(111), to: id)
        try store.append(sample(112, speed: nil, reason: "missing_fix"), to: id)
        try store.append(sample(113), to: id)
        let points = try store.points(session: id, limit: 100)
        XCTAssertEqual(points.count, 4)
        XCTAssertNotEqual(points[0].segment, points[1].segment)
        XCTAssertNil(points[2].speedKmh)
        XCTAssertNotEqual(points[1].segment, points[3].segment)
    }

    func testWholeRideDownsamplingKeepsEndpointsPeakAndLimit() throws {
        let store = try RideStore(url: try folder().appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .replay, at: 100)
        for index in 0..<1_000 { try store.append(sample(Double(100 + index), speed: index == 500 ? 180 : Double(index % 30)), to: id) }
        let points = try store.points(session: id, limit: 80)
        XCTAssertLessThanOrEqual(points.count, 80)
        XCTAssertEqual(points.first?.timestamp, 100)
        XCTAssertEqual(points.last?.timestamp, 1_099)
        XCTAssertTrue(points.contains { $0.speedKmh == 180 })
        XCTAssertEqual(try store.points(session: id, limit: 0).count, 0)
    }

    func testInvalidClockFixesRemainInCSVButDoNotDistortGraphOrRecovery() throws {
        let directory = try folder(), store = try RideStore(url: directory.appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .live, at: 100)
        try store.append(sample(100), to: id)
        try store.append(sample(101, speed: nil, reason: "missing_fix"), to: id)
        try store.append(sample(102), to: id)
        for (index, reason) in ["stale_fix", "future_fix", "non_monotonic_timestamp", "invalid_timestamp", "invalid_receipt_timestamp"].enumerated() {
            try store.append(sample(Double(10_000 + index), speed: nil, reason: reason), to: id)
        }
        let points = try store.points(session: id, limit: 100)
        XCTAssertEqual(points.map { $0.timestamp }, [100, 101, 102])
        XCTAssertNil(points[1].speedKmh)
        try store.recoverInterrupted(at: 200)
        XCTAssertEqual(try store.summaries().first?.endedAt, 102)
        let output = directory.appendingPathComponent("ride.csv")
        try store.exportCSV(session: id, to: output)
        let csv = try String(contentsOf: output, encoding: .utf8)
        XCTAssertTrue(csv.contains("future_fix"))
        XCTAssertTrue(csv.contains("10004.0"))
    }

    func testCSVContainsUTCValidityAllFieldsAndEscapedReasons() throws {
        let directory = try folder(), store = try RideStore(url: directory.appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .replay, at: 1_700_000_000)
        let reason = "poor, \"signal\"\n再取得"
        try store.append(sample(1_700_000_001, speed: nil, reason: reason), to: id)
        let output = directory.appendingPathComponent("ride.csv")
        try store.exportCSV(session: id, to: output)
        let csv = try String(contentsOf: output, encoding: .utf8)
        XCTAssertTrue(csv.contains("\"UTC (+00:00)\""))
        XCTAssertTrue(csv.contains("\"WGS84 (EPSG:4326)\""))
        XCTAssertTrue(csv.contains("2023-11-14T22:13:21.000Z"))
        XCTAssertTrue(csv.contains("\"poor, \"\"signal\"\"\n再取得\""))
        XCTAssertTrue(csv.contains("\"false\""))
        XCTAssertTrue(csv.contains("\"match_json\""))
        XCTAssertTrue(csv.contains("\"observation_json\""))
        XCTAssertTrue(csv.contains("\"session_status\""))
        XCTAssertTrue(csv.contains("\"replay\""))
    }

    func testNonfiniteRawSensorValueRemainsExportable() throws {
        let directory = try folder(), store = try RideStore(url: directory.appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .replay, at: 100)
        let processor = RideProcessor(network: try network())
        try store.append(processor.process(observation(.nan, speed: .infinity)), to: id)
        try store.exportCSV(session: id, to: directory.appendingPathComponent("ride.csv"))
        let csv = try String(contentsOf: directory.appendingPathComponent("ride.csv"), encoding: .utf8)
        XCTAssertTrue(csv.contains("invalid_timestamp"))
        XCTAssertTrue(csv.contains("NaN"))
        XCTAssertEqual(try store.summaries().first?.maximumSpeedKmh, 0)
        XCTAssertEqual(try store.points(session: id, limit: 100).count, 0)
    }

    func testDeletionRequiresEndedSessionAndDoesNotAffectOtherRide() throws {
        let store = try RideStore(url: try folder().appendingPathComponent("rides.sqlite"))
        let first = try store.begin(mode: .live, at: 100), second = try store.begin(mode: .replay, at: 200)
        try store.append(sample(101), to: first)
        XCTAssertThrowsError(try store.delete(session: first))
        try store.setStatus("paused", session: first, at: 102)
        XCTAssertThrowsError(try store.delete(session: first))
        try store.setStatus("completed", session: first, at: 103)
        try store.delete(session: first)
        XCTAssertEqual(try store.summaries().map { $0.id }, [second])
        XCTAssertEqual(try store.points(session: first, limit: 100).count, 0)
        XCTAssertThrowsError(try store.exportCSV(session: first, to: FileManager.default.temporaryDirectory.appendingPathComponent("invalid.csv")))
        XCTAssertThrowsError(try store.delete(session: "../rides.sqlite"))
    }

    func testExtendedCSVPreservesReceiptClocksDiagnosticsAndSessionSummary() throws {
        let directory = try folder(), store = try RideStore(url: directory.appendingPathComponent("rides.sqlite"))
        let id = try store.begin(mode: .replay, at: 1000)
        try store.append(sample(100), to: id, recordedAt: 1002, receivedAt: 1001.5)
        let detail = "poor, \"signal\"\n再取得"
        try store.recordDiagnostic(session: id, at: 1003, kind: "location_error", domain: "kCLErrorDomain", code: 0, detail: detail)
        try store.setStatus("completed", session: id, at: 1010)
        let output = directory.appendingPathComponent("extended.csv")
        try store.exportCSV(session: id, to: output)
        let csv = try parsedCSV(output)
        XCTAssertEqual(csv.header.count, 39)
        XCTAssertEqual(Array(csv.header.suffix(3)), ["received_unix_seconds", "persistence_started_unix_seconds", "details_json"])
        let observation = try XCTUnwrap(csv.records.first { $0["record_type"] == "observation" })
        XCTAssertEqual(observation["unix_seconds"], "100.0")
        XCTAssertEqual(observation["received_unix_seconds"], "1001.5")
        XCTAssertEqual(observation["persistence_started_unix_seconds"], "1002.0")
        let diagnostic = try XCTUnwrap(csv.records.first { $0["record_type"] == "diagnostic" })
        let diagnosticJSON = try XCTUnwrap(diagnostic["details_json"])
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(diagnosticJSON.utf8)) as? [String: Any])
        XCTAssertEqual(payload["kind"] as? String, "location_error")
        XCTAssertEqual(payload["domain"] as? String, "kCLErrorDomain")
        XCTAssertEqual(payload["code"] as? Int, 0)
        XCTAssertEqual(payload["detail"] as? String, detail)
        let summary = try XCTUnwrap(csv.records.first { $0["record_type"] == "session_summary" })
        let summaryJSON = try XCTUnwrap(summary["details_json"])
        let values = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(summaryJSON.utf8)) as? [String: Any])
        XCTAssertEqual(values["started_at"] as? Double, 1000)
        XCTAssertEqual(values["ended_at"] as? Double, 1010)
        XCTAssertEqual(values["last_saved_at"] as? Double, 1002)
        XCTAssertEqual(values["maximum_speed_kmh"] as? Double, 36)
        XCTAssertEqual(values["status"] as? String, "completed")
        XCTAssertEqual(values["timing_semantics"] as? String, "received_to_persistence_start_excludes_sql_and_commit")
        // CI may explicitly retain this artificial replay for the Python consumer interoperability check.
        if let path = ProcessInfo.processInfo.environment["RAILVELO_TEST_EXPORT_PATH"], !path.isEmpty {
            let destination = URL(fileURLWithPath: path)
            try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data(contentsOf: output).write(to: destination, options: .atomic)
        }
    }

    func testExistingVersionFourSamplesMigrateWithoutLosingRowsOrFabricatingReceiptTime() throws {
        let url = try folder().appendingPathComponent("rides.sqlite")
        let id = "22222222-2222-2222-2222-222222222222", old = sample(100)
        let raw = String(decoding: try RailVeloJSON.encoder().encode(old.observation), as: UTF8.self)
        let matched = String(decoding: try RailVeloJSON.encoder().encode(old.result), as: UTF8.self)
        try withSQLDatabase(url, flags: SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE) { database in
            let schema = """
                PRAGMA user_version=1;
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,mode TEXT NOT NULL,started_at REAL NOT NULL,ended_at REAL,
                    maximum_speed_kmh REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,last_timestamp REAL,
                    last_saved_at REAL,previous_speed REAL,segment INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    timestamp REAL,observation_json TEXT NOT NULL,match_json TEXT NOT NULL,
                    speed_kmh REAL,exclusion_reason TEXT,segment INTEGER NOT NULL
                );
                INSERT INTO sessions(id,mode,started_at,status,last_timestamp,last_saved_at,maximum_speed_kmh)
                    VALUES('22222222-2222-2222-2222-222222222222','replay',1000,'recording',100,1001,36);
                """
            XCTAssertEqual(sqlite3_exec(database, schema, nil, nil, nil), SQLITE_OK)
            var pointer: OpaquePointer?
            XCTAssertEqual(sqlite3_prepare_v2(database, "INSERT INTO samples(session_id,timestamp,observation_json,match_json,speed_kmh,segment) VALUES(?,100,?,?,36,0)", -1, &pointer, nil), SQLITE_OK)
            let statement = try XCTUnwrap(pointer)
            defer { sqlite3_finalize(statement) }
            let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
            XCTAssertEqual(sqlite3_bind_text(statement, 1, id, -1, transient), SQLITE_OK)
            XCTAssertEqual(sqlite3_bind_text(statement, 2, raw, -1, transient), SQLITE_OK)
            XCTAssertEqual(sqlite3_bind_text(statement, 3, matched, -1, transient), SQLITE_OK)
            XCTAssertEqual(sqlite3_step(statement), SQLITE_DONE)
        }
        let store = try RideStore(url: url)
        try store.append(sample(101), to: id, recordedAt: 1003, receivedAt: 1002.5)
        try store.recoverInterrupted(at: 1100)
        let output = url.deletingLastPathComponent().appendingPathComponent("migrated.csv")
        try store.exportCSV(session: id, to: output)
        let observations = try parsedCSV(output).records.filter { $0["record_type"] == "observation" }
        XCTAssertEqual(observations.count, 2)
        XCTAssertEqual(observations[0]["unix_seconds"], "100.0")
        XCTAssertEqual(observations[0]["speed_kmh"], "36.0")
        XCTAssertEqual(observations[0]["received_unix_seconds"], "")
        XCTAssertEqual(observations[0]["persistence_started_unix_seconds"], "")
        XCTAssertEqual(observations[1]["received_unix_seconds"], "1002.5")
        XCTAssertEqual(observations[1]["persistence_started_unix_seconds"], "1003.0")
        XCTAssertEqual(try store.summaries().first?.endedAt, 1003)
        XCTAssertEqual(try rowCount("samples", at: url), 2)
    }

    func testDiagnosticDeletionCascadesOnlyForTheEndedTargetSession() throws {
        let url = try folder().appendingPathComponent("rides.sqlite"), store = try RideStore(url: url)
        let first = try store.begin(mode: .live, at: 100), second = try store.begin(mode: .replay, at: 200)
        var result = MatchResult(timestamp: 101, status: "matched", reason: "test")
        result.events = [StationEvent(type: "pass", timestamp: 101, stationId: "station", confidence: 0.9)]
        try store.append(RecordedSample(observation: observation(101), result: result, speedKmh: 36, exclusionReason: nil), to: first)
        try store.append(sample(201), to: second)
        try store.recordDiagnostic(session: first, at: 102, kind: "remove")
        try store.recordDiagnostic(session: second, at: 202, kind: "keep")
        XCTAssertEqual(try rowCount("diagnostics", at: url), 2)
        XCTAssertThrowsError(try store.delete(session: first))
        try store.setStatus("completed", session: first, at: 103)
        try store.delete(session: first)
        XCTAssertEqual(try rowCount("sessions", at: url), 1)
        XCTAssertEqual(try rowCount("diagnostics", at: url), 1)
        XCTAssertEqual(try rowCount("samples", at: url), 1)
        XCTAssertEqual(try rowCount("events", at: url), 0)
        XCTAssertEqual(try rowCount("status_events", at: url), 1)
        let output = url.deletingLastPathComponent().appendingPathComponent("survivor.csv")
        try store.exportCSV(session: second, to: output)
        let rows = try parsedCSV(output).records.filter { $0["record_type"] == "diagnostic" }
        XCTAssertEqual(rows.count, 1)
        XCTAssertTrue(rows[0]["details_json"]?.contains("keep") == true)
    }
}
