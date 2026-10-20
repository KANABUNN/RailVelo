"""Exact-source-vertex graph. No crossing noding, rounding, snapping, gap filling."""
from collections import defaultdict
import heapq
from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point
from shapely.ops import transform
from inspect_source import parts

GEOD = Geod(ellps="GRS80")
TO_METRIC = Transformer.from_crs(6668, 6670, always_xy=True)
TO_SOURCE = Transformer.from_crs(6670, 6668, always_xy=True)


def metric(geom):
    return transform(TO_METRIC.transform, geom)


def length(a, b):
    return GEOD.inv(*a, *b)[2]


def cumulative(coords):
    out = [0.0]
    for a, b in zip(coords, coords[1:]):
        out.append(out[-1] + length(a, b))
    return out


def graph(features):
    adj = defaultdict(dict)
    provenance = defaultdict(set)
    for f in features:
        for line in parts(f):
            for x, y in zip(line, line[1:]):
                a, b = tuple(x), tuple(y)
                if a == b:
                    raise ValueError(f"Zero-length source segment {f['source_id']}")
                adj[a][b] = adj[b][a] = length(a, b)
                provenance[tuple(sorted((a, b)))].add(f["source_id"])
    return adj, provenance


def shortest(adj, start, end, banned=frozenset()):
    queue = [(0.0, start)]
    dist, prev = {start: 0.0}, {}
    while queue:
        cost, a = heapq.heappop(queue)
        if cost != dist[a]:
            continue
        if a == end:
            path = [a]
            while path[-1] != start:
                path.append(prev[path[-1]])
            return cost, list(reversed(path))
        for b, d in sorted(adj[a].items()):
            if tuple(sorted((a, b))) in banned:
                continue
            new = cost + d
            if new < dist.get(b, float("inf")):
                dist[b], prev[b] = new, a
                heapq.heappush(queue, (new, b))
    raise ValueError("No source-connected path; no synthetic connection will be created")


def station_midpoint(f):
    cs = parts(f)
    if len(cs) != 1:
        raise ValueError("Multipart station needs explicit review")
    coords = [tuple(c) for c in cs[0]]
    sums = cumulative(coords)
    target = sums[-1] / 2
    for i in range(len(coords) - 1):
        if sums[i + 1] >= target:
            ratio = (target - sums[i]) / (sums[i + 1] - sums[i])
            a, b = coords[i:i + 2]
            return (a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1]))
    raise ValueError("Empty station")


def add_source_midpoint(adj, prov, station):
    p = station_midpoint(station)
    line = [tuple(c) for c in parts(station)[0]]
    for a, b in zip(line, line[1:]):
        # The interpolated point belongs to exactly this original source segment.
        # Midpoint interpolation was performed in source coordinate space. A
        # projected straight segment is not exactly the transformed source line.
        if LineString([a, b]).distance(Point(p)) < 1e-10:
            if b not in adj[a]:
                raise ValueError(f"Station segment absent from railroad graph: {station['source_id']}")
            if p == a or p == b:
                return p
            ids = prov.pop(tuple(sorted((a, b))))
            del adj[a][b]
            del adj[b][a]
            for c in (a, b):
                adj[c][p] = adj[p][c] = length(c, p)
                prov[tuple(sorted((c, p)))].update(ids)
            return p
    raise ValueError(f"Station midpoint cannot be inserted: {station['source_id']}")


def project_on_path(coords, point):
    """Locate in metric CRS; accumulate GRS80 distances, not projected degrees."""
    mp = metric(Point(point))
    sums = cumulative(coords)
    best = None
    for i, (a, b) in enumerate(zip(coords, coords[1:])):
        segment = metric(LineString([a, b]))
        t = segment.project(mp) / segment.length
        q = segment.interpolate(t, normalized=True)
        d = q.distance(mp)
        lon, lat = TO_SOURCE.transform(q.x, q.y)
        item = (d, sums[i] + length(a, (lon, lat)), i, (lon, lat))
        if best is None or item[:2] < best[:2]:
            best = item
    return best
