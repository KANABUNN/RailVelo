"""Stationary dwell must be continuous and supported by an approach."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from railvelo.events import EventDetector
from railvelo.network import Network


class DwellBoundaries(unittest.TestCase):
    def setUp(self):
        self.network = Network.from_json(ROOT / "fixtures/synthetic_network.json")
        self.detector = EventDetector(self.network)
        self.station = self.network.route_stations["main"][2]

    def feed(self, timestamp, offset, speed):
        return self.detector.update(timestamp, "main", self.station["measure_m"] + offset, 1, speed, .95)

    def test_creeping_breaks_continuous_stop_clock(self):
        events = []
        for row in [(0, -200, 10), (5, -100, 10), (10, 0, 0),
                    (15, 0, 0), (18, 3, 1.2), (20, 4, 0), (25, 4, 0), (30, 4, 0)]:
            events.extend(self.feed(*row))
        self.assertFalse(any(e["type"] == "arrival" for e in events))
        after_dwell = self.feed(32, 4, 0)
        self.assertEqual([e["type"] for e in after_dwell], ["arrival"])
        self.assertEqual(after_dwell[0]["timestamp"], 20)

    def test_station_start_without_approach_is_not_an_arrival(self):
        events = [e for t in range(0, 62, 2) for e in self.feed(t, 0, 0)]
        self.assertFalse(any(e["type"] == "arrival" for e in events))


if __name__ == "__main__":
    unittest.main()
