-- JR Kyushu Rail Monitor / MVP-1 SQLite schema v0.2
-- No commercial train timetable tables are included by design.
-- Geometry is stored as WGS84-compatible latitude/longitude degrees; metric distance is derived separately.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS data_releases (
  id TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_date TEXT,
  built_utc TEXT NOT NULL,
  sha256 TEXT,
  license_id TEXT NOT NULL,
  attribution TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operators (
  id TEXT PRIMARY KEY,
  public_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rail_routes (
  id TEXT PRIMARY KEY,
  operator_id TEXT NOT NULL REFERENCES operators(id),
  public_name TEXT NOT NULL,
  source_release_id TEXT REFERENCES data_releases(id)
);

CREATE TABLE IF NOT EXISTS stations (
  id TEXT PRIMARY KEY,
  public_name TEXT NOT NULL,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  release_id TEXT REFERENCES data_releases(id),
  source_station_code TEXT
);

CREATE TABLE IF NOT EXISTS rail_edges (
  id TEXT PRIMARY KEY,
  route_id TEXT NOT NULL REFERENCES rail_routes(id),
  from_node TEXT NOT NULL,
  to_node TEXT NOT NULL,
  length_m REAL NOT NULL CHECK(length_m >= 0),
  geom_source_release_id TEXT REFERENCES data_releases(id)
);

CREATE INDEX IF NOT EXISTS idx_edges_route ON rail_edges(route_id);
CREATE INDEX IF NOT EXISTS idx_edges_from ON rail_edges(from_node);
CREATE INDEX IF NOT EXISTS idx_edges_to ON rail_edges(to_node);

CREATE TABLE IF NOT EXISTS rail_edge_points (
  edge_id TEXT NOT NULL REFERENCES rail_edges(id) ON DELETE CASCADE,
  point_index INTEGER NOT NULL,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  progress_m REAL NOT NULL CHECK(progress_m >= 0),
  PRIMARY KEY(edge_id, point_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS rail_edge_rtree USING rtree (
  numeric_id, min_lon, max_lon, min_lat, max_lat
);

-- ID indirection is necessary because R-Tree row IDs are integers.
CREATE TABLE IF NOT EXISTS rail_edge_spatial_keys (
  numeric_id INTEGER PRIMARY KEY,
  edge_id TEXT NOT NULL UNIQUE REFERENCES rail_edges(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS station_track_locations (
  station_id TEXT NOT NULL REFERENCES stations(id),
  edge_id TEXT NOT NULL REFERENCES rail_edges(id),
  progress_m REAL NOT NULL,
  platform_begin_m REAL,
  platform_end_m REAL,
  match_quality TEXT NOT NULL DEFAULT 'unverified',
  PRIMARY KEY(station_id, edge_id)
);
CREATE INDEX IF NOT EXISTS idx_station_track_edge ON station_track_locations(edge_id);

CREATE TABLE IF NOT EXISTS rides (
  id TEXT PRIMARY KEY,
  started_utc TEXT NOT NULL,
  ended_utc TEXT,
  label TEXT,
  final_total_distance_m REAL,
  final_max_speed_mps REAL
);

CREATE TABLE IF NOT EXISTS gps_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ride_id TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
  timestamp_utc TEXT NOT NULL,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  horizontal_accuracy_m REAL,
  speed_mps REAL,
  speed_accuracy_mps REAL,
  course_deg REAL,
  course_accuracy_deg REAL,
  quality TEXT NOT NULL CHECK(quality IN ('usable', 'low_quality', 'rejected')),
  quality_flags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_gps_ride_time ON gps_samples(ride_id, timestamp_utc);

CREATE TABLE IF NOT EXISTS match_results (
  sample_id INTEGER PRIMARY KEY REFERENCES gps_samples(id) ON DELETE CASCADE,
  edge_id TEXT REFERENCES rail_edges(id),
  progress_m REAL,
  route_id TEXT REFERENCES rail_routes(id),
  direction TEXT CHECK(direction IN ('up','down','unknown')),
  confidence TEXT NOT NULL CHECK(confidence IN ('high','medium','low','unknown')),
  source TEXT NOT NULL CHECK(source IN ('measured','extrapolated','unknown'))
);

CREATE TABLE IF NOT EXISTS station_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ride_id TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
  station_id TEXT REFERENCES stations(id),
  event_type TEXT NOT NULL CHECK(event_type IN ('arrival','departure','pass','unknown')),
  timestamp_utc TEXT NOT NULL,
  confidence TEXT NOT NULL CHECK(confidence IN ('high','medium','low','unknown')),
  derived_from_sample_id INTEGER REFERENCES gps_samples(id),
  review_state TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX IF NOT EXISTS idx_station_events_ride_time ON station_events(ride_id, timestamp_utc);

PRAGMA user_version = 2;
