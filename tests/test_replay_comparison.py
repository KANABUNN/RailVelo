import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compare_replays import compare_rows


class ReplayComparison(unittest.TestCase):
    def setUp(self):
        self.result = dict(timestamp=10, status="matched", edge_id="e", route_id="r", direction=1, direction_label="forward", previous_station_id="s1", next_station_id="s2", reason="observed", offset_m=10.0, distance_to_next_m=100, uncertainty_m=5, confidence=.9, progress=.2, lat=33, lon=130, events=[], candidates=[dict(edge_id="e", route_id="r", direction=1, offset_m=10, probability=.9)])

    def test_identical_nonempty_outputs_pass(self):
        self.assertEqual(compare_rows([self.result], [copy.deepcopy(self.result)]), [])

    def test_empty_and_different_row_counts_fail(self):
        self.assertTrue(compare_rows([], []))
        self.assertTrue(compare_rows([self.result], []))

    def test_classification_and_event_mismatch_fail(self):
        for changes in (dict(route_id="wrong"), dict(status="lost"), dict(events=[dict(type="pass", timestamp=10, station_id="s2", confidence=.9)])):
            self.assertTrue(compare_rows([self.result], [{**self.result, **changes}]))

    def test_tolerance_is_applied_without_hiding_large_errors(self):
        self.assertFalse(compare_rows([self.result], [{**self.result, "offset_m": 11.0}]))
        self.assertTrue(compare_rows([self.result], [{**self.result, "offset_m": 30.0}]))
        self.assertTrue(compare_rows([self.result], [{**self.result, "confidence": float("nan")}]))
        self.assertTrue(compare_rows([self.result], [{**self.result, "lat": float("nan")}]))


if __name__ == "__main__":
    unittest.main()
