"""Inspect official attributes and exact-vertex topology before selecting a path."""
import collections
import json
from pathlib import Path
import zipfile
from pyproj import Geod

ROOT = Path(__file__).resolve().parents[1]
GEOD = Geod(ellps="GRS80")
CONFIG = json.loads((ROOT / "config/corridor.json").read_text(encoding="utf-8"))


def load():
    manifest = json.loads((ROOT / "data/raw/manifest.json").read_text(encoding="utf-8"))
    z = zipfile.ZipFile(ROOT / "data/raw" / manifest["archive"])
    out = {}
    for layer in ("RailroadSection", "Station"):
        name = next(n for n in z.namelist() if n.endswith(f"_{layer}.geojson"))
        data = json.loads(z.read(name))
        out[layer] = data
        for i, f in enumerate(data["features"]):
            f["source_id"] = f"{layer}:{i:05d}"
            f["source_member"] = name
    return out


def selected(f):
    p = f["properties"]
    return (p.get("N02_004") == CONFIG["source_operator"] and p.get("N02_003") == CONFIG["source_line"]
            and p.get("N02_001") == CONFIG["source_railway_type"] and p.get("N02_002") == CONFIG["source_provider_type"])


def parts(f):
    g = f["geometry"]
    if g["type"] == "LineString":
        return [g["coordinates"]]
    if g["type"] == "MultiLineString":
        return g["coordinates"]
    raise ValueError(g["type"])


def graph_stats(fs):
    adj = collections.defaultdict(set)
    segments = set()
    duplicate = 0
    for f in fs:
        for line in parts(f):
            for x, y in zip(line, line[1:]):
                a, b = tuple(x), tuple(y)
                key = tuple(sorted((a, b)))
                if key in segments:
                    duplicate += 1
                segments.add(key)
                adj[a].add(b)
                adj[b].add(a)
    remain = set(adj)
    components = []
    while remain:
        stack = [min(remain)]
        visited = set(stack)
        while stack:
            for b in adj[stack.pop()]:
                if b not in visited:
                    visited.add(b)
                    stack.append(b)
        remain -= visited
        components.append(visited)
    return {
        "nodes": len(adj), "segments": len(segments), "duplicate_segments": duplicate,
        "components": [{"nodes": len(c), "bbox": [min(p[0] for p in c), min(p[1] for p in c),
                        max(p[0] for p in c), max(p[1] for p in c)]}
                       for c in sorted(components, key=len, reverse=True)],
        "degree_counts": dict(collections.Counter(len(a) for a in adj.values())),
        "branch_vertices": [{"lon": a[0], "lat": a[1], "degree": len(bs)}
                            for a, bs in sorted(adj.items()) if len(bs) > 2],
    }


def main():
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    layers = load()
    report = {}
    for layer, data in layers.items():
        fs = data["features"]
        exact = [f for f in fs if selected(f)]
        report[layer] = {
            "total": len(fs), "crs": data.get("crs"), "selected_count": len(exact),
            "operator_values": dict(collections.Counter(f["properties"].get("N02_004") for f in fs
                                                       if f["properties"].get("N02_003") in ("鹿児島線", "鹿児島本線"))),
            "jrkyushu_routes": dict(collections.Counter(f["properties"].get("N02_003") for f in fs
                                                     if f["properties"].get("N02_004") == "九州旅客鉄道")),
            "geometry_types": dict(collections.Counter((f.get("geometry") or {}).get("type") for f in exact)),
        }
    rs = [f for f in layers["RailroadSection"]["features"] if selected(f)]
    st = [f for f in layers["Station"]["features"] if selected(f)]
    report["sections_only"] = graph_stats(rs)
    report["sections_and_stations"] = graph_stats(rs + st)
    report["station_attributes"] = [dict(source_id=f["source_id"], **f["properties"]) for f in st]
    (out / "source_inspection.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "station_attributes"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
