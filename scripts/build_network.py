"""Verify and adapt the preserved N02 v0.2 bundle to the v0.3 runtime schema.

Python 3.11+ standard library only. Never edits the upstream SQLite or shapes.
Rebuild the upstream bundle separately with its pinned GIS dependencies.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_only(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def geodesic_distance(a, b):
    """Vincenty inverse on GRS80; short N02 segments avoid antipodal issues."""
    radius, flattening = 6378137.0, 1 / 298.257222101
    minor = radius * (1 - flattening)
    u1, u2 = (math.atan((1 - flattening) * math.tan(math.radians(p[0]))) for p in (a, b))
    delta = math.radians(b[1] - a[1])
    lam = delta
    for _ in range(100):
        ss = math.hypot(math.cos(u2) * math.sin(lam), math.cos(u1) * math.sin(u2) - math.sin(u1) * math.cos(u2) * math.cos(lam))
        if ss == 0:
            return 0.0
        cs = math.sin(u1) * math.sin(u2) + math.cos(u1) * math.cos(u2) * math.cos(lam)
        sigma = math.atan2(ss, cs)
        sa = math.cos(u1) * math.cos(u2) * math.sin(lam) / ss
        c2a = 1 - sa * sa
        c2sm = cs - 2 * math.sin(u1) * math.sin(u2) / c2a if c2a > 1e-15 else 0
        cc = flattening / 16 * c2a * (4 + flattening * (4 - 3 * c2a))
        previous = lam
        lam = delta + (1 - cc) * flattening * sa * (sigma + cc * ss * (c2sm + cc * cs * (-1 + 2 * c2sm * c2sm)))
        if abs(lam - previous) < 1e-12:
            break
    else:
        raise ValueError("Geodesic calculation failed to converge")
    u2v = c2a * (radius * radius - minor * minor) / (minor * minor)
    aa = 1 + u2v / 16384 * (4096 + u2v * (-768 + u2v * (320 - 175 * u2v)))
    bb = u2v / 1024 * (256 + u2v * (-128 + u2v * (74 - 47 * u2v)))
    ds = bb * ss * (c2sm + bb / 4 * (cs * (-1 + 2 * c2sm * c2sm) - bb / 6 * c2sm * (-3 + 4 * ss * ss) * (-3 + 4 * c2sm * c2sm)))
    return minor * aa * (sigma - ds)


def competing_geometry(upstream):
    """Conservative other-route candidates, with no invented cross-route links.

    Upstream's pinned EPSG:6668->4326 operation is PROJ noop, accuracy 1 m.
    Reusing source numeric coordinates is exactly that pinned operation.
    """
    source = json.loads((upstream / "output/nearby_excluded.geojson").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for feature in source["features"]:
        prop = feature["properties"]
        key = (prop["N02_004"], prop["N02_003"])
        groups[key].append(feature)
    routes, nodes, edges = [], {}, []
    for key, features in sorted(groups.items()):
        route_id = "nearby." + hashlib.sha256("|".join(key).encode()).hexdigest()[:16]
        routes.append({"id": route_id, "name": key[0] + " " + key[1], "forward_label": "方向未定義", "reverse_label": "方向未定義"})
        # Only an identical source vertex within this same operator and line can
        # connect candidates. Crossings, close tracks, and corridor stay separate.
        occurrences = Counter(tuple(p) for f in features for p in f["geometry"]["coordinates"])
        seen = set()
        for f in features:
            coordinates = [tuple(reversed(p)) for p in f["geometry"]["coordinates"]]
            cuts = [0] + [i for i, p in enumerate(coordinates[1:-1], 1) if occurrences[tuple(reversed(p))] > 1] + [len(coordinates)-1]
            for begin, end in zip(cuts, cuts[1:]):
                points = coordinates[begin:end+1]
                canonical = min(tuple(points), tuple(reversed(points)))
                if len(points) < 2 or canonical in seen:
                    continue
                seen.add(canonical)
                measures = [0.0]
                for a, b in zip(points, points[1:]):
                    measures.append(measures[-1] + geodesic_distance(a, b))
                if measures[-1] <= 0:
                    continue
                nodeids = []
                for p in (points[0], points[-1]):
                    nid = route_id + ".n." + hashlib.sha256(repr(p).encode()).hexdigest()[:16]
                    nodes[nid] = {"id": nid, "lat": p[0], "lon": p[1]}
                    nodeids.append(nid)
                eid = route_id + ".e." + hashlib.sha256(repr(canonical).encode()).hexdigest()[:16]
                edges.append({"id": eid, "from_node": nodeids[0], "to_node": nodeids[1], "route_ids": [route_id],
                              "coordinates": [list(p) for p in points], "length_m": measures[-1], "point_measures_m": measures,
                              "source_ids": [f["properties"]["source_id"]], "role": "nearby_competitor",
                              "topology_quality": "same_operator_line_identical_vertex_no_corridor_connection"})
    return routes, list(nodes.values()), edges


def adapt(config):
    upstream = ROOT / config["upstream_root"]
    manifest_path = upstream / "MANIFEST.sha256"
    if sha(manifest_path) != config["expected_upstream_manifest_sha256"]:
        raise ValueError("Upstream bundle manifest checksum differs")
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        file = (upstream / relative).resolve()
        if not file.is_relative_to(upstream.resolve()) or not file.is_file() or sha(file) != digest:
            raise ValueError("Upstream bundle file checksum differs: " + relative)
    path = upstream / config["upstream_database"]
    if sha(path) != config["expected_database_sha256"]:
        raise ValueError("Upstream SQLite checksum differs; review before updating config")
    manifest = json.loads((upstream / "data/raw/manifest.json").read_text(encoding="utf-8"))
    archive = upstream / "data/raw" / manifest["archive"]
    if sha(archive) != config["expected_archive_sha256"]:
        raise ValueError("Official N02 archive checksum differs")
    db = read_only(path)
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Upstream SQLite integrity/foreign keys failed")
    meta = {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value_json FROM rm_metadata")}
    route_id = config["route_id"]
    edge_meta = {r["edge_id"]: dict(r) for r in db.execute("SELECT * FROM rm_edge_metadata")}
    all_edges = {r["id"]: dict(r) for r in db.execute("SELECT * FROM rail_edges")}
    source_path = [dict(r) for r in db.execute("SELECT * FROM rm_reference_path ORDER BY sequence")]
    # Keep the directed reference orientation, then one of each off-path twin.
    selected = [r["edge_id"] for r in source_path]
    represented = set(selected) | {edge_meta[e]["reverse_edge_id"] for e in selected}
    for eid in sorted(all_edges):
        if eid not in represented:
            selected.append(eid)
            represented.update((eid, edge_meta[eid]["reverse_edge_id"]))
    if len(represented) != len(all_edges):
        raise ValueError("Physical edge twin collapse lost data")
    edges = []
    for eid in selected:
        row = all_edges[eid]
        points = [dict(r) for r in db.execute("SELECT * FROM rail_edge_points WHERE edge_id=? ORDER BY point_index", (eid,))]
        edges.append({"id": eid, "from_node": row["from_node"], "to_node": row["to_node"],
                      "route_ids": [route_id], "coordinates": [[p["latitude"], p["longitude"]] for p in points],
                      "length_m": row["length_m"], "point_measures_m": [p["progress_m"] for p in points],
                      "source_ids": json.loads(edge_meta[eid]["source_ids_json"]),
                      "role": edge_meta[eid]["role"], "topology_quality": edge_meta[eid]["topology_quality"]})
    nodes = [{"id": r["id"], "lat": r["latitude"], "lon": r["longitude"]}
             for r in db.execute("SELECT * FROM rm_nodes ORDER BY id")]
    start = source_path[0]["begin_chainage_m"]
    route_edges = [{"route_id": route_id, "edge_id": r["edge_id"], "sequence": i,
                    "direction": 1, "start_m": r["begin_chainage_m"] - start}
                   for i, r in enumerate(source_path)]
    stations, route_stations = [], []
    for r in db.execute("SELECT s.*,p.* FROM stations s JOIN rm_station_positions p ON s.id=p.station_id ORDER BY p.sequence"):
        radius = max(config["station_radius_min_m"], min(config["station_radius_max_m"],
                     (r["extent_end_m"] - r["extent_begin_m"]) / 2 + config["station_radius_margin_m"]))
        stations.append({"id": r["id"], "name": r["public_name"]})
        route_stations.append({"route_id": route_id, "station_id": r["id"], "sequence": r["sequence"],
                               "measure_m": r["chainage_m"] - start, "radius_m": radius,
                               "extent_begin_m": r["extent_begin_m"] - start,
                               "extent_end_m": r["extent_end_m"] - start,
                               "extent_quality": "N02_station_line_not_surveyed_platform"})
    if [s["name"] for s in stations] != meta["config"]["stations"]:
        raise ValueError("Station order differs from preserved official-source configuration")
    document = {"schema_version": 1, "nodes": nodes, "edges": edges,
                "routes": [{"id": route_id, "name": meta["config"]["public_name"],
                            "forward_label": config["forward_label"], "reverse_label": config["reverse_label"]}],
                "route_edges": route_edges, "stations": stations, "route_stations": route_stations,
                "metadata": {"source": "国土交通省 国土数値情報 鉄道データ N02 2025年版を加工",
                             "source_url": manifest["catalog_checked"], "source_date": "2025-12-31",
                             "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
                             "upstream_sqlite_sha256": sha(path), "source_archive_sha256": sha(archive),
                             "coordinate_system": "WGS84 EPSG:4326 converted by upstream from JGD2011 EPSG:6668",
                             "distance_model": meta["distance_model"], "center_length_m": meta["reference_center_length_m"],
                             "expected_station_count": len(meta["config"]["stations"]),
                             "origin_shift_m": -start, "topology": "source_vertex_connectivity_only_not_verified_turnouts",
                             "competing_routes": "Nearby source lines and station geometries within upstream 150m audit are imported as isolated other-route candidates; route switching topology is unknown",
                             "alternate_edges": "Three source alternate edges have no reference station chainage; return uncertain distances there"}}
    competitors, extra_nodes, extra_edges = competing_geometry(upstream)
    document["routes"].extend(competitors)
    document["nodes"].extend(extra_nodes)
    document["edges"].extend(extra_edges)
    db.close()
    return document


SCHEMA = """
PRAGMA foreign_keys=ON;
PRAGMA user_version=3;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE nodes(id TEXT PRIMARY KEY,lat REAL NOT NULL,lon REAL NOT NULL);
CREATE TABLE routes(id TEXT PRIMARY KEY,name TEXT NOT NULL,forward_label TEXT NOT NULL,reverse_label TEXT NOT NULL);
CREATE TABLE edges(id TEXT PRIMARY KEY,from_node TEXT NOT NULL REFERENCES nodes(id),to_node TEXT NOT NULL REFERENCES nodes(id),length_m REAL NOT NULL CHECK(length_m>0),coordinates_json TEXT NOT NULL,route_ids_json TEXT NOT NULL,point_measures_json TEXT NOT NULL);
CREATE TABLE route_edges(route_id TEXT NOT NULL REFERENCES routes(id),edge_id TEXT NOT NULL REFERENCES edges(id),sequence INTEGER NOT NULL,direction INTEGER NOT NULL CHECK(direction IN (-1,1)),start_m REAL NOT NULL,PRIMARY KEY(route_id,sequence));
CREATE TABLE stations(id TEXT PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE route_stations(route_id TEXT NOT NULL REFERENCES routes(id),station_id TEXT NOT NULL REFERENCES stations(id),sequence INTEGER NOT NULL,measure_m REAL NOT NULL,radius_m REAL NOT NULL CHECK(radius_m>0),PRIMARY KEY(route_id,sequence));
CREATE INDEX idx_edges_from ON edges(from_node);
CREATE INDEX idx_edges_to ON edges(to_node);
CREATE INDEX idx_route_edge ON route_edges(edge_id);
"""


def write_database(path, doc):
    # SQLite is generated through an in-memory database and replaced as bytes.
    # No source database is opened writable or altered in place.
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO metadata VALUES (?,?)", [("schema_version", "1")] +
                   [(k, json.dumps(v, ensure_ascii=False)) for k, v in doc["metadata"].items()])
    db.executemany("INSERT INTO nodes VALUES (:id,:lat,:lon)", doc["nodes"])
    db.executemany("INSERT INTO routes VALUES (:id,:name,:forward_label,:reverse_label)", doc["routes"])
    db.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", [(e["id"], e["from_node"], e["to_node"], e["length_m"],
                   json.dumps(e["coordinates"], separators=(",", ":")), json.dumps(e["route_ids"]),
                   json.dumps(e["point_measures_m"], separators=(",", ":"))) for e in doc["edges"]])
    db.executemany("INSERT INTO route_edges VALUES (:route_id,:edge_id,:sequence,:direction,:start_m)", doc["route_edges"])
    db.executemany("INSERT INTO stations VALUES (:id,:name)", doc["stations"])
    db.executemany("INSERT INTO route_stations VALUES (:route_id,:station_id,:sequence,:measure_m,:radius_m)", doc["route_stations"])
    db.commit()
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Runtime SQLite failed integrity checks")
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(db, "serialize"):
        path.write_bytes(db.serialize())
    else:
        target = sqlite3.connect(path)
        db.backup(target)
        target.close()
    db.close()


def validate(doc, path):
    checks = []
    def check(name, success, **details):
        checks.append({"name": name, "passed": bool(success), "details": details})
    nodes = {n["id"]: n for n in doc["nodes"]}
    edges = {e["id"]: e for e in doc["edges"]}
    check("unique_ids", len(nodes) == len(doc["nodes"]) and len(edges) == len(doc["edges"]))
    check("all_geometry_finite", all(math.isfinite(v) for e in edges.values() for p in e["coordinates"] for v in p))
    check("positive_lengths", all(e["length_m"] > 0 for e in edges.values()))
    endpoints = []
    for e in edges.values():
        if e["coordinates"][0] != [nodes[e["from_node"]]["lat"], nodes[e["from_node"]]["lon"]] or e["coordinates"][-1] != [nodes[e["to_node"]]["lat"], nodes[e["to_node"]]["lon"]]:
            endpoints.append(e["id"])
    check("exact_edge_node_endpoints", not endpoints, errors=endpoints)
    check("point_measures_preserved", all(e["point_measures_m"][0] == 0 and abs(e["point_measures_m"][-1] - e["length_m"]) < 1e-6 and all(b > a for a, b in zip(e["point_measures_m"], e["point_measures_m"][1:])) for e in edges.values()))
    length_error = max(abs(sum(geodesic_distance(a, b) for a, b in zip(e["coordinates"], e["coordinates"][1:])) - e["length_m"]) for e in edges.values())
    check("independent_ellipsoid_length_recomputation", length_error < 0.001, maximum_error_m=length_error)
    duplicate = Counter((tuple(e["route_ids"]), tuple(map(tuple, min(e["coordinates"], list(reversed(e["coordinates"])))))) for e in edges.values())
    check("no_duplicate_geometry_within_same_route", max(duplicate.values(), default=0) == 1)
    path_errors = []
    chain = doc["route_edges"]
    for i, r in enumerate(chain):
        e = edges[r["edge_id"]]
        if i:
            prior = edges[chain[i-1]["edge_id"]]
            if prior["to_node"] != e["from_node"] or abs(chain[i-1]["start_m"] + prior["length_m"] - r["start_m"]) > 1e-6:
                path_errors.append(i)
    check("continuous_reference_path_without_snap", not path_errors, errors=path_errors)
    positions = doc["route_stations"]
    gaps = [b["measure_m"] - a["measure_m"] for a, b in zip(positions, positions[1:])]
    check("configured_stations_monotonic", len(positions) == doc["metadata"]["expected_station_count"] and all(g > 0 for g in gaps), count=len(positions))
    check("station_extent_contains_center", all(0 <= s["extent_begin_m"] <= s["measure_m"] <= s["extent_end_m"] <= chain[-1]["start_m"] + edges[chain[-1]["edge_id"]]["length_m"] for s in positions))
    total = positions[-1]["measure_m"] - positions[0]["measure_m"]
    check("center_length_matches_upstream", abs(total - doc["metadata"]["center_length_m"]) < 1e-6, center_length_m=total)
    db = read_only(path)
    check("sqlite_integrity", db.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    check("sqlite_foreign_keys", not db.execute("PRAGMA foreign_key_check").fetchall())
    for table in ("nodes", "edges", "routes", "route_edges", "stations", "route_stations"):
        check("sqlite_count_" + table, db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == len(doc[table]))
    contents_match = True
    for e in edges.values():
        r = db.execute("SELECT * FROM edges WHERE id=?", (e["id"],)).fetchone()
        contents_match &= r["from_node"] == e["from_node"] and r["to_node"] == e["to_node"] and r["length_m"] == e["length_m"] and json.loads(r["coordinates_json"]) == e["coordinates"] and json.loads(r["route_ids_json"]) == e["route_ids"] and json.loads(r["point_measures_json"]) == e["point_measures_m"]
    for s in positions:
        r = db.execute("SELECT * FROM route_stations WHERE route_id=? AND sequence=?", (s["route_id"], s["sequence"])).fetchone()
        contents_match &= all(r[k] == s[k] for k in r.keys())
    check("sqlite_runtime_values_match_json", contents_match)
    db.close()
    degree = Counter(n for e in edges.values() for n in (e["from_node"], e["to_node"]))
    main_nodes = {n for e in edges.values() if e["role"] != "nearby_competitor" for n in (e["from_node"], e["to_node"])}
    other_nodes = {n for e in edges.values() if e["role"] == "nearby_competitor" for n in (e["from_node"], e["to_node"])}
    check("no_fabricated_cross_route_connections", not (main_nodes & other_nodes))
    check("competing_routes_have_no_invented_chainage", not any(r["route_id"].startswith("nearby.") for r in doc["route_edges"] + doc["route_stations"]))
    return {"status": "PASS_WITH_DOCUMENTED_LIMITATIONS" if all(c["passed"] for c in checks) else "FAIL",
            "passed": sum(c["passed"] for c in checks), "total": len(checks), "checks": checks,
            "counts": {"nodes": len(nodes), "physical_edges": len(edges), "reference_edges": len(chain), "alternate_edges": sum(e["role"] == "candidate" for e in edges.values()), "nearby_competitor_edges": sum(e["role"] == "nearby_competitor" for e in edges.values()), "routes": len(doc["routes"]), "stations": len(positions), "source_junction_candidates": sum(d > 2 for d in degree.values())},
            "center_length_m": total, "full_path_length_m": sum(edges[r["edge_id"]]["length_m"] for r in chain),
            "interstation_min_m": min(gaps), "interstation_max_m": max(gaps), "sqlite_sha256": sha(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/network.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    doc = adapt(config)
    dump(args.output / "network.json", doc)
    dbpath = args.output / "railway.sqlite"
    write_database(dbpath, doc)
    report = validate(doc, dbpath)
    dump(ROOT / "docs/data-quality.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
