"""Risk-focused regression cases: crossings, short gaps, and ambiguous paths."""
import unittest
from collections import defaultdict

from build_rail_db import through_graph
from topology import graph, shortest, add_source_midpoint


def feature(sid, coords):
    return {"source_id":sid,"geometry":{"type":"LineString","coordinates":coords}}


class TopologySafetyTests(unittest.TestCase):
    def test_geographic_crossing_does_not_create_connection(self):
        fs=[feature("a",[(130.5,33.8),(130.502,33.802)]),
            feature("b",[(130.5,33.802),(130.502,33.8)])]
        adj,_=graph(fs)
        with self.assertRaisesRegex(ValueError,"No source-connected path"):
            shortest(adj,(130.5,33.8),(130.502,33.8))

    def test_submetre_gap_is_not_silently_snapped(self):
        fs=[feature("a",[(130.5,33.8),(130.501,33.8)]),
            feature("b",[(130.501001,33.8),(130.502,33.8)])]
        adj,_=graph(fs)
        with self.assertRaisesRegex(ValueError,"No source-connected path"):
            shortest(adj,(130.5,33.8),(130.502,33.8))

    def test_alternative_remains_in_candidate_graph(self):
        a,b,c,d,spur=(130.5,33.8),(130.501,33.8),(130.502,33.8),(130.501,33.801),(130.5,33.799)
        adj,_=graph([feature("main",[a,b,c]),feature("alt",[a,d,c]),feature("spur",[a,spur])])
        _,path=shortest(adj,a,c)
        kept,_=through_graph(adj,path)
        self.assertIn(d,kept)
        self.assertNotIn(spur,kept)

    def test_station_geometry_must_exist_in_railroad_layer(self):
        adj,prov=graph([feature("a",[(130.5,33.8),(130.502,33.8)])])
        foreign=feature("station",[(130.5,33.801),(130.502,33.801)])
        with self.assertRaisesRegex(ValueError,"absent from railroad graph"):
            add_source_midpoint(adj,prov,foreign)

    def test_source_station_midpoint_preserves_provenance(self):
        a,b=(130.5,33.8),(130.51,33.801)
        f=feature("rail",[a,b])
        adj,prov=graph([f])
        p=add_source_midpoint(adj,prov,feature("station",[a,b]))
        self.assertNotIn(b,adj[a])
        self.assertIn(p,adj[a])
        self.assertEqual(prov[tuple(sorted((a,p)))],{"rail"})
        self.assertEqual(prov[tuple(sorted((b,p)))],{"rail"})


if __name__=="__main__":
    unittest.main(verbosity=2)
