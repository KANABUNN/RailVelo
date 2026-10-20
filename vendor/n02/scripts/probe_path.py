import json
from shapely.geometry import LineString, Point
from inspect_source import load, selected
from topology import graph, shortest, add_source_midpoint, station_midpoint, project_on_path, metric

layers = load()
rs = [f for f in layers['RailroadSection']['features'] if selected(f)]
st = [f for f in layers['Station']['features'] if selected(f)]
adj, prov = graph(rs)
ends = [next(f for f in st if f['properties']['N02_005'] == name) for name in ['門司港','博多']]
start, end = [add_source_midpoint(adj, prov, f) for f in ends]
d, path = shortest(adj, start, end)
print('Shortest GRS80 metres',d,'vertices',len(path),'branches',sum(len(adj[a])>2 for a in path))
route = metric(LineString(path))
found=[]
for f in st:
    mid = station_midpoint(f)
    m = metric(Point(mid))
    if route.distance(m) < 200:
        found.append((route.project(m),f,mid))
for _, f, mid in sorted(found):
    dist, s, _, _ = project_on_path(path,mid)
    print(f['source_id'],f['properties']['N02_005'],round(s,3),round(dist,3))
print('branches')
for a in path:
    if len(adj[a])>2:
        print(a,len(adj[a]), [sorted(prov[tuple(sorted((a,b)))]) for b in adj[a]])
