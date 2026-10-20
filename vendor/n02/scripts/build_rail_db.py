"""Build the Mojiko-Hakata N02 reference DB against the original v0.2 DDL.

This creates a geographic reference, not verified physical turnout topology.
Only source segments are used. Unresolvable track choices remain candidates.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import sqlite3
import sys
import uuid
import zipfile

import pyproj
import shapely
from shapely.geometry import LineString, Point, shape, mapping
from shapely.strtree import STRtree
from pyproj import Transformer

from fetch import sha
from inspect_source import load, parts, selected
from topology import (graph, shortest, add_source_midpoint, station_midpoint,
                      project_on_path, cumulative, length, metric)

ROOT = Path(__file__).resolve().parents[1]
TO_WGS = Transformer.from_crs(6668, 4326, always_xy=True, allow_ballpark=False)
NAMESPACE = uuid.UUID("01a1592c-df45-7b92-8e93-d00e9d89ce0b")


def dumps(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def dump(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def stable_id(kind, name):
    return str(uuid.uuid5(NAMESPACE, f"{kind}/{name}"))


def key(a, b):
    return tuple(sorted((a, b)))


def through_graph(adj, path):
    """Keep all source-connected alternatives; a one-touch spur is not a through path.

    This is a source graph property, not proof of operational connections.
    """
    on = set(path)
    retained = set(on)
    remain = set(adj) - on
    excluded_components = []
    while remain:
        start = min(remain)
        stack, seen, touches = [start], {start}, set()
        while stack:
            for b in adj[stack.pop()]:
                if b in on:
                    touches.add(b)
                elif b not in seen:
                    seen.add(b)
                    stack.append(b)
        remain -= seen
        if len(touches) >= 2:
            retained |= seen
        else:
            excluded_components.append({"nodes": len(seen), "touches": len(touches)})
    return {a: {b: d for b, d in adj[a].items() if b in retained} for a in sorted(retained)}, excluded_components


def compress(adj, prov, path):
    """Stop at source boundaries, branches, and reference terminals."""
    stops = {path[0], path[-1]}
    for a, neighbors in adj.items():
        if len(neighbors) != 2:
            stops.add(a)
        elif len({tuple(sorted(prov[key(a, b)])) for b in neighbors}) > 1:
            stops.add(a)
    # Midpoints are deliberately stops so station representatives have exact nodes.
    stops |= {a for a in adj if any(s.startswith("Station:") for b in adj[a] for s in prov[key(a, b)])}
    used, polylines = set(), []
    for a in sorted(stops):
        for b in sorted(adj[a]):
            if key(a, b) in used:
                continue
            cs = [a, b]
            used.add(key(a, b))
            while cs[-1] not in stops:
                nxt = next(x for x in adj[cs[-1]] if x != cs[-2])
                used.add(key(cs[-1], nxt))
                cs.append(nxt)
            polylines.append(cs)
    expected = {key(a, b) for a in adj for b in adj[a]}
    if used != expected:
        raise ValueError("Compression lost source segments")
    return polylines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "output")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dbpath = out / "rail_jrkyushu.sqlite"
    if dbpath.exists():
        raise FileExistsError("Use a new --out directory; existing DBs are never replaced")
    logs = []

    def log(stage, **values):
        row = dict(stage=stage, **values)
        logs.append(row)
        print(dumps(row), flush=True)
        with (out / "build.jsonl").open("a", encoding="utf-8") as f:
            f.write(dumps(row) + "\n")

    config = json.loads((ROOT / "config/corridor.json").read_text(encoding="utf-8"))
    registry_input = json.loads((ROOT / "config/station_registry.json").read_text(encoding="utf-8"))
    registry_ids = {x["public_name"]: x["id"] for x in registry_input}
    if set(registry_ids) != set(config["stations"]) or len(set(registry_ids.values())) != len(registry_ids):
        raise ValueError("Frozen station registry must cover exactly the configured stations with unique IDs")
    manifest = json.loads((ROOT / "data/raw/manifest.json").read_text(encoding="utf-8"))
    if manifest["selected_year"] != int(config["policy"]["source_reference_date"][:4]):
        raise ValueError("New source release needs an explicit reference date/license/configuration review")
    for name, info in manifest["files"].items():
        if sha(ROOT / "data/raw" / name) != info["sha256"]:
            raise ValueError(f"Input hash mismatch: {name}")
    layers = load()
    rs = [f for f in layers["RailroadSection"]["features"] if selected(f)]
    all_st = [f for f in layers["Station"]["features"] if selected(f)]
    st = [f for f in all_st if f["properties"]["N02_005"] in config["stations"]]
    # Fail rather than silently skip source geometry errors.
    for f in rs + st:
        g = shape(f["geometry"])
        if g.is_empty or not g.is_valid or g.geom_type not in ("LineString", "MultiLineString"):
            raise ValueError(f"Invalid selected source geometry: {f['source_id']}")
    log("source", selected_railroad_features=len(rs), selected_station_features=len(st),
        archive_sha256=manifest["files"][manifest["archive"]]["sha256"])

    adj, prov = graph(rs)
    station_segment_missing = []
    for f in st:
        for line in parts(f):
            for x, y in zip(line, line[1:]):
                a, b = tuple(x), tuple(y)
                if b in adj.get(a, {}):
                    prov[key(a, b)].add(f["source_id"])
                else:
                    station_segment_missing.append(f["source_id"])
    if station_segment_missing:
        raise ValueError(f"Station segments missing from source railroad layer: {station_segment_missing}")
    mids = {f["source_id"]: add_source_midpoint(adj, prov, f) for f in st}
    terminal = [next(f for f in st if f["properties"]["N02_005"] == name)
                for name in (config["stations"][0], config["stations"][-1])]
    startmid, endmid = [mids[f["source_id"]] for f in terminal]
    center_length, center_path = shortest(adj, startmid, endmid)
    start_ends = [tuple(parts(terminal[0])[0][i]) for i in (0, -1)]
    end_ends = [tuple(parts(terminal[1])[0][i]) for i in (0, -1)]
    start = max(start_ends, key=lambda x: shortest(adj, x, endmid)[0])
    end = max(end_ends, key=lambda x: shortest(adj, startmid, x)[0])
    full_length, reference = shortest(adj, start, end)
    if startmid not in reference or endmid not in reference:
        raise ValueError("Reference path did not pass both terminal station midpoints")
    ref_sums = cumulative(reference)
    origin = ref_sums[reference.index(startmid)]
    ref_indices = {p: i for i, p in enumerate(reference)}
    corridor, excluded_components = through_graph(adj, reference)
    polylines = compress(corridor, prov, reference)
    log("topology", reference_center_length_m=center_length, reference_vertices=len(reference),
        undirected_geometries=len(polylines),
        source_only_connectivity=True, synthetic_gap_edges=0)

    issues = []

    def issue(code, severity, ids, **details):
        issues.append(dict(id=f"Q{len(issues)+1:04d}", code=code, severity=severity,
                           related_ids=ids, details=details))

    issue("REFERENCE_NOT_SURVEYED_RUNNING_TRACK", "limitation", [],
          message="N02線形による計算用代表経路。上下線・番線・転轍器・接続可否を保証しない。最短経路は実際の乗車経路の同定ではない。")
    source_features = {f["source_id"]: f for f in rs + st}
    station_info, primary, registry = {}, {}, []
    for sequence, name in enumerate(config["stations"]):
        fs = [f for f in st if f["properties"]["N02_005"] == name]
        if not fs:
            raise ValueError(f"Expected official station absent: {name}")
        station_id = registry_ids[name]
        registry.append({"id": station_id, "public_name": name})
        infos = []
        for f in fs:
            sid = f["source_id"]
            d, chain, _, _ = project_on_path(reference, mids[sid])
            ranges = [project_on_path(reference, tuple(c))[1] - origin
                      for line in parts(f) for c in line]
            info = dict(source_id=sid, station_id=station_id, public_name=name, sequence=sequence,
                        chainage_m=chain-origin, offset_m=d, extent_begin_m=min(ranges),
                        extent_end_m=max(ranges), on_candidate_graph=mids[sid] in corridor)
            infos.append(info)
            station_info[sid] = info
        chosen = min(infos, key=lambda x: (round(x["offset_m"], 2), x["source_id"]))
        if chosen["offset_m"] > 0.01 or not chosen["on_candidate_graph"]:
            raise ValueError(f"No exact reference geometry for station {name}; manual review required")
        primary[name] = chosen
        if len(fs) > 1:
            issue("MULTIPLE_STATION_LINE_FEATURES", "warning", [f["source_id"] for f in fs],
                  station=name, representatives=infos,
                  message="同一駅の複数線形を保存。位置・用途・現行番線との対応はN02だけでは確定できない。")
        for info in infos:
            if not info["on_candidate_graph"]:
                issue("STATION_VARIANT_NOT_ON_THROUGH_GRAPH", "warning", [info["source_id"]],
                      station=name, reference_offset_m=info["offset_m"],
                      message="鹿児島線属性の通り抜け経路に載らない駅線形。代表経路へ接続線を補作しない。")
    ordered = [primary[n]["chainage_m"] for n in config["stations"]]
    if any(b <= a for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Station order contradicts the official JR station order")
    comparisons = []
    for row in config["operating_km_reference"]["segments"]:
        measured = primary[row["to"]]["chainage_m"] - primary[row["from"]]["chainage_m"]
        expected_m = row["operating_km"] * 1000
        comparisons.append(dict(row, n02_reference_m=measured,
                                difference_m=measured-expected_m,
                                difference_percent=(measured/expected_m-1)*100))
    expected_m = sum(x["operating_km"] for x in comparisons) * 1000
    comparisons.append(dict(from_station=config["stations"][0], to_station=config["stations"][-1],
                            operating_km=expected_m/1000, n02_reference_m=center_length,
                            difference_m=center_length-expected_m,
                            difference_percent=(center_length/expected_m-1)*100))
    issue("DIFFERENCE_FROM_OFFICIAL_OPERATING_KM", "warning", [],
          source=config["operating_km_reference"], comparisons=comparisons,
          message="形状弧長と営業キロには差がある。原因・現在の実走距離との誤差は確定できない。値の較正・引伸しは行っていない。")

    # Source-graph junctions are candidates, not verified operational turnouts.
    branch_nodes = [a for a in corridor if len(corridor[a]) > 2]
    for a in branch_nodes:
        source_ids = sorted({s for b in corridor[a] for s in prov[key(a, b)]})
        issue("SOURCE_GRAPH_JUNCTION_UNVERIFIED", "warning", source_ids,
              longitude=a[0], latitude=a[1], degree=len(corridor[a]),
              message="元データで同一頂点を共有する分岐候補。実際の線路接続・立体交差・進入方向は未確認。")

    db = sqlite3.connect(dbpath)
    db.executescript((ROOT / "schemas/railmonitor_v0_2.sql").read_text(encoding="utf-8-sig"))
    db.executescript((ROOT / "schemas/n02_extensions.sql").read_text(encoding="utf-8"))
    release_id = f"mlit.n02.{manifest['selected_year']}.{manifest['files'][manifest['archive']]['sha256'][:12]}"
    built_utc = manifest["files"][manifest["archive"]]["retrieved_utc"]
    attribution = ("国土数値情報（鉄道データ）2025年度版（国土交通省）"
                   " https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html を加工して作成。"
                   "門司港〜博多の抽出・グラフ化・代表経路選択・駅投影・距離計算を実施。国が作成した成果物ではありません。")
    db.execute("INSERT INTO data_releases VALUES (?,?,?,?,?,?,?,?)",
               (release_id, "国土数値情報 N02 鉄道 2025年度版", manifest["files"][manifest["archive"]]["url"],
                config["policy"]["source_reference_date"], built_utc,
                manifest["files"][manifest["archive"]]["sha256"], "CC-BY-4.0", attribution))
    db.execute("INSERT INTO operators VALUES (?,?)", (config["operator_id"], "JR九州"))
    db.execute("INSERT INTO rail_routes VALUES (?,?,?,?)", (config["id"], config["operator_id"], config["public_name"], release_id))
    for name in config["stations"]:
        info = primary[name]
        f = source_features[info["source_id"]]
        lon, lat = TO_WGS.transform(*mids[info["source_id"]])
        db.execute("INSERT INTO stations VALUES (?,?,?,?,?,?)", (info["station_id"], name, lat, lon, release_id, f["properties"]["N02_005c"]))

    needed_ids = {s for a in corridor for b in corridor[a] for s in prov[key(a, b)]} | set(station_info)
    for sid in sorted(needed_ids):
        f = source_features[sid]
        db.execute("INSERT INTO rm_source_features VALUES (?,?,?,?,?,?)",
                   (sid, sid.split(":")[0], f["source_member"], int(sid.split(":")[1]), dumps(f["properties"]), dumps(f["geometry"])))
    for sid, info in sorted(station_info.items()):
        p = source_features[sid]["properties"]
        db.execute("INSERT INTO rm_station_sources VALUES (?,?,?,?,?,?,?,?)",
                   (sid, info["station_id"], p.get("N02_005c"), p.get("N02_005g"), int(info["on_candidate_graph"]),
                    info["offset_m"], info["chainage_m"], int(primary[info["public_name"]]["source_id"] == sid)))
    for name in config["stations"]:
        i = primary[name]
        db.execute("INSERT INTO rm_station_positions VALUES (?,?,?,?,?,?,?)",
                   (i["station_id"], i["sequence"], i["source_id"], i["chainage_m"],
                    i["extent_begin_m"], i["extent_end_m"], "n02_extent_unverified",))

    nodes = sorted({cs[0] for cs in polylines} | {cs[-1] for cs in polylines})
    nodeids = {p: f"n{i:04d}" for i, p in enumerate(nodes)}
    for p in nodes:
        lon, lat = TO_WGS.transform(*p)
        db.execute("INSERT INTO rm_nodes VALUES (?,?,?,?)", (nodeids[p], lon, lat, "exact_source_vertex_or_source_station_midpoint"))
    exports, reference_edges, edge_count = [], [], 0
    reference_segments = {key(a, b) for a, b in zip(reference, reference[1:])}
    for i, cs in enumerate(polylines):
        ks = [key(a, b) for a, b in zip(cs, cs[1:])]
        is_ref = all(k in reference_segments for k in ks)
        if any(k in reference_segments for k in ks) and not is_ref:
            raise ValueError("Compressed edge mixes reference and alternate path")
        if is_ref and ref_indices[cs[0]] > ref_indices[cs[-1]]:
            cs = list(reversed(cs))
        ids = sorted({sid for k in ks for sid in prov[k]})
        roles = "reference" if is_ref else "candidate"
        for rev in (False, True):
            points = list(reversed(cs)) if rev else cs
            progress = cumulative(points)
            eid = f"e{i:04d}.{'r' if rev else 'f'}"
            twin = f"e{i:04d}.{'f' if rev else 'r'}"
            direction = ("up" if rev else "down") if is_ref else "unknown"
            db.execute("INSERT INTO rail_edges VALUES (?,?,?,?,?,?)", (eid, config["id"], nodeids[points[0]], nodeids[points[-1]], progress[-1], release_id))
            ll = [TO_WGS.transform(*p) for p in points]
            db.executemany("INSERT INTO rail_edge_points VALUES (?,?,?,?,?)", [(eid, j, p[1], p[0], progress[j]) for j, p in enumerate(ll)])
            edge_count += 1
            db.execute("INSERT INTO rail_edge_spatial_keys VALUES (?,?)", (edge_count, eid))
            db.execute("INSERT INTO rail_edge_rtree VALUES (?,?,?,?,?)", (edge_count, min(p[0] for p in ll), max(p[0] for p in ll), min(p[1] for p in ll), max(p[1] for p in ll)))
            db.execute("INSERT INTO rm_edge_metadata VALUES (?,?,?,?,?,?)", (eid, twin, roles, direction, dumps(ids), "source_vertex_connectivity_only"))
            station_ids = sorted({station_info[sid]["station_id"] for sid in ids if sid in station_info})
            for station_id in station_ids:
                source_variants = [sid for sid in ids if sid in station_info and station_info[sid]["station_id"] == station_id]
                _, pos, _, _ = min(project_on_path(points, mids[sid]) for sid in source_variants)
                db.execute("INSERT INTO station_track_locations VALUES (?,?,?,?,?,?)", (station_id, eid, min(max(pos, 0), progress[-1]), 0.0, progress[-1], "n02_station_line_extent_unverified"))
            if is_ref and not rev:
                reference_edges.append((ref_indices[cs[0]], eid, ref_sums[ref_indices[cs[0]]]-origin, ref_sums[ref_indices[cs[-1]]]-origin))
        exports.append({"type":"Feature", "properties":{"id":f"e{i:04d}","role":roles,"source_ids":ids},
                        "geometry":mapping(LineString(cs))})
    for seq, (_, eid, begin, finish) in enumerate(sorted(reference_edges)):
        db.execute("INSERT INTO rm_reference_path VALUES (?,?,?,?,?)", (config["id"], seq, eid, begin, finish))

    # Nearby foreign, freight-labelled, and other-route geometry is audited, never
    # admitted by a bounding box or a spatial join alone.
    reference_metric = metric(LineString(reference))
    region = reference_metric.buffer(config["policy"]["nearby_audit_radius_m"])
    nearby, excluded_stats = [], Counter()
    for layer, data in layers.items():
        for f in data["features"]:
            if selected(f):
                continue
            geom = f.get("geometry")
            if not geom:
                continue
            # Cheap lon/lat bounding test before projection; not an inclusion filter.
            bounds = shape(geom).bounds
            rb = LineString(reference).bounds
            if bounds[2] < rb[0]-0.02 or bounds[0] > rb[2]+0.02 or bounds[3] < rb[1]-0.02 or bounds[1] > rb[3]+0.02:
                continue
            gm = metric(shape(geom))
            if gm.intersects(region):
                props = f["properties"]
                distance = gm.distance(reference_metric)
                category = "other_jrkyushu_route" if props.get("N02_004") == "九州旅客鉄道" else "other_operator"
                if "貨物" in props.get("N02_004", ""):
                    category = "freight_label"
                excluded_stats[(layer, category, props.get("N02_004"), props.get("N02_003"))] += 1
                nearby.append({"type":"Feature", "properties":dict(props, source_id=f["source_id"], distance_to_reference_m=distance, exclusion_reason=category), "geometry":geom})
    log("exclusions", nearby_features=len(nearby), counts=[dict(layer=k[0], reason=k[1], operator=k[2], line=k[3], count=v) for k, v in sorted(excluded_stats.items())])

    # Audit source line intersections without introducing graph connections.
    corridor_rs = [source_features[s] for s in sorted(needed_ids) if s.startswith("RailroadSection:")]
    geoms = [shape(f["geometry"]) for f in corridor_rs]
    tree = STRtree(geoms)
    crossing_count = 0
    for i, geom in enumerate(geoms):
        for j0 in tree.query(geom, predicate="intersects"):
            j = int(j0)
            if j <= i:
                continue
            shared = {tuple(c) for p in parts(corridor_rs[i]) for c in p} & {tuple(c) for p in parts(corridor_rs[j]) for c in p}
            intersection = geom.intersection(geoms[j])
            ips = [intersection] if intersection.geom_type == "Point" else list(intersection.geoms) if intersection.geom_type == "MultiPoint" else []
            unconnected = [p for p in ips if tuple(p.coords[0]) not in shared]
            if unconnected:
                crossing_count += 1
                issue("GEOMETRIC_CROSSING_NOT_CONNECTED", "warning", [corridor_rs[i]["source_id"], corridor_rs[j]["source_id"]],
                      locations=[list(p.coords[0]) for p in unconnected], message="幾何交点に共通元頂点なし。グラフ接続は作らない。")

    for row in issues:
        db.execute("INSERT INTO rm_quality_issues VALUES (?,?,?,?,?)", (row["id"], row["severity"], row["code"], dumps(row["related_ids"]), dumps(row["details"])))
    metadata = dict(
        package="railmonitor_n02", config=config, source_archive=manifest["archive"],
        source_archive_sha256=manifest["files"][manifest["archive"]]["sha256"],
        schema_sha256=sha(ROOT / "schemas/railmonitor_v0_2.sql"),
        input_configuration_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p)
                                    for p in [ROOT/"schemas/n02_extensions.sql", ROOT/"config/corridor.json", ROOT/"config/station_registry.json", ROOT/"requirements.lock.txt"]},
        built_utc=built_utc, build_time_policy="Pinned to archive retrieval timestamp for reproducible bytes",
        coordinate_transform=dict(description=TO_WGS.description, accuracy_m=TO_WGS.accuracy, definition=TO_WGS.definition),
        source_crs="EPSG:6668", db_crs="EPSG:4326", metric_projection="EPSG:6670",
        distance_model="GRS80 ellipsoid, sum of source line segments; not operating kilometres",
        reference_center_length_m=center_length, full_reference_length_m=full_length,
        official_operating_km_comparison=comparisons,
        reference_begin_chainage_m=-origin, reference_end_chainage_m=full_length-origin,
        registry_policy="Frozen application IDs generated once; never replace them with N02 codes on update",
        runtime=dict(python=platform.python_version(), sqlite=sqlite3.sqlite_version, shapely=shapely.__version__, geos=shapely.geos_version_string, pyproj=pyproj.__version__, proj=pyproj.proj_version_str),
        code_sha256={p.name:sha(p) for p in sorted((ROOT / "scripts").glob("*.py"))},
    )
    for k, value in metadata.items():
        db.execute("INSERT INTO rm_metadata VALUES (?,?)", (k, dumps(value)))
    db.commit()
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("SQLite integrity/FK check failed")
    db.execute("VACUUM")
    db.close()
    dump(out / "metadata.json", metadata)
    dump(out / "quality_issues.json", issues)
    dump(out / "station_sources.json", list(station_info.values()))
    dump(out / "station_registry.json", registry)
    dump(out / "corridor.geojson", {"type":"FeatureCollection", "crs":layers["RailroadSection"]["crs"], "features":exports})
    dump(out / "station_lines.geojson", {"type":"FeatureCollection", "crs":layers["Station"]["crs"], "features":[{"type":"Feature","properties":dict(f["properties"], source_id=f["source_id"], **{k:v for k,v in station_info[f["source_id"]].items() if k != "source_id"}),"geometry":f["geometry"]} for f in st]})
    dump(out / "nearby_excluded.geojson", {"type":"FeatureCollection", "crs":layers["RailroadSection"]["crs"], "features":nearby})
    selection_counts = Counter()
    with (out / "selection_audit.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source_id","layer","operator","source_line","station_name","station_code","decision"])
        for layer, data in layers.items():
            for feature in data["features"]:
                p = feature["properties"]
                sid = feature["source_id"]
                if p.get("N02_004") != config["source_operator"]:
                    decision = "operator_filter"
                elif p.get("N02_003") != config["source_line"]:
                    decision = "line_filter"
                elif not selected(feature):
                    decision = "railway_type_filter"
                elif layer == "Station" and p.get("N02_005") not in config["stations"]:
                    decision = "outside_target_station_order"
                elif sid not in needed_ids:
                    decision = "outside_source_through_graph"
                elif sid in station_info and not station_info[sid]["on_candidate_graph"]:
                    decision = "preserved_unmapped_station_variant"
                else:
                    decision = "selected_partly_or_fully"
                selection_counts[(layer, decision)] += 1
                writer.writerow([sid,layer,p.get("N02_004"),p.get("N02_003"),p.get("N02_005"),p.get("N02_005c"),decision])
    dump(out / "selection_counts.json", [dict(layer=k[0],decision=k[1],count=v) for k,v in sorted(selection_counts.items())])
    with (out / "stations.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sequence","public_name","station_id","chainage_m","extent_begin_m","extent_end_m","source_id","offset_m"])
        writer.writeheader()
        for name in config["stations"]:
            info = primary[name]
            writer.writerow({k:info[k] for k in writer.fieldnames})
    with (out / "station_distances.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["from","to","n02_reference_distance_m","source","quality"])
        for a, b in zip(config["stations"], config["stations"][1:]):
            writer.writerow([a,b,primary[b]["chainage_m"]-primary[a]["chainage_m"],"N02-25 shortest reference path","not_surveyed_not_operating_km"])
    log("complete", sqlite_sha256=sha(dbpath), stations=len(registry), station_source_features=len(st),
        directed_edges=edge_count, reference_edges=len(reference_edges),
        unconnected_geometric_crossing_pairs=crossing_count, issue_count=len(issues),
        excluded_non_through_components=excluded_components)


if __name__ == "__main__":
    main()
