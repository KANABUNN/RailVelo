import copy
import json
import math
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from railvelo.network import Network, distance
from railvelo.matcher import Matcher


class GeometryAndTopology(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / "fixtures" / "synthetic_network.json").read_text(encoding="utf-8"))
        self.network = Network(self.document)

    def test_parallel_and_geometric_crossing_are_not_graph_connections(self):
        self.assertEqual(self.network.shortest("m2", "p2"), math.inf)
        self.assertTrue(math.isfinite(self.network.shortest("m2", "b2")))

    def test_geometry_distances_follow_track_shape(self):
        edge = self.network.edges["b0"]
        # The branched route bends around the main route; its path is longer.
        path = sum(self.network.edges[f"b{i}"]["length_m"] for i in range(4))
        start, end = edge["coordinates"][0], self.network.edges["b3"]["coordinates"][-1]
        self.assertGreater(path - distance(start, end), 60)
        halfway = self.network.interpolate("b0", edge["length_m"] / 2)
        projection = self.network.project(edge, halfway)
        self.assertAlmostEqual(projection["offset_m"], edge["length_m"] / 2, delta=.01)

    def test_source_point_measures_and_reverse_route_orientation(self):
        # Retain the source's arc measure instead of recomputing a potentially
        # different geodetic length in each consumer language.
        document = copy.deepcopy(self.document)
        edge = next(e for e in document["edges"] if e["id"] == "p0")
        edge["point_measures_m"] = [0, edge["length_m"] * .4, edge["length_m"]]
        document["route_edges"] = [e for e in document["route_edges"] if e["route_id"] != "parallel"]
        measure = 0
        for sequence, edge_id in enumerate([f"p{i}" for i in reversed(range(6))]):
            document["route_edges"].append(dict(route_id="parallel", edge_id=edge_id, sequence=sequence, direction=-1, start_m=measure))
            measure += next(e["length_m"] for e in document["edges"] if e["id"] == edge_id)
        network = Network(document)
        projection = network.project(network.edges["p0"], edge["coordinates"][1])
        self.assertAlmostEqual(projection["offset_m"], edge["length_m"] * .4, delta=.001)
        measure, direction = network.route_location(dict(edge_id="p0", route_id="parallel", offset_m=projection["offset_m"], direction=-1))
        self.assertEqual(direction, 1)
        self.assertAlmostEqual(measure, sum(network.edges[f"p{i}"]["length_m"] for i in range(1, 6)) + edge["length_m"] * .6, delta=.001)

    def test_invalid_topology_and_point_measures_fail_before_matching(self):
        cases = []
        missing = copy.deepcopy(self.document)
        missing["edges"][0]["from_node"] = "does_not_exist"
        cases.append(missing)
        discontinuous = copy.deepcopy(self.document)
        next(e for e in discontinuous["route_edges"] if e["route_id"] == "main" and e["sequence"] == 2)["direction"] = -1
        cases.append(discontinuous)
        malformed = copy.deepcopy(self.document)
        malformed["edges"][0]["point_measures_m"] = [0, -10, malformed["edges"][0]["length_m"]]
        cases.append(malformed)
        repeated = copy.deepcopy(self.document)
        repeated["edges"].append(copy.deepcopy(repeated["edges"][0]))
        cases.append(repeated)
        for document in cases:
            with self.subTest(case=cases.index(document)), self.assertRaises(ValueError):
                Network(document)


@unittest.skipUnless((ROOT / "data" / "railway.sqlite").exists(), "N02 database has not been built")
class RealDatabase(unittest.TestCase):
    def test_sqlite_integrity_foreign_keys_and_json_equivalence(self):
        path = ROOT / "data" / "railway.sqlite"
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        left, right = Network.from_sqlite(path), Network.from_json(ROOT / "data" / "network.json")
        self.assertEqual(set(left.nodes), set(right.nodes))
        self.assertEqual(set(left.edges), set(right.edges))
        self.assertEqual(left.route_edges, right.route_edges)
        # JSON may include source-quality annotations beyond the interchange
        # fields stored in SQLite; compare every inference field explicitly.
        station_fields = ("route_id", "station_id", "sequence", "measure_m", "radius_m")
        canonical = lambda network: {route: [{key: row[key] for key in station_fields} for row in station_rows] for route, station_rows in network.route_stations.items()}
        self.assertEqual(canonical(left), canonical(right))
        for edge_id in left.edges:
            for key in ("coordinates", "length_m", "route_ids", "from_node", "to_node", "measures"):
                self.assertEqual(left.edges[edge_id][key], right.edges[edge_id][key])
        if (ROOT / "fixtures" / "corridor_full.jsonl").exists():
            a, b = Matcher(left), Matcher(right)
            for line in (ROOT / "fixtures" / "corridor_full.jsonl").read_text(encoding="utf-8").splitlines():
                observation = json.loads(line)
                self.assertEqual(a.update(observation), b.update(observation))


if __name__ == "__main__":
    unittest.main()
