-- Additive provenance/quality tables. Original v0.2 DDL is kept byte-for-byte.
CREATE TABLE rm_metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE rm_nodes (
  id TEXT PRIMARY KEY, longitude REAL NOT NULL, latitude REAL NOT NULL,
  connectivity_basis TEXT NOT NULL
);
CREATE TABLE rm_source_features (
  source_id TEXT PRIMARY KEY, layer TEXT NOT NULL, archive_member TEXT NOT NULL,
  feature_index INTEGER NOT NULL, properties_json TEXT NOT NULL, geometry_json TEXT NOT NULL
);
CREATE TABLE rm_edge_metadata (
  edge_id TEXT PRIMARY KEY REFERENCES rail_edges(id),
  reverse_edge_id TEXT NOT NULL REFERENCES rail_edges(id) DEFERRABLE INITIALLY DEFERRED,
  role TEXT NOT NULL CHECK(role IN ('reference','candidate')),
  direction TEXT NOT NULL CHECK(direction IN ('up','down','unknown')),
  source_ids_json TEXT NOT NULL,
  topology_quality TEXT NOT NULL DEFAULT 'source_vertex_connectivity_only'
);
CREATE TABLE rm_reference_path (
  path_id TEXT NOT NULL, sequence INTEGER NOT NULL,
  edge_id TEXT NOT NULL REFERENCES rail_edges(id),
  begin_chainage_m REAL NOT NULL, end_chainage_m REAL NOT NULL,
  PRIMARY KEY(path_id,sequence)
);
CREATE TABLE rm_station_sources (
  source_id TEXT PRIMARY KEY REFERENCES rm_source_features(source_id),
  station_id TEXT NOT NULL REFERENCES stations(id),
  source_station_code TEXT, source_group_code TEXT,
  on_candidate_graph INTEGER NOT NULL CHECK(on_candidate_graph IN (0,1)),
  reference_offset_m REAL NOT NULL, projected_reference_chainage_m REAL NOT NULL,
  is_primary INTEGER NOT NULL CHECK(is_primary IN (0,1))
);
CREATE TABLE rm_station_positions (
  station_id TEXT PRIMARY KEY REFERENCES stations(id), sequence INTEGER NOT NULL UNIQUE,
  primary_source_id TEXT NOT NULL REFERENCES rm_station_sources(source_id),
  chainage_m REAL NOT NULL, extent_begin_m REAL NOT NULL, extent_end_m REAL NOT NULL,
  match_quality TEXT NOT NULL DEFAULT 'n02_extent_unverified'
);
CREATE TABLE rm_quality_issues (
  id TEXT PRIMARY KEY, severity TEXT NOT NULL, code TEXT NOT NULL,
  related_ids_json TEXT NOT NULL, details_json TEXT NOT NULL
);
