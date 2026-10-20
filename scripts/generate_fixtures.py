"""Reproducible synthetic GPS replays; sensor data and hidden truth are separate.

No generated replay represents a real train journey. Uses only Python stdlib.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EARTH_M = 6_371_008.8
BASE_TIME = 1_792_440_000.0


def distance(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dy, dx = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dy / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dx / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def xy_point(x, y):
    # This coordinate origin is synthetic test data, not an inference constant.
    return [33.0 + math.degrees(y / EARTH_M), 130.0 + math.degrees(x / (EARTH_M * math.cos(math.radians(33.0))))]


def length(points):
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def synthetic_network():
    nodes, edges = [], []
    for prefix, y in (("m", 0), ("p", 60)):
        for i in range(7):
            lat, lon = xy_point(i * 1000, y)
            nodes.append(dict(id=f"{prefix}{i}", lat=lat, lon=lon))
        for i in range(6):
            coords = [xy_point(i * 1000, y), xy_point(i * 1000 + 500, y + 12), xy_point((i + 1) * 1000, y)]
            route_ids = ["main"] if prefix == "m" else ["parallel"]
            if prefix == "m" and i < 2:
                route_ids.append("branch")
            edges.append(dict(id=f"{prefix}{i}", from_node=f"{prefix}{i}", to_node=f"{prefix}{i + 1}", route_ids=route_ids, coordinates=coords, length_m=length(coords)))
    branch_points = [xy_point(2000, 0), xy_point(3000, 300), xy_point(4000, 350), xy_point(5000, 250), xy_point(6000, 0)]
    for i, point in enumerate(branch_points[1:-1], 1):
        nodes.append(dict(id=f"b{i}", lat=point[0], lon=point[1]))
    branch_nodes = ["m2", "b1", "b2", "b3", "m6"]
    for i in range(4):
        coords = branch_points[i:i + 2]
        edges.append(dict(id=f"b{i}", from_node=branch_nodes[i], to_node=branch_nodes[i + 1], route_ids=["branch"], coordinates=coords, length_m=length(coords)))
    route_edges, route_stations, stations = [], [], []
    for route, edge_ids in (("main", [f"m{i}" for i in range(6)]), ("parallel", [f"p{i}" for i in range(6)]), ("branch", ["m0", "m1"] + [f"b{i}" for i in range(4)])):
        measure = 0.0
        for sequence, edge_id in enumerate(edge_ids):
            route_edges.append(dict(route_id=route, edge_id=edge_id, sequence=sequence, direction=1, start_m=measure))
            measure += next(e["length_m"] for e in edges if e["id"] == edge_id)
        for sequence, station_measure in enumerate((0.0, 1000.288, 3000.864, 5001.440, measure)):
            station_id = f"{route}_s{sequence}"
            stations.append(dict(id=station_id, name=f"Synthetic {route} station {sequence}"))
            route_stations.append(dict(route_id=route, station_id=station_id, sequence=sequence, measure_m=min(station_measure, measure), radius_m=80.0))
    return dict(schema_version=1, nodes=nodes, edges=edges, routes=[dict(id=r, name=f"Synthetic {r}", forward_label="forward", reverse_label="reverse") for r in ("main", "branch", "parallel")], route_edges=route_edges, stations=stations, route_stations=route_stations)


class RouteGeometry:
    def __init__(self, document, route_id):
        self.route_id = route_id
        edge_map = {edge["id"]: edge for edge in document["edges"]}
        self.segments = []
        measure = 0.0
        for membership in sorted((r for r in document["route_edges"] if r["route_id"] == route_id), key=lambda r: r["sequence"]):
            edge = edge_map[membership["edge_id"]]
            coords = edge["coordinates"] if membership["direction"] == 1 else list(reversed(edge["coordinates"]))
            source_measures = edge.get("point_measures_m")
            if source_measures is None:
                segment_lengths = [distance(a, b) for a, b in zip(coords, coords[1:])]
                scale = edge["length_m"] / sum(segment_lengths)
                segment_lengths = [x * scale for x in segment_lengths]
            else:
                segment_lengths = [b - a for a, b in zip(source_measures, source_measures[1:])]
                if membership["direction"] == -1:
                    segment_lengths.reverse()
            edge_offset = 0.0
            measure = membership["start_m"]
            for a, b, segment_length in zip(coords, coords[1:], segment_lengths):
                self.segments.append((measure, measure + segment_length, a, b, edge["id"], edge_offset, membership["direction"], edge["length_m"]))
                measure += segment_length
                edge_offset += segment_length
        self.length_m = measure

    def point(self, measure):
        measure = max(0.0, min(self.length_m, measure))
        segment = next((s for s in self.segments if measure <= s[1]), self.segments[-1])
        start, end, a, b, edge_id, offset, direction, edge_length = segment
        f = (measure - start) / max(1e-9, end - start)
        coord = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
        bearing = math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0])) % 360
        route_offset = offset + measure - start
        return coord, bearing, edge_id, route_offset if direction == 1 else edge_length - route_offset


def make_replay(geometry, measures, *, seed=42, dt=2.0, noise_m=3.0, accuracy_m=8.0, direction=1):
    rng = random.Random(seed)
    observations, truths = [], []
    prior = None
    for i, measure in enumerate(measures):
        coord, bearing, edge_id, offset = geometry.point(measure)
        actual_speed = abs(measure - prior) / dt if prior is not None else 20.0
        prior = measure
        north, east = rng.gauss(0, noise_m), rng.gauss(0, noise_m)
        lat = coord[0] + math.degrees(north / EARTH_M)
        lon = coord[1] + math.degrees(east / (EARTH_M * math.cos(math.radians(coord[0]))))
        timestamp = BASE_TIME + i * dt
        observations.append(dict(timestamp=timestamp, lat=lat, lon=lon, horizontal_accuracy_m=accuracy_m, speed_mps=actual_speed, speed_accuracy_mps=0.7, course_deg=(bearing + (180 if direction < 0 else 0)) % 360 if actual_speed > 1 else rng.uniform(0, 360)))
        truths.append(dict(timestamp=timestamp, route_id=geometry.route_id, direction=direction, measure_m=measure, edge_id=edge_id, offset_m=offset, lat=coord[0], lon=coord[1], sensor_valid=True))
    return observations, truths


def sequence(start, end, step=40):
    count = max(1, int(math.ceil(abs(end - start) / abs(step))))
    return [start + (end - start) * i / count for i in range(count + 1)]


def scenarios(document):
    main, branch, parallel = (RouteGeometry(document, r) for r in ("main", "branch", "parallel"))
    result = {}
    normal = sequence(2200, 4700)
    result["normal"] = make_replay(main, normal)
    result["reverse"] = make_replay(main, list(reversed(normal)), direction=-1)
    result["station_stop_depart"] = make_replay(main, sequence(2300, 3000.864) + [3000.864] * 18 + sequence(3000.864, 3800)[1:])
    result["station_pass"] = make_replay(main, sequence(2300, 3800))
    result["between_station_stop"] = make_replay(main, sequence(3300, 4000) + [4000] * 45 + sequence(4000, 4700)[1:])
    result["branch_merge"] = make_replay(branch, sequence(1600, branch.length_m - 30))
    result["parallel"] = make_replay(parallel, sequence(2300, 4700))
    result["endpoint"] = make_replay(main, sequence(5300, main.length_m) + [main.length_m] * 4)
    for name in ("position_jump", "speed_spike", "poor_accuracy", "signal_loss", "long_signal_loss", "tunnel_reentry"):
        observations, truths = make_replay(main, normal)
        if name == "position_jump":
            observations[20]["lat"] += 0.08
            truths[20]["sensor_valid"] = False
        elif name == "speed_spike":
            observations[20]["speed_mps"] = 500.0
            observations[20]["speed_accuracy_mps"] = 0.1
        elif name == "poor_accuracy":
            for i in range(20, 30):
                observations[i]["horizontal_accuracy_m"] = 700.0
                observations[i]["lat"] += 0.001
                truths[i]["sensor_valid"] = False
        else:
            gap = range(15, 20) if name == "signal_loss" else range(10, 40)
            for i in gap:
                observations[i]["lat"] = observations[i]["lon"] = None
                truths[i]["sensor_valid"] = False
            if name == "tunnel_reentry":
                observations[40]["lat"] += 0.004
                observations[40]["horizontal_accuracy_m"] = 100
                truths[40]["sensor_valid"] = False
        result[name] = observations, truths
    # The middle of two disconnected parallel lines is intentionally unresolved.
    ambiguous, truth = make_replay(main, [3600] * 12, noise_m=0, accuracy_m=80)
    for observation in ambiguous:
        observation["lat"] += math.degrees(30 / EARTH_M)
        observation["speed_mps"] = 0
        observation["course_deg"] = 270
    result["ambiguous_stationary"] = ambiguous, truth
    return result


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def generate(output=ROOT / "fixtures", real_network=ROOT / "data" / "network.json"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    document = synthetic_network()
    (output / "synthetic_network.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = dict(schema_version=1, kind="synthetic_only", seed=42, generator="scripts/generate_fixtures.py", scenarios=[])
    for name, (observations, truths) in scenarios(document).items():
        write_jsonl(output / f"{name}.jsonl", observations)
        write_jsonl(output / f"{name}.truth.jsonl", truths)
        manifest["scenarios"].append(dict(name=name, network="synthetic_network.json", observations=f"{name}.jsonl", truth=f"{name}.truth.jsonl", count=len(observations)))
    if Path(real_network).exists():
        real = json.loads(Path(real_network).read_text(encoding="utf-8"))
        # First route is not necessarily the corridor: use the longest ordered
        # route with at least two station markers, without embedding its name.
        station_counts = {r["id"]: sum(s["route_id"] == r["id"] for s in real["route_stations"]) for r in real["routes"]}
        eligible_routes = [r["id"] for r in real["routes"] if station_counts[r["id"]] >= 2]
        if not eligible_routes:
            raise ValueError("Real network has no station-bearing ordered route")
        route_id = max(eligible_routes, key=lambda r: RouteGeometry(real, r).length_m)
        geometry = RouteGeometry(real, route_id)
        # Sparse full-corridor coverage, realistic 20 m/s average and ~250 fixes.
        measures = sequence(30, geometry.length_m - 30, 500)
        observations, truths = make_replay(geometry, measures, dt=25, noise_m=6, accuracy_m=12)
        write_jsonl(output / "corridor_full.jsonl", observations)
        write_jsonl(output / "corridor_full.truth.jsonl", truths)
        manifest["scenarios"].append(dict(name="corridor_full", network="../data/network.json", observations="corridor_full.jsonl", truth="corridor_full.truth.jsonl", count=len(observations)))
        observations, truths = make_replay(geometry, list(reversed(measures)), dt=25, noise_m=6, accuracy_m=12, direction=-1)
        write_jsonl(output / "corridor_reverse.jsonl", observations)
        write_jsonl(output / "corridor_reverse.truth.jsonl", truths)
        manifest["scenarios"].append(dict(name="corridor_reverse", network="../data/network.json", observations="corridor_reverse.jsonl", truth="corridor_reverse.truth.jsonl", count=len(observations)))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "fixtures")
    parser.add_argument("--network", type=Path, default=ROOT / "data" / "network.json")
    args = parser.parse_args()
    manifest = generate(args.output, args.network)
    print(json.dumps({"kind": manifest["kind"], "scenarios": len(manifest["scenarios"]), "observations": sum(s["count"] for s in manifest["scenarios"])}, indent=2))
