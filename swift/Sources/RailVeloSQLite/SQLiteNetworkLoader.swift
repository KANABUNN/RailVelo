import Foundation
import CSQLite
import RailVeloCore

public enum SQLiteNetworkError: Error, CustomStringConvertible {
    case database(String)
    public var description: String { switch self { case .database(let detail): return detail } }
}

/// Loads a complete immutable snapshot, closes SQLite, then lets inference run offline.
/// The supplied application database is opened strictly read-only.
public enum SQLiteNetworkLoader {
    public static func load(url: URL) throws -> Network {
        var database: OpaquePointer?
        let code = sqlite3_open_v2(url.path, &database, SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX, nil)
        guard code == SQLITE_OK, let handle = database else {
            let detail = database.map { String(cString: sqlite3_errmsg($0)) } ?? "SQLite open failed"
            if let database { sqlite3_close(database) }
            throw SQLiteNetworkError.database(detail)
        }
        defer { sqlite3_close(handle) }
        func query(_ sql: String) throws -> [[String: Any]] {
            var statement: OpaquePointer?
            guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK, let statement else {
                throw SQLiteNetworkError.database(String(cString: sqlite3_errmsg(handle)))
            }
            defer { sqlite3_finalize(statement) }
            var rows: [[String: Any]] = []
            var step = sqlite3_step(statement)
            while step == SQLITE_ROW {
                var row: [String: Any] = [:]
                for index in 0..<sqlite3_column_count(statement) {
                    let name = String(cString: sqlite3_column_name(statement, index))
                    switch sqlite3_column_type(statement, index) {
                    case SQLITE_INTEGER: row[name] = sqlite3_column_int64(statement, index)
                    case SQLITE_FLOAT: row[name] = sqlite3_column_double(statement, index)
                    case SQLITE_TEXT: row[name] = String(cString: sqlite3_column_text(statement, index))
                    default: row[name] = NSNull()
                    }
                }
                rows.append(row); step = sqlite3_step(statement)
            }
            guard step == SQLITE_DONE else { throw SQLiteNetworkError.database(String(cString: sqlite3_errmsg(handle))) }
            return rows
        }
        let check = try query("PRAGMA quick_check")
        guard check.count == 1, check.first?.values.first as? String == "ok" else {
            throw SQLiteNetworkError.database("SQLite quick_check failed")
        }
        guard try query("PRAGMA foreign_key_check").isEmpty else {
            throw SQLiteNetworkError.database("SQLite foreign key check failed")
        }
        let metadata = try query("SELECT key, value FROM metadata WHERE key='schema_version'")
        guard metadata.first?["value"] as? String == "1" else {
            throw SQLiteNetworkError.database("Unsupported or missing schema_version metadata")
        }
        let hasPointMeasures = try query("PRAGMA table_info(edges)").contains { $0["name"] as? String == "point_measures_json" }
        let columns = "id,from_node,to_node,length_m,coordinates_json,route_ids_json" + (hasPointMeasures ? ",point_measures_json" : "")
        var edgeRows = try query("SELECT \(columns) FROM edges ORDER BY id")
        for i in edgeRows.indices {
            for (source, destination) in [("coordinates_json", "coordinates"), ("route_ids_json", "route_ids")] {
                guard let value = edgeRows[i].removeValue(forKey: source) as? String, let data = value.data(using: .utf8) else {
                    throw SQLiteNetworkError.database("Invalid edge JSON column")
                }
                edgeRows[i][destination] = try JSONSerialization.jsonObject(with: data)
            }
            if hasPointMeasures, let text = edgeRows[i].removeValue(forKey: "point_measures_json") as? String {
                edgeRows[i]["point_measures_m"] = try JSONSerialization.jsonObject(with: Data(text.utf8))
            }
        }
        let document: [String: Any] = [
            "schema_version": 1,
            "nodes": try query("SELECT id,lat,lon FROM nodes ORDER BY id"),
            "edges": edgeRows,
            "routes": try query("SELECT id,name,forward_label,reverse_label FROM routes ORDER BY id"),
            "route_edges": try query("SELECT route_id,edge_id,sequence,direction,start_m FROM route_edges ORDER BY route_id,sequence"),
            "stations": try query("SELECT id,name FROM stations ORDER BY id"),
            "route_stations": try query("SELECT route_id,station_id,sequence,measure_m,radius_m FROM route_stations ORDER BY route_id,sequence")
        ]
        let data = try JSONSerialization.data(withJSONObject: document)
        return try Network(document: RailVeloJSON.decoder().decode(NetworkDocument.self, from: data))
    }
}
