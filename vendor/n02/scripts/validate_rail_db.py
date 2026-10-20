"""Independently check the delivered v0.2 DB, geometry, provenance, and R-tree."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import zipfile

from pyproj import Geod, Transformer
from shapely.geometry import LineString, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
GEOD = Geod(ellps="GRS80")
FROM_DB = Transformer.from_crs(4326, 6668, always_xy=True, allow_ballpark=False)


def validate(dbpath):
    db = sqlite3.connect(f"{dbpath.resolve().as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    checks = []

    def check(name, condition, **details):
        checks.append({"name":name, "passed":bool(condition), "details":details})

    check("sqlite_integrity", db.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    check("foreign_keys", not db.execute("PRAGMA foreign_key_check").fetchall())
    check("schema_version", db.execute("PRAGMA user_version").fetchone()[0] == 2)
    baseline = sqlite3.connect(":memory:")
    schema = ROOT / "schemas/railmonitor_v0_2.sql"
    baseline.executescript(schema.read_text(encoding="utf-8-sig"))
    expected = dict(baseline.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
    actual = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
    changed = [name for name, sql in expected.items() if actual.get(name) != sql]
    check("original_v0_2_schema_unchanged", not changed, original_objects=len(expected), changed=changed,
          schema_sha256=hashlib.sha256(schema.read_bytes()).hexdigest())
    baseline.close()
    meta = {r[0]:json.loads(r[1]) for r in db.execute("SELECT key,value_json FROM rm_metadata")}
    config = meta["config"]
    release = dict(db.execute("SELECT * FROM data_releases").fetchone())
    manifest = json.loads((ROOT / "data/raw/manifest.json").read_text(encoding="utf-8"))
    raw = ROOT / "data/raw" / manifest["archive"]
    check("source_archive_hash", hashlib.sha256(raw.read_bytes()).hexdigest() == release["sha256"] == meta["source_archive_sha256"])
    originals = {}
    with zipfile.ZipFile(raw) as z:
        for layer in ("Station", "RailroadSection"):
            member = next(n for n in z.namelist() if n.endswith(f"_{layer}.geojson"))
            data = json.loads(z.read(member))
            check(f"{layer}_source_crs", data["crs"]["properties"]["name"].endswith("::6668"))
            for i, f in enumerate(data["features"]):
                originals[f"{layer}:{i:05d}"] = f
    source = {r["source_id"]: dict(r) for r in db.execute("SELECT * FROM rm_source_features")}
    bad_source, bad_filter, bad_geometry = [], [], []
    for sid, row in source.items():
        p = json.loads(row["properties_json"])
        geometry = json.loads(row["geometry_json"])
        if p != originals[sid]["properties"] or geometry != originals[sid]["geometry"]:
            bad_source.append(sid)
        if (p.get("N02_004"),p.get("N02_003"),p.get("N02_001"),p.get("N02_002")) != (config["source_operator"],config["source_line"],"11","2"):
            bad_filter.append(sid)
        g = shape(geometry)
        if not g.is_valid or g.is_empty:
            bad_geometry.append(sid)
    check("source_features_exactly_preserved", not bad_source, compared=len(source), errors=bad_source)
    check("operator_line_and_railway_type_filter", not bad_filter, freight_and_non_jr_imported=len(bad_filter))
    check("selected_geometry_valid_and_nonempty", not bad_geometry, errors=bad_geometry)
    nodes = {r["id"]:(r["longitude"],r["latitude"]) for r in db.execute("SELECT * FROM rm_nodes")}
    edge_rows = {r["id"]:dict(r) for r in db.execute("SELECT * FROM rail_edges")}
    edge_meta = {r["edge_id"]:dict(r) for r in db.execute("SELECT * FROM rm_edge_metadata")}
    points = defaultdict(list)
    for r in db.execute("SELECT * FROM rail_edge_points ORDER BY edge_id,point_index"):
        points[r["edge_id"]].append(dict(r))
    max_length_error = 0.0
    bad_progress, bad_endpoints, bad_twins, unsupported, nonfinite = [], [], [], [], []
    for eid, e in edge_rows.items():
        ps = points[eid]
        coords = [(p["longitude"],p["latitude"]) for p in ps]
        values = [v for p in ps for v in (p["latitude"],p["longitude"],p["progress_m"])] + [e["length_m"]]
        if not all(math.isfinite(v) for v in values):
            nonfinite.append(eid)
        increments = []
        for a,b in zip(coords,coords[1:]):
            sa,sb = FROM_DB.transform(*a),FROM_DB.transform(*b)
            increments.append(GEOD.inv(*sa,*sb)[2])
        maximum = max([abs(sum(increments)-e["length_m"])] + [abs((b["progress_m"]-a["progress_m"])-d) for a,b,d in zip(ps,ps[1:],increments)])
        max_length_error = max(max_length_error,maximum)
        if len(ps)<2 or [p["point_index"] for p in ps] != list(range(len(ps))) or ps[0]["progress_m"] != 0 or abs(ps[-1]["progress_m"]-e["length_m"])>1e-6 or any(b["progress_m"]<=a["progress_m"] for a,b in zip(ps,ps[1:])):
            bad_progress.append(eid)
        if nodes.get(e["from_node"]) != coords[0] or nodes.get(e["to_node"]) != coords[-1]:
            bad_endpoints.append(eid)
        m = edge_meta[eid]
        twin = edge_rows[m["reverse_edge_id"]]
        twinpoints = [(p["longitude"],p["latitude"]) for p in points[twin["id"]]]
        if coords != list(reversed(twinpoints)) or twin["from_node"]!=e["to_node"] or twin["to_node"]!=e["from_node"] or abs(twin["length_m"]-e["length_m"])>1e-6:
            bad_twins.append(eid)
        ids = json.loads(m["source_ids_json"])
        railroad = [shape(json.loads(source[s]["geometry_json"])) for s in ids if s.startswith("RailroadSection:")]
        support = unary_union(railroad).buffer(1e-9)
        sourcecoords = [FROM_DB.transform(*c) for c in coords]
        if not railroad or not support.covers(LineString(sourcecoords)):
            unsupported.append(eid)
    check("finite_numeric_values", not nonfinite, errors=nonfinite)
    check("progress_indices_and_positive_lengths", not bad_progress, errors=bad_progress)
    check("ellipsoid_distance_recomputed", max_length_error<0.001, maximum_error_m=max_length_error)
    check("exact_edge_node_endpoints", not bad_endpoints, errors=bad_endpoints)
    check("reverse_virtual_edges", not bad_twins, errors=bad_twins)
    check("no_fabricated_gap_geometry", not unsupported, tolerance_degrees=1e-9, errors=unsupported)
    spatial = list(db.execute("SELECT k.edge_id,r.* FROM rail_edge_spatial_keys k JOIN rail_edge_rtree r USING(numeric_id)"))
    missing = set(edge_rows)-{r["edge_id"] for r in spatial}
    wrong_bounds=[]
    for r in spatial:
        cs=points[r["edge_id"]]
        if not all(r["min_lon"]<=p["longitude"]<=r["max_lon"] and r["min_lat"]<=p["latitude"]<=r["max_lat"] for p in cs):
            wrong_bounds.append(r["edge_id"])
    check("rtree_complete_outward_bounds", not missing and not wrong_bounds and len(spatial)==len(edge_rows),
          edges=len(spatial), missing=sorted(missing), wrong_bounds=wrong_bounds)
    path = [dict(r) for r in db.execute("SELECT * FROM rm_reference_path ORDER BY sequence")]
    previous=None
    continuity=[]
    for i,r in enumerate(path):
        e=edge_rows[r["edge_id"]]
        if r["sequence"]!=i or abs((r["end_chainage_m"]-r["begin_chainage_m"])-e["length_m"])>0.001:
            continuity.append(i)
        if previous and (previous["to"]!=e["from_node"] or abs(previous["s"]-r["begin_chainage_m"])>0.001):
            continuity.append(i)
        if edge_meta[e["id"]]["direction"]!="down":
            continuity.append(i)
        previous={"to":e["to_node"],"s":r["end_chainage_m"]}
    check("continuous_ordered_reference_path", not continuity, edges=len(path), errors=continuity)
    stations = [dict(r) for r in db.execute("SELECT s.*,p.* FROM stations s JOIN rm_station_positions p ON p.station_id=s.id ORDER BY p.sequence")]
    check("official_station_order_and_count", [r["public_name"] for r in stations]==config["stations"],
          expected=len(config["stations"]), actual=len(stations))
    check("station_chainage_monotonic", all(b["chainage_m"]>a["chainage_m"] for a,b in zip(stations,stations[1:])))
    check("center_distance_equals_reference", abs(stations[-1]["chainage_m"]-stations[0]["chainage_m"]-meta["reference_center_length_m"])<0.001)
    extent_errors=[]
    for r in db.execute("SELECT l.*,e.length_m FROM station_track_locations l JOIN rail_edges e ON e.id=l.edge_id"):
        if not (0<=r["platform_begin_m"]<=r["progress_m"]<=r["platform_end_m"]<=r["length_m"]+1e-6):
            extent_errors.append([r["station_id"],r["edge_id"]])
    check("station_extent_bounds", not extent_errors, errors=extent_errors)
    missing_st = db.execute("SELECT id FROM stations WHERE id NOT IN (SELECT station_id FROM station_track_locations)").fetchall()
    check("all_stations_have_graph_locations", not missing_st)
    source_count = db.execute("SELECT count(*) FROM rm_station_sources").fetchone()[0]
    check("all_35_station_line_variants_retained", source_count==35, source_line_features=source_count)
    for name in ("rides","gps_samples","match_results","station_events"):
        check(f"no_fabricated_{name}", db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]==0)
    check("commercial_timetable_absent", "commercial_train_runs" not in actual)
    issue_count=db.execute("SELECT count(*) FROM rm_quality_issues").fetchone()[0]
    check("limitations_persisted", issue_count>0, issue_count=issue_count)
    report=dict(status="PASS_WITH_DOCUMENTED_LIMITATIONS" if all(c["passed"] for c in checks) else "FAIL",
                passed=sum(c["passed"] for c in checks), total=len(checks), checks=checks,
                counts=dict(stations=len(stations),source_station_lines=source_count,nodes=len(nodes),directed_edges=len(edge_rows),reference_edges=len(path)),
                reference_center_length_m=meta["reference_center_length_m"],
                sqlite_sha256=hashlib.sha256(dbpath.read_bytes()).hexdigest())
    db.close()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("db",type=Path)
    p.add_argument("--report",type=Path)
    args=p.parse_args()
    result=validate(args.db)
    report=args.report or args.db.parent/"validation.json"
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="checks"},ensure_ascii=False,indent=2))
    sys.exit(0 if result["status"]!="FAIL" else 1)


if __name__=="__main__":
    main()
