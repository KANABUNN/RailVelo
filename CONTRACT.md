# Implementation contract (v0.3)

Coordinates are WGS84 latitude/longitude, distances metres, times Unix seconds UTC,
speed m/s and heading degrees clockwise from north. No route names or coordinates
belong in the inference source code.

Network interchange JSON:
```
{"schema_version":1,"nodes":[{"id":"n","lat":0,"lon":0}],
 "edges":[{"id":"e","from_node":"n","to_node":"m","route_ids":["r"],"coordinates":[[lat,lon],[lat,lon]],"length_m":1,"point_measures_m":[0,1]}],
 "routes":[{"id":"r","name":"...","forward_label":"...","reverse_label":"..."}],
 "route_edges":[{"route_id":"r","edge_id":"e","sequence":0,"direction":1,"start_m":0}],
 "stations":[{"id":"s","name":"..."}],
 "route_stations":[{"route_id":"r","station_id":"s","sequence":0,"measure_m":0,"radius_m":100}]}
```
Edges are bidirectional; connectivity requires common node IDs (geometric crossing
alone is not a connection). Coordinates follow from_node -> to_node. Route edges
form a contiguous ordered path; direction is +1 or -1. Multiple routes may share
an edge. Station measures are projected platform midpoints, radius is a tunable
inference envelope, not an authoritative platform boundary.

SQLite: metadata(key TEXT PRIMARY KEY,value TEXT); nodes(id TEXT PRIMARY KEY,lat
REAL,lon REAL); edges(id TEXT PRIMARY KEY,from_node TEXT,to_node TEXT,length_m REAL,
coordinates_json TEXT,route_ids_json TEXT,point_measures_json TEXT); routes(id TEXT PRIMARY KEY,name TEXT,
forward_label TEXT,reverse_label TEXT); route_edges(route_id TEXT,edge_id TEXT,
sequence INTEGER,direction INTEGER,start_m REAL,PRIMARY KEY(route_id,sequence));
stations(id TEXT PRIMARY KEY,name TEXT); route_stations(route_id TEXT,station_id
TEXT,sequence INTEGER,measure_m REAL,radius_m REAL,PRIMARY KEY(route_id,sequence)).
Use foreign keys and validate continuity, lengths and station order.
point_measures_m / point_measures_json are optional for consumers; when present,
they preserve source ellipsoid cumulative distances at every vertex. The delivered
SQLite includes them. Missing arrays are computed proportionally from geometry.

Observation JSON fields: timestamp (number), lat/lon (number or null for loss),
horizontal_accuracy_m (number), speed_mps (number or null), speed_accuracy_mps
(number or null), course_deg (number or null). Negative or invalid sensor values
mean unavailable; invalid time/coordinate values must fail safely.

Result fields: timestamp, status (matched/predicted/uncertain/lost/rejected),
edge_id, lat, lon, offset_m, route_id (nullable), direction (+1/-1/0 in route
orientation), direction_label, previous_station_id, next_station_id,
distance_to_next_m, progress, confidence [0,1], uncertainty_m, reason,
candidates [{edge_id,route_id,direction,offset_m,probability}],
events [{type,timestamp,station_id,confidence}]. Results of insufficient confidence
must not expose a confirmed route/direction/station pair; candidates may remain.
No next-stop API is offered; next_station_id means next station physically passed.
Event types are arrival, departure, pass, between_station_stop, resume. Event times
are estimated occurrence times; pass is emitted after station-envelope exit.
Candidate direction is in edge orientation; result direction is route orientation.
Optional result fields and absent event station_id are explicitly JSON null.

Python public API: railvelo.network.Network.from_json(path), .from_sqlite(path),
Network(document); railvelo.matcher.Matcher(network).update(observation_dict)
returns a serializable dict. scripts/replay.py consumes JSONL and writes JSONL.
Swift mirrors JSON field names via Codable, Network JSON loading and
MapMatcher(network:).update(Observation) -> MatchResult. Separate SQLite and Core
Location targets. Cross-language comparison uses replay executables.

