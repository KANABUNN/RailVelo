import Foundation
import CSQLite
import RailVeloCore

public enum RideStoreError: Error, CustomStringConvertible {
    case database(String), invalidSession(String), invalidValue(String)
    public var description: String {
        switch self { case .database(let text), .invalidSession(let text), .invalidValue(let text): return text }
    }
}

/// A separate writable database for private ride history. Own on a single serial executor.
public final class RideStore {
    private var database: OpaquePointer?
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    private enum Value { case text(String), number(Double), integer(Int64), null }

    public init(url: URL) throws {
        guard url.isFileURL else { throw RideStoreError.invalidValue("History database must be a local file") }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let code = sqlite3_open_v2(url.path, &database, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nil)
        guard code == SQLITE_OK, database != nil else {
            let error = message()
            if let database { sqlite3_close(database) }; database = nil
            throw RideStoreError.database(error)
        }
        do {
            sqlite3_busy_timeout(database, 5_000)
            try execute("PRAGMA foreign_keys=ON")
            try execute("PRAGMA journal_mode=WAL")
            try execute("PRAGMA synchronous=FULL")
            let version: Int32 = try statement("PRAGMA user_version") { sqlite3_step($0) == SQLITE_ROW ? sqlite3_column_int($0, 0) : -1 }
            guard version == 0 || version == 1 else { throw RideStoreError.database("Unsupported ride history schema") }
            try execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL CHECK(mode IN ('live','replay')),
                    started_at REAL NOT NULL, ended_at REAL, maximum_speed_kmh REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL, last_timestamp REAL, last_saved_at REAL, previous_speed REAL, segment INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    timestamp REAL, observation_json TEXT NOT NULL, match_json TEXT NOT NULL,
                    speed_kmh REAL, exclusion_reason TEXT, segment INTEGER NOT NULL,
                    received_at REAL, persistence_started_at REAL
                );
                CREATE INDEX IF NOT EXISTS samples_session_order ON samples(session_id,id);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
                    type TEXT NOT NULL, timestamp REAL NOT NULL, station_id TEXT, confidence REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS status_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, timestamp REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS diagnostics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    timestamp REAL NOT NULL, payload_json TEXT NOT NULL
                );
                PRAGMA user_version=1;
                """)
            let hasSavedAt: Bool = try statement("PRAGMA table_info(sessions)") { pointer in
                var code = sqlite3_step(pointer), found = false
                while code == SQLITE_ROW {
                    if text(pointer, 1) == "last_saved_at" { found = true }
                    code = sqlite3_step(pointer)
                }
                guard code == SQLITE_DONE else { throw RideStoreError.database(message()) }
                return found
            }
            if !hasSavedAt { try execute("ALTER TABLE sessions ADD COLUMN last_saved_at REAL") }
            let sampleColumns: Set<String> = try statement("PRAGMA table_info(samples)") { pointer in
                var names = Set<String>(), code = sqlite3_step(pointer)
                while code == SQLITE_ROW {
                    if let name = text(pointer, 1) { names.insert(name) }
                    code = sqlite3_step(pointer)
                }
                guard code == SQLITE_DONE else { throw RideStoreError.database(message()) }
                return names
            }
            for column in ["received_at", "persistence_started_at"] where !sampleColumns.contains(column) {
                try execute("ALTER TABLE samples ADD COLUMN \(column) REAL")
            }
        } catch {
            if let database { sqlite3_close(database) }; database = nil
            throw error
        }
    }

    deinit { if let database { sqlite3_close(database) } }
    private func message() -> String { database.map { String(cString: sqlite3_errmsg($0)) } ?? "History database is closed" }
    private func validate(_ id: String) throws {
        guard UUID(uuidString: id) != nil else { throw RideStoreError.invalidSession("Invalid session identifier") }
    }
    private func statement<T>(_ sql: String, _ values: [Value] = [], _ body: (OpaquePointer) throws -> T) throws -> T {
        var pointer: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &pointer, nil) == SQLITE_OK, let pointer else {
            throw RideStoreError.database(message())
        }
        defer { sqlite3_finalize(pointer) }
        for (offset, value) in values.enumerated() {
            let index = Int32(offset + 1), code: Int32
            switch value {
            case .text(let text): code = sqlite3_bind_text(pointer, index, text, -1, transient)
            case .number(let number): code = number.isFinite ? sqlite3_bind_double(pointer, index, number) : sqlite3_bind_null(pointer, index)
            case .integer(let integer): code = sqlite3_bind_int64(pointer, index, integer)
            case .null: code = sqlite3_bind_null(pointer, index)
            }
            guard code == SQLITE_OK else { throw RideStoreError.database(message()) }
        }
        return try body(pointer)
    }
    private func execute(_ sql: String) throws {
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else { throw RideStoreError.database(message()) }
    }
    private func write(_ sql: String, _ values: [Value] = []) throws {
        try statement(sql, values) { pointer in
            guard sqlite3_step(pointer) == SQLITE_DONE else { throw RideStoreError.database(message()) }
        }
    }
    private func transaction<T>(_ body: () throws -> T) throws -> T {
        try execute("BEGIN IMMEDIATE")
        do { let result = try body(); try execute("COMMIT"); return result }
        catch { try? execute("ROLLBACK"); throw error }
    }
    private func text(_ pointer: OpaquePointer, _ index: Int32) -> String? {
        guard sqlite3_column_type(pointer, index) != SQLITE_NULL, let value = sqlite3_column_text(pointer, index) else { return nil }
        return String(cString: value)
    }
    private func number(_ pointer: OpaquePointer, _ index: Int32) -> Double? {
        sqlite3_column_type(pointer, index) == SQLITE_NULL ? nil : sqlite3_column_double(pointer, index)
    }
    private func numeric(_ value: Double?) -> Value { value.map(Value.number) ?? .null }
    private func optionalText(_ value: String?) -> Value { value.map(Value.text) ?? .null }
    private func encoder() -> JSONEncoder {
        let encoder = RailVeloJSON.encoder()
        encoder.nonConformingFloatEncodingStrategy = .convertToString(positiveInfinity: "+Infinity", negativeInfinity: "-Infinity", nan: "NaN")
        return encoder
    }
    private func decoder() -> JSONDecoder {
        let decoder = RailVeloJSON.decoder()
        decoder.nonConformingFloatDecodingStrategy = .convertFromString(positiveInfinity: "+Infinity", negativeInfinity: "-Infinity", nan: "NaN")
        return decoder
    }

    public func begin(mode: RideMode, at: Double) throws -> String {
        guard at.isFinite else { throw RideStoreError.invalidValue("Invalid session start time") }
        let id = UUID().uuidString
        try transaction {
            try write("INSERT INTO sessions(id,mode,started_at,status) VALUES(?,?,?,'recording')", [.text(id), .text(mode.rawValue), .number(at)])
            try write("INSERT INTO status_events(session_id,status,timestamp) VALUES(?,'recording',?)", [.text(id), .number(at)])
        }
        return id
    }

    public func append(_ sample: RecordedSample, to id: String, recordedAt: Double? = nil, receivedAt: Double? = nil) throws {
        try validate(id)
        let observationJSON = String(decoding: try encoder().encode(sample.observation), as: UTF8.self)
        let matchJSON = String(decoding: try encoder().encode(sample.result), as: UTF8.self)
        let speed = sample.speedKmh.flatMap { $0.isFinite && $0 >= 0 && $0 <= 216 && sample.exclusionReason == nil && sample.result.status != "rejected" ? $0 : nil }
        let reason = sample.exclusionReason ?? (sample.speedKmh != nil && speed == nil ? "invalid_accepted_speed" : nil)
        try transaction {
            let previous: (Double?, Double?, Int, Double?) = try statement("SELECT last_timestamp,previous_speed,segment,last_saved_at,status FROM sessions WHERE id=?", [.text(id)]) { pointer in
                guard sqlite3_step(pointer) == SQLITE_ROW, text(pointer, 4) == "recording" else {
                    throw RideStoreError.invalidSession("Session is not recording")
                }
                return (number(pointer, 0), number(pointer, 1), Int(sqlite3_column_int64(pointer, 2)), number(pointer, 3))
            }
            var segment = previous.2
            if previous.0 != nil && ((previous.1 == nil && speed != nil) || sample.observation.timestamp - previous.0! > 10) { segment += 1 }
            try write("INSERT INTO samples(session_id,timestamp,observation_json,match_json,speed_kmh,exclusion_reason,segment,received_at,persistence_started_at) VALUES(?,?,?,?,?,?,?,?,?)", [
                .text(id), .number(sample.observation.timestamp), .text(observationJSON), .text(matchJSON), numeric(speed), optionalText(reason), .integer(Int64(segment)), numeric(receivedAt), numeric(recordedAt)
            ])
            let sampleID = sqlite3_last_insert_rowid(database)
            for event in sample.result.events {
                guard event.timestamp.isFinite, event.confidence.isFinite else { throw RideStoreError.invalidValue("Invalid station event") }
                try write("INSERT INTO events(sample_id,type,timestamp,station_id,confidence) VALUES(?,?,?,?,?)", [
                    .integer(sampleID), .text(event.type), .number(event.timestamp), optionalText(event.stationId), .number(event.confidence)
                ])
            }
            let invalidTime = ["stale_fix", "future_fix", "non_monotonic_timestamp", "invalid_timestamp", "invalid_receipt_timestamp"].contains(reason ?? "")
            let latest = sample.observation.timestamp.isFinite && !invalidTime ? max(previous.0 ?? sample.observation.timestamp, sample.observation.timestamp) : previous.0
            // Observation time belongs to the sensor/replay clock; saved time belongs to this recording session.
            let savedAt: Double?
            if let recordedAt { savedAt = recordedAt.isFinite ? recordedAt : nil }
            else { savedAt = !invalidTime && sample.observation.timestamp.isFinite ? sample.observation.timestamp : nil }
            let latestSavedAt = savedAt.map { max(previous.3 ?? $0, $0) } ?? previous.3
            try write("UPDATE sessions SET maximum_speed_kmh=MAX(maximum_speed_kmh,?),last_timestamp=?,last_saved_at=?,previous_speed=?,segment=? WHERE id=?", [
                .number(speed ?? 0), numeric(latest), numeric(latestSavedAt), numeric(speed), .integer(Int64(segment)), .text(id)
            ])
        }
    }

    /// Best-effort caller diagnostics remain private and are exported with their session.
    /// These are error/context events, not a CPU, memory, or battery profiler.
    public func recordDiagnostic(session id: String, at time: Double, kind: String,
                                 domain: String? = nil, code: Int? = nil, detail: String? = nil) throws {
        try validate(id)
        guard time.isFinite, !kind.isEmpty, kind.count <= 128 else { throw RideStoreError.invalidValue("Invalid diagnostic") }
        var payload: [String: Any] = ["kind": kind]
        if let domain { payload["domain"] = String(domain.prefix(256)) }
        if let code { payload["code"] = code }
        if let detail { payload["detail"] = String(detail.prefix(2000)) }
        let json = String(decoding: try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]), as: UTF8.self)
        try write("INSERT INTO diagnostics(session_id,timestamp,payload_json) VALUES(?,?,?)", [.text(id), .number(time), .text(json)])
    }

    public func setStatus(_ status: String, session id: String, at: Double) throws {
        try validate(id)
        let terminal = ["completed", "finished", "ended", "interrupted"].contains(status)
        guard at.isFinite, terminal || ["recording", "paused"].contains(status) else { throw RideStoreError.invalidValue("Invalid session status or time") }
        try transaction {
            let old: String = try statement("SELECT status FROM sessions WHERE id=?", [.text(id)]) { pointer in
                guard sqlite3_step(pointer) == SQLITE_ROW, let value = text(pointer, 0) else { throw RideStoreError.invalidSession("Session does not exist") }
                return value
            }
            guard old == "recording" || old == "paused" else { throw RideStoreError.invalidSession("Session has ended") }
            try write("UPDATE sessions SET status=?,ended_at=?,segment=segment+1,previous_speed=NULL WHERE id=?", [.text(status), terminal ? .number(at) : .null, .text(id)])
            try write("INSERT INTO status_events(session_id,status,timestamp) VALUES(?,?,?)", [.text(id), .text(status), .number(at)])
        }
    }

    public func recoverInterrupted(at: Double) throws {
        guard at.isFinite else { throw RideStoreError.invalidValue("Invalid recovery time") }
        try transaction {
            try write("INSERT INTO status_events(session_id,status,timestamp) SELECT id,'interrupted',? FROM sessions WHERE status IN ('recording','paused')", [.number(at)])
            try write("UPDATE sessions SET status='interrupted',ended_at=MAX(started_at,COALESCE(last_saved_at,started_at)),previous_speed=NULL WHERE status IN ('recording','paused')")
        }
    }

    public func summaries() throws -> [RideSummary] {
        try statement("SELECT id,mode,started_at,ended_at,maximum_speed_kmh,status FROM sessions ORDER BY started_at DESC,id DESC") { pointer in
            var result: [RideSummary] = []
            var code = sqlite3_step(pointer)
            while code == SQLITE_ROW {
                guard let id = text(pointer, 0), let modeText = text(pointer, 1), let mode = RideMode(rawValue: modeText), let status = text(pointer, 5) else {
                    throw RideStoreError.database("Malformed session")
                }
                result.append(RideSummary(id: id, mode: mode, startedAt: sqlite3_column_double(pointer, 2), endedAt: number(pointer, 3), maximumSpeedKmh: sqlite3_column_double(pointer, 4), status: status))
                code = sqlite3_step(pointer)
            }
            guard code == SQLITE_DONE else { throw RideStoreError.database(message()) }
            return result
        }
    }

    /// Returns at most limit points over the entire ride, retaining bucket endpoints and extrema.
    /// The persisted segment prevents a line from bridging missing fixes or a recording pause.
    public func points(session id: String, limit: Int) throws -> [SpeedPoint] {
        try validate(id)
        guard limit > 0 else { return [] }
        let bounded = min(limit, 10_000), buckets = max(1, min(limit, 10_000) / 4)
        return try statement("""
            WITH ordered AS (
                SELECT id,timestamp,speed_kmh,exclusion_reason,segment,
                    ROW_NUMBER() OVER (ORDER BY id)-1 AS rn,COUNT(*) OVER () AS total
                FROM samples WHERE session_id=? AND timestamp IS NOT NULL
                    AND (exclusion_reason IS NULL OR exclusion_reason NOT IN
                        ('stale_fix','future_fix','non_monotonic_timestamp','invalid_timestamp','invalid_receipt_timestamp'))
            ), grouped AS (
                SELECT *,CAST(rn*?/total AS INTEGER) AS bucket FROM ordered
            ), ranked AS (
                SELECT *,ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY speed_kmh DESC,id) AS high,
                    ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY speed_kmh ASC,id) AS low,
                    ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY id) AS first,
                    ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY id DESC) AS last FROM grouped
            )
            SELECT id,timestamp,speed_kmh,exclusion_reason,segment FROM ranked
            WHERE first=1 OR last=1 OR high=1 OR low=1 ORDER BY id LIMIT ?
            """, [.text(id), .integer(Int64(buckets)), .integer(Int64(bounded))]) { pointer in
            var result: [SpeedPoint] = [], code = sqlite3_step(pointer)
            while code == SQLITE_ROW {
                result.append(SpeedPoint(id: String(sqlite3_column_int64(pointer, 0)), timestamp: sqlite3_column_double(pointer, 1), speedKmh: number(pointer, 2), reason: text(pointer, 3), segment: Int(sqlite3_column_int64(pointer, 4))))
                code = sqlite3_step(pointer)
            }
            guard code == SQLITE_DONE else { throw RideStoreError.database(message()) }
            return result
        }
    }

    public func delete(session id: String) throws {
        try validate(id)
        try transaction {
            try statement("SELECT status FROM sessions WHERE id=?", [.text(id)]) { pointer in
                guard sqlite3_step(pointer) == SQLITE_ROW, let status = text(pointer, 0) else { throw RideStoreError.invalidSession("Session does not exist") }
                guard status != "recording" && status != "paused" else { throw RideStoreError.invalidSession("End the recording before deleting it") }
            }
            try write("DELETE FROM sessions WHERE id=?", [.text(id)])
        }
    }

    public func exportCSV(session id: String, to url: URL) throws {
        try validate(id)
        guard url.isFileURL else { throw RideStoreError.invalidValue("CSV must be exported to a local file") }
        let mode: String = try statement("SELECT mode FROM sessions WHERE id=?", [.text(id)]) { pointer in
            guard sqlite3_step(pointer) == SQLITE_ROW, let value = text(pointer, 0) else { throw RideStoreError.invalidSession("Session does not exist") }
            return value
        }
        let folder = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let temporary = folder.appendingPathComponent(".railvelo-export-\(UUID().uuidString).tmp")
        guard FileManager.default.createFile(atPath: temporary.path, contents: nil) else { throw RideStoreError.database("Could not create CSV") }
        defer { try? FileManager.default.removeItem(at: temporary) }
        let handle = try FileHandle(forWritingTo: temporary)
        defer { try? handle.close() }
        func row(_ fields: [String]) throws {
            let escaped = fields.map { "\"" + $0.replacingOccurrences(of: "\"", with: "\"\"") + "\"" }.joined(separator: ",") + "\r\n"
            try handle.write(contentsOf: Data(escaped.utf8))
        }
        func value(_ number: Double?) -> String { number.map { String($0) } ?? "" }
        let formatter = ISO8601DateFormatter()
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        func utc(_ time: Double) -> String { time.isFinite ? formatter.string(from: Date(timeIntervalSince1970: time)) : "" }
        try row(["record_type","session_id","mode","time_utc","unix_seconds","time_zone","latitude","longitude","coordinate_reference_system","horizontal_accuracy_m","raw_speed_mps","speed_accuracy_mps","course_deg","speed_kmh","speed_valid","exclusion_reason","match_status","match_reason","route_id","direction","direction_label","previous_station_id","next_station_id","distance_to_next_m","progress","confidence","uncertainty_m","matched_latitude","matched_longitude","edge_id","offset_m","events_json","match_json","observation_json","segment","session_status","received_unix_seconds","persistence_started_unix_seconds","details_json"])
        try statement("SELECT observation_json,match_json,speed_kmh,exclusion_reason,segment,received_at,persistence_started_at FROM samples WHERE session_id=? ORDER BY id", [.text(id)]) { pointer in
            var code = sqlite3_step(pointer)
            while code == SQLITE_ROW {
                guard let raw = text(pointer, 0), let matched = text(pointer, 1) else { throw RideStoreError.database("Malformed sample") }
                let observation = try decoder().decode(Observation.self, from: Data(raw.utf8))
                let result = try decoder().decode(MatchResult.self, from: Data(matched.utf8))
                let speed = number(pointer, 2)
                let events = String(decoding: try encoder().encode(result.events), as: UTF8.self)
                try row(["observation",id,mode,utc(observation.timestamp),value(observation.timestamp),"UTC (+00:00)",value(observation.lat),value(observation.lon),"WGS84 (EPSG:4326)",value(observation.horizontalAccuracyM),value(observation.speedMps),value(observation.speedAccuracyMps),value(observation.courseDeg),value(speed),speed == nil ? "false" : "true",text(pointer, 3) ?? "",result.status,result.reason,result.routeId ?? "",String(result.direction),result.directionLabel ?? "",result.previousStationId ?? "",result.nextStationId ?? "",value(result.distanceToNextM),value(result.progress),value(result.confidence),value(result.uncertaintyM),value(result.lat),value(result.lon),result.edgeId ?? "",value(result.offsetM),events,matched,raw,String(sqlite3_column_int64(pointer, 4)),"",value(number(pointer, 5)),value(number(pointer, 6)),""])
                code = sqlite3_step(pointer)
            }
            guard code == SQLITE_DONE else { throw RideStoreError.database(message()) }
        }
        try statement("SELECT status,timestamp FROM status_events WHERE session_id=? ORDER BY id", [.text(id)]) { pointer in
            var code = sqlite3_step(pointer)
            while code == SQLITE_ROW {
                let time = sqlite3_column_double(pointer, 1)
                var fields = Array(repeating: "", count: 39)
                fields[0] = "session_status"; fields[1] = id; fields[2] = mode; fields[3] = utc(time)
                fields[4] = value(time); fields[5] = "UTC (+00:00)"; fields[8] = "WGS84 (EPSG:4326)"
                fields[35] = text(pointer, 0) ?? ""
                try row(fields)
                code = sqlite3_step(pointer)
            }
            guard code == SQLITE_DONE else { throw RideStoreError.database(message()) }
        }
        try statement("SELECT timestamp,payload_json FROM diagnostics WHERE session_id=? ORDER BY id", [.text(id)]) { pointer in
            var code = sqlite3_step(pointer)
            while code == SQLITE_ROW {
                let time = sqlite3_column_double(pointer, 0)
                var fields = Array(repeating: "", count: 39)
                fields[0] = "diagnostic"; fields[1] = id; fields[2] = mode; fields[3] = utc(time)
                fields[4] = value(time); fields[5] = "UTC (+00:00)"; fields[38] = text(pointer, 1) ?? ""
                try row(fields)
                code = sqlite3_step(pointer)
            }
            guard code == SQLITE_DONE else { throw RideStoreError.database(message()) }
        }
        try statement("SELECT started_at,ended_at,last_saved_at,maximum_speed_kmh,status FROM sessions WHERE id=?", [.text(id)]) { pointer in
            guard sqlite3_step(pointer) == SQLITE_ROW else { throw RideStoreError.invalidSession("Session does not exist") }
            let started = sqlite3_column_double(pointer, 0), ended = number(pointer, 1)
            let summary: [String: Any] = ["started_at": started, "ended_at": ended.map { $0 as Any } ?? NSNull(),
                "last_saved_at": number(pointer, 2).map { $0 as Any } ?? NSNull(),
                "maximum_speed_kmh": sqlite3_column_double(pointer, 3), "status": text(pointer, 4) ?? "",
                "timing_semantics": "received_to_persistence_start_excludes_sql_and_commit"]
            var fields = Array(repeating: "", count: 39)
            fields[0] = "session_summary"; fields[1] = id; fields[2] = mode; fields[3] = utc(ended ?? started)
            fields[4] = value(ended ?? started); fields[5] = "UTC (+00:00)"; fields[35] = text(pointer, 4) ?? ""
            fields[38] = String(decoding: try JSONSerialization.data(withJSONObject: summary, options: [.sortedKeys]), as: UTF8.self)
            try row(fields)
        }
        try handle.synchronize()
        try handle.close()
        if FileManager.default.fileExists(atPath: url.path) {
            _ = try FileManager.default.replaceItemAt(url, withItemAt: temporary)
        } else { try FileManager.default.moveItem(at: temporary, to: url) }
    }
}
