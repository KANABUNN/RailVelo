"""Graph, local metric geometry and independent read-only storage adapter.

Network lengths remain those of the source database. Projection is local to each
polyline segment; its fraction is mapped to source cumulative arc lengths.
"""
import heapq
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from functools import lru_cache
from pathlib import Path

EARTH_RADIUS = 6371008.8


def distance(a, b):
    p, q = math.radians(a[0]), math.radians(b[0])
    dp, dl = q - p, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS * math.asin(min(1, math.sqrt(max(0, h))))


def bearing(a, b):
    p, q = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(q),
        math.cos(p) * math.sin(q) - math.sin(p) * math.cos(q) * math.cos(dl))) % 360


def angle(a, b):
    return abs((a - b + 180) % 360 - 180)


class Network:
    def __init__(self, document):
        if document.get("schema_version") != 1:
            raise ValueError("unsupported network schema")
        self.document = document
        self.nodes = {x["id"]: x for x in document["nodes"]}
        self.edges = {x["id"]: dict(x) for x in document["edges"]}
        self.routes = {x["id"]: x for x in document["routes"]}
        self.stations = {x["id"]: x for x in document["stations"]}
        for name, table in (("nodes", self.nodes), ("edges", self.edges),
                            ("routes", self.routes), ("stations", self.stations)):
            if len(table) != len(document[name]):
                raise ValueError("duplicate " + name)
            if any(not key for key in table):
                raise ValueError("empty " + name + " ID")
        if not self.edges:
            raise ValueError("empty graph")
        if any(not all(math.isfinite(n[k]) for k in ("lat", "lon")) or abs(n["lat"]) > 90 or abs(n["lon"]) > 180 for n in self.nodes.values()):
            raise ValueError("invalid node coordinates")
        self.adjacency = defaultdict(list)
        self.grid = defaultdict(set)
        for e in self.edges.values():
            coords = e["coordinates"]
            if e["from_node"] not in self.nodes or e["to_node"] not in self.nodes:
                raise ValueError("edge references missing node")
            if not math.isfinite(e["length_m"]) or e["length_m"] <= 0 or len(coords) < 2:
                raise ValueError("invalid edge length or geometry")
            if not e["route_ids"] or any(r not in self.routes for r in e["route_ids"]):
                raise ValueError("invalid edge route")
            if any(len(p) != 2 or not all(math.isfinite(v) for v in p)
                   or abs(p[0]) > 90 or abs(p[1]) > 180 for p in coords):
                raise ValueError("invalid coordinates")
            for field, p in (("from_node", coords[0]), ("to_node", coords[-1])):
                n = self.nodes[e[field]]
                if distance(p, (n["lat"], n["lon"])) > 1:
                    raise ValueError("edge/node endpoint mismatch")
            lengths = [distance(a, b) for a, b in zip(coords, coords[1:])]
            total = sum(lengths)
            if total <= 0:
                raise ValueError("zero geometry length")
            measures = e.get("point_measures_m")
            if measures is None:
                measures = [0.0]
                for length in lengths:
                    measures.append(measures[-1] + length / total * e["length_m"])
            if (len(measures) != len(coords) or abs(measures[0]) > 0.01
                    or abs(measures[-1] - e["length_m"]) > 0.05
                    or any(not math.isfinite(m) for m in measures)
                    or any(b < a for a, b in zip(measures, measures[1:]))):
                raise ValueError("invalid point measures")
            e["measures"] = measures
            self.adjacency[e["from_node"]].append((e["to_node"], e["length_m"], e["id"]))
            self.adjacency[e["to_node"]].append((e["from_node"], e["length_m"], e["id"]))
            # Per-segment geographic bins; no fixed nationwide plane projection.
            for a, b in zip(coords, coords[1:]):
                for i in range(math.floor(min(a[0], b[0]) * 100), math.floor(max(a[0], b[0]) * 100) + 1):
                    for j in range(math.floor(min(a[1], b[1]) * 100), math.floor(max(a[1], b[1]) * 100) + 1):
                        self.grid[i, j].add(e["id"])
        self.route_edges = {}
        by_route = defaultdict(list)
        for x in document["route_edges"]:
            if x["route_id"] not in self.routes or x["edge_id"] not in self.edges or x["direction"] not in (-1, 1) or not math.isfinite(x["start_m"]):
                raise ValueError("invalid route edge")
            if x["route_id"] not in self.edges[x["edge_id"]]["route_ids"]:
                raise ValueError("route path edge membership mismatch")
            key = x["route_id"], x["edge_id"]
            if key in self.route_edges:
                raise ValueError("repeated edge in route requires path occurrence IDs")
            self.route_edges[key] = x
            by_route[x["route_id"]].append(x)
        for path in by_route.values():
            path.sort(key=lambda x: x["sequence"])
            if abs(path[0]["start_m"]) > 0.1 or [p["sequence"] for p in path] != list(range(len(path))):
                raise ValueError("route origin or sequence mismatch")
            for a, b in zip(path, path[1:]):
                ea, eb = self.edges[a["edge_id"]], self.edges[b["edge_id"]]
                end = ea["to_node"] if a["direction"] == 1 else ea["from_node"]
                start = eb["from_node"] if b["direction"] == 1 else eb["to_node"]
                if end != start or abs(a["start_m"] + ea["length_m"] - b["start_m"]) > 0.1:
                    raise ValueError("discontinuous route path")
        self.route_stations = defaultdict(list)
        for s in document["route_stations"]:
            if s["route_id"] not in self.routes or s["station_id"] not in self.stations:
                raise ValueError("station references missing route or station")
            if not math.isfinite(s["measure_m"]) or not 0 < s["radius_m"] <= 1000:
                raise ValueError("invalid station measure or radius")
            self.route_stations[s["route_id"]].append(s)
        for ss in self.route_stations.values():
            ss.sort(key=lambda x: x["sequence"])
            path = by_route.get(ss[0]["route_id"])
            if not path:
                raise ValueError("station route has no path")
            end = path[-1]["start_m"] + self.edges[path[-1]["edge_id"]]["length_m"]
            if ([s["sequence"] for s in ss] != list(range(len(ss)))
                    or any(s["measure_m"] < 0 or s["measure_m"] > end + 0.1 for s in ss)):
                raise ValueError("station measure outside route or invalid sequence")
            if any(b["measure_m"] <= a["measure_m"] or b["sequence"] <= a["sequence"] for a, b in zip(ss, ss[1:])):
                raise ValueError("station order not strictly monotonic")

    @classmethod
    def from_json(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_sqlite(cls, path):
        # URI read-only prevents accidental creation of an empty database.
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as c:
            c.row_factory = sqlite3.Row
            version = c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if version is None or version[0] != "1":
                raise ValueError("unsupported SQLite schema")
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
            if c.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("SQLite foreign key check failed")
            doc = {"schema_version": 1}
            for name in ("nodes", "edges", "routes", "route_edges", "stations", "route_stations"):
                doc[name] = [dict(r) for r in c.execute("SELECT * FROM " + name)]
            for e in doc["edges"]:
                e["coordinates"] = json.loads(e.pop("coordinates_json"))
                e["route_ids"] = json.loads(e.pop("route_ids_json"))
                if "point_measures_json" in e:
                    e["point_measures_m"] = json.loads(e.pop("point_measures_json"))
            return cls(doc)

    def project(self, edge, point):
        best = None
        for i, (a, b) in enumerate(zip(edge["coordinates"], edge["coordinates"][1:])):
            scale = math.cos(math.radians(point[0]))
            x, y = (b[1] - a[1]) * scale, b[0] - a[0]
            px, py = (point[1] - a[1]) * scale, point[0] - a[0]
            t = max(0, min(1, (px * x + py * y) / (x * x + y * y))) if x * x + y * y else 0
            p = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
            d = distance(point, p)
            if best is None or d < best["cross_m"]:
                best = {"edge_id": edge["id"], "offset_m": edge["measures"][i] + t * (edge["measures"][i + 1] - edge["measures"][i]),
                        "lat": p[0], "lon": p[1], "cross_m": d, "bearing": bearing(a, b)}
        return best

    def candidates(self, point, radius):
        lat_delta = radius / 110000
        lon_delta = lat_delta / max(0.01, math.cos(math.radians(point[0])))
        ids = set()
        for i in range(math.floor((point[0] - lat_delta) * 100), math.floor((point[0] + lat_delta) * 100) + 1):
            for j in range(math.floor((point[1] - lon_delta) * 100), math.floor((point[1] + lon_delta) * 100) + 1):
                ids.update(self.grid.get((i, j), ()))
        rows = [self.project(self.edges[eid], point) for eid in sorted(ids)]
        return sorted((r for r in rows if r["cross_m"] <= radius), key=lambda r: (r["cross_m"], r["edge_id"]))[:12]

    @lru_cache(maxsize=4096)
    def shortest(self, start, end):
        queue, seen = [(0.0, start)], {}
        while queue:
            d, n = heapq.heappop(queue)
            if n in seen:
                continue
            if n == end:
                return d
            seen[n] = d
            for nxt, length, _ in self.adjacency[n]:
                if nxt not in seen:
                    heapq.heappush(queue, (d + length, nxt))
        return math.inf

    def interpolate(self, edge_id, offset):
        e = self.edges[edge_id]
        offset = max(0, min(e["length_m"], offset))
        for i, (a, b) in enumerate(zip(e["measures"], e["measures"][1:])):
            if offset <= b:
                t = (offset - a) / (b - a) if b > a else 0
                p, q = e["coordinates"][i:i + 2]
                return [p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]
        return e["coordinates"][-1]

    def route_location(self, state):
        r = self.route_edges.get((state["route_id"], state["edge_id"]))
        if r is None:
            return None
        offset = state["offset_m"] if r["direction"] == 1 else self.edges[state["edge_id"]]["length_m"] - state["offset_m"]
        return r["start_m"] + offset, state["direction"] * r["direction"]
