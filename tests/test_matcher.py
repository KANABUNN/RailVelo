from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "scripts"))
from railvelo.matcher import Matcher
from railvelo.network import Network
from railvelo.events import EventDetector
from generate_fixtures import RouteGeometry, distance, make_replay, sequence


def rows(name):
    return [json.loads(line) for line in (ROOT / "fixtures" / name).read_text(encoding="utf-8").splitlines() if line]


class MatcherScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / "fixtures" / "synthetic_network.json").read_text(encoding="utf-8"))
        cls.network = Network(cls.document)

    def replay(self, name):
        matcher = Matcher(self.network)
        observations = rows(f"{name}.jsonl")
        return observations, [matcher.update(observation) for observation in observations]

    def assert_safe(self, result):
        self.assertIn(result["status"], ("matched", "predicted", "uncertain", "lost", "rejected"))
        self.assertGreaterEqual(result["confidence"], 0)
        self.assertLessEqual(result["confidence"], 1)
        if result["status"] in ("uncertain", "lost", "rejected"):
            self.assertIsNone(result["route_id"])
            self.assertEqual(result["direction"], 0)
            self.assertIsNone(result["previous_station_id"])
            self.assertIsNone(result["next_station_id"])
        if result.get("distance_to_next_m") is not None:
            self.assertGreaterEqual(result["distance_to_next_m"], 0)
        if result.get("progress") is not None:
            self.assertGreaterEqual(result["progress"], 0)
            self.assertLessEqual(result["progress"], 1)
        for event in result["events"]:
            self.assertIsInstance(event["timestamp"], (int, float))
            self.assertTrue(math.isfinite(event["timestamp"]))
            self.assertGreaterEqual(event["confidence"], 0)
            self.assertLessEqual(event["confidence"], 1)
        for candidate in result["candidates"]:
            self.assertGreaterEqual(candidate["probability"], 0)
            self.assertLessEqual(candidate["probability"], 1)
        json.dumps(result, allow_nan=False)

    def test_all_scenario_outputs_follow_safety_contract(self):
        manifest = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["scenarios"]:
            if entry["network"] != "synthetic_network.json":
                continue
            with self.subTest(scenario=entry["name"]):
                _, results = self.replay(entry["name"])
                for result in results:
                    self.assert_safe(result)

    def test_normal_running_station_pair_and_track_distance(self):
        _, results = self.replay("normal")
        last = results[-1]
        self.assertEqual(last["status"], "matched")
        self.assertEqual(last["route_id"], "main")
        self.assertEqual(last["direction"], 1)
        self.assertEqual(last["previous_station_id"], "main_s2")
        self.assertEqual(last["next_station_id"], "main_s3")
        self.assertAlmostEqual(last["distance_to_next_m"], 301.440, delta=25)
        self.assertAlmostEqual(last["progress"], (4700 - 3000.864) / (5001.440 - 3000.864), delta=.02)
        truth = rows("normal.truth.jsonl")[-1]
        self.assertLess(distance([last["lat"], last["lon"]], [truth["lat"], truth["lon"]]), 25)
        confirmed = [r for r in results[5:] if r["route_id"] is not None]
        self.assertGreater(len(confirmed), len(results[5:]) * .8)
        self.assertTrue(all(r["route_id"] == "main" for r in confirmed))

    def test_reverse_direction_and_next_passed_station(self):
        _, results = self.replay("reverse")
        last = results[-1]
        self.assertEqual(last["route_id"], "main")
        self.assertEqual(last["direction"], -1)
        self.assertEqual(last["previous_station_id"], "main_s2")
        self.assertEqual(last["next_station_id"], "main_s1")
        self.assertAlmostEqual(last["distance_to_next_m"], 2200 - 1000.288, delta=25)

    def test_turnaround_returning_to_initial_position_retains_direction_evidence(self):
        geometry = RouteGeometry(self.document, "main")
        outward = sequence(3500, 4300)
        measures = outward + sequence(4300, 3500)[1:]
        observations, _ = make_replay(geometry, measures, noise_m=1)
        for observation in observations[len(outward):]:
            observation["course_deg"] = (observation["course_deg"] + 180) % 360
        matcher = Matcher(self.network)
        results = [matcher.update(observation) for observation in observations]
        self.assertEqual(results[-1]["status"], "matched")
        self.assertEqual(results[-1]["route_id"], "main")
        self.assertEqual(results[-1]["direction"], -1)
        self.assertTrue(all(r["status"] == "matched" and r["direction"] == -1 for r in results[-5:]))

    def test_branch_and_merge_follow_graph(self):
        _, results = self.replay("branch_merge")
        truth = rows("branch_merge.truth.jsonl")
        selected = [(r, t) for r, t in zip(results, truth) if 2700 < t["measure_m"] < 5400]
        confirmed = [r for r, _ in selected if r["route_id"] is not None]
        self.assertGreater(len(confirmed), len(selected) * .8)
        self.assertTrue(all(r["route_id"] == "branch" for r in confirmed))
        self.assertTrue(all(r["edge_id"].startswith("b") for r in confirmed))
        self.assertEqual(results[-1]["route_id"], "branch")

    def test_disconnected_parallel_track_is_not_a_connection(self):
        _, results = self.replay("parallel")
        confirmed = [r for r in results[5:] if r["route_id"] is not None]
        self.assertGreater(len(confirmed), len(results[5:]) * .8)
        self.assertTrue(all(r["route_id"] == "parallel" for r in confirmed))
        # Existing main-track history cannot jump onto a nearby disconnected line.
        matcher = Matcher(self.network)
        for observation in rows("normal.jsonl")[:20]:
            matcher.update(observation)
        observation = copy.deepcopy(rows("normal.jsonl")[20])
        observation["lat"] += math.degrees(60 / 6_371_008.8)
        observation["horizontal_accuracy_m"] = 50
        result = matcher.update(observation)
        self.assertNotEqual(result.get("route_id"), "parallel")

    def test_position_jump_does_not_teleport_or_poison_history(self):
        _, results = self.replay("position_jump")
        self.assertNotEqual(results[20]["status"], "matched")
        self.assertFalse(results[20]["events"])
        self.assertEqual(results[-1]["route_id"], "main")
        self.assertLess(distance([results[19]["lat"], results[19]["lon"]], [results[21]["lat"], results[21]["lon"]]), 150)

    def test_speed_spike_does_not_advance_position(self):
        _, normal = self.replay("normal")
        _, results = self.replay("speed_spike")
        self.assertEqual(results[-1]["route_id"], "main")
        self.assertLess(distance([normal[21]["lat"], normal[21]["lon"]], [results[21]["lat"], results[21]["lon"]]), 35)
        self.assertFalse(results[20]["events"])

    def test_poor_accuracy_is_not_confirmed_as_measured(self):
        _, results = self.replay("poor_accuracy")
        self.assertTrue(all(r["status"] != "matched" for r in results[20:30]))
        self.assertTrue(all(not r["events"] for r in results[20:30]))
        self.assertEqual(results[-1]["route_id"], "main")

    def test_short_gap_is_explicitly_predicted_without_station_events(self):
        _, results = self.replay("signal_loss")
        self.assertTrue(any(r["status"] == "predicted" for r in results[15:20]))
        self.assertTrue(all(r["status"] != "matched" and not r["events"] for r in results[15:20]))
        self.assertEqual(results[-1]["route_id"], "main")

    def test_long_gap_stops_confirmation_and_recovers(self):
        _, results = self.replay("long_signal_loss")
        self.assertTrue(any(r["status"] == "lost" for r in results[20:40]))
        self.assertTrue(all(not r["events"] for r in results[10:40]))
        self.assertEqual(results[-1]["route_id"], "main")

    def test_tunnel_reentry_bad_fix_is_not_trusted(self):
        _, results = self.replay("tunnel_reentry")
        self.assertNotEqual(results[40]["status"], "matched")
        self.assertFalse(results[40]["events"])
        self.assertEqual(results[-1]["route_id"], "main")

    def test_low_speed_heading_does_not_invent_direction(self):
        _, results = self.replay("ambiguous_stationary")
        self.assertTrue(all(r["direction"] == 0 for r in results))
        self.assertTrue(all(r["route_id"] is None for r in results))
        self.assertTrue(all(not r["events"] for r in results))

    def test_route_endpoint_has_no_fictitious_next_station(self):
        _, results = self.replay("endpoint")
        # Noise may project just before the terminal marker; it must never extrapolate.
        geometry = RouteGeometry(self.document, "main")
        last = results[-1]
        self.assertLess(distance([last["lat"], last["lon"]], geometry.point(geometry.length_m)[0]), 25)
        self.assertIn(last.get("next_station_id"), (None, "main_s4"))
        self.assertNotIn(last.get("previous_station_id"), ("parallel_s4", "branch_s4"))

    def test_out_of_order_and_invalid_input_do_not_corrupt_state(self):
        observations = rows("normal.jsonl")
        matcher, control = Matcher(self.network), Matcher(self.network)
        for observation in observations[:10]:
            matcher.update(observation)
            control.update(observation)
        for changes in (dict(timestamp=observations[0]["timestamp"]), dict(timestamp=float("nan")), dict(lat=100.0), dict(lon=float("inf"))):
            bad = {**observations[10], **changes}
            result = matcher.update(bad)
            self.assertEqual(result["status"], "rejected")
            self.assert_safe(result)
        actual, expected = matcher.update(observations[10]), control.update(observations[10])
        self.assertEqual(actual["route_id"], expected["route_id"])
        self.assertEqual(actual["direction"], expected["direction"])
        self.assertAlmostEqual(actual["offset_m"], expected["offset_m"], delta=.001)

    def test_missing_or_negative_sensor_fields_are_unavailable(self):
        observations = rows("normal.jsonl")
        matcher = Matcher(self.network)
        for observation in observations:
            observation.update(speed_mps=-1, speed_accuracy_mps=-1, course_deg=-1)
            result = matcher.update(observation)
            self.assert_safe(result)
        self.assertEqual(result["route_id"], "main")
        self.assertEqual(result["direction"], 1)

    def test_station_events_use_dwell_and_movement_history(self):
        _, results = self.replay("station_stop_depart")
        events = [event for result in results for event in result["events"]]
        arrivals = [e for e in events if e["type"] == "arrival"]
        departures = [e for e in events if e["type"] == "departure"]
        self.assertEqual([e["station_id"] for e in arrivals], ["main_s2"])
        self.assertEqual([e["station_id"] for e in departures], ["main_s2"])
        self.assertLess(arrivals[0]["timestamp"], departures[0]["timestamp"])
        self.assertFalse(any(e["type"] == "pass" for e in events))

    def test_station_pass_is_distinct_from_arrival(self):
        _, results = self.replay("station_pass")
        events = [event for result in results for event in result["events"]]
        self.assertTrue(any(e["type"] == "pass" and e["station_id"] == "main_s2" for e in events))
        self.assertFalse(any(e["type"] == "arrival" for e in events))

    def test_cross_station_marker_then_stop_does_not_emit_pass_and_arrival(self):
        detector = EventDetector(self.network)
        # A train may stop past a platform midpoint. Crossing that point alone
        # must not commit a pass event before the dwell is known.
        samples = [(0, 2800, 20), (2, 2940, 20), (4, 3020, 20),
                   (6, 3020, 0), (12, 3020, 0), (18, 3020, 0), (22, 3060, 20), (26, 3100, 20)]
        events = [event for timestamp, measure, speed in samples
                  for event in detector.update(timestamp, "main", measure, 1, speed, .99)]
        self.assertEqual([e["type"] for e in events], ["arrival", "departure"])
        self.assertTrue(all(e["station_id"] == "main_s2" for e in events))

    def test_pass_event_is_confirmed_after_envelope_with_interpolated_time(self):
        detector = EventDetector(self.network)
        samples = [(0, 2800, 20), (2, 2940, 20), (4, 3020, 20), (6, 3050, 20), (8, 3150, 20)]
        result_events = [detector.update(timestamp, "main", measure, 1, speed, .99) for timestamp, measure, speed in samples]
        self.assertTrue(all(not events for events in result_events[:-1]))
        self.assertEqual(len(result_events[-1]), 1)
        event = result_events[-1][0]
        self.assertEqual(event["type"], "pass")
        self.assertEqual(event["station_id"], "main_s2")
        self.assertAlmostEqual(event["timestamp"], 2 + (3000.864 - 2940) / 80 * 2, delta=.001)

    def test_long_between_station_stop_and_resume(self):
        _, results = self.replay("between_station_stop")
        events = [event for result in results for event in result["events"]]
        stops = [e for e in events if e["type"] == "between_station_stop"]
        resumes = [e for e in events if e["type"] == "resume"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(len(resumes), 1)
        self.assertIsNone(stops[0]["station_id"])
        self.assertLess(stops[0]["timestamp"], resumes[0]["timestamp"])
        self.assertFalse(any(e["type"] == "arrival" for e in events))

    def test_stop_at_edge_of_station_envelope_is_not_arrival(self):
        geometry = RouteGeometry(self.document, "main")
        measures = sequence(2400, 3067) + [3067] * 20
        observations, _ = make_replay(geometry, measures, noise_m=1)
        matcher = Matcher(self.network)
        events = [event for observation in observations for event in matcher.update(observation)["events"]]
        self.assertFalse(any(e["type"] == "arrival" for e in events))

    def test_gap_crossing_station_does_not_fabricate_pass_event(self):
        geometry = RouteGeometry(self.document, "main")
        observations, _ = make_replay(geometry, sequence(2700, 3300, 30))
        matcher = Matcher(self.network)
        results = []
        for i, observation in enumerate(observations):
            if 7 <= i <= 13:
                observation["lat"] = observation["lon"] = None
            results.append(matcher.update(observation))
        self.assertFalse(any(event["type"] == "pass" for result in results for event in result["events"]))


class CorridorReplay(unittest.TestCase):
    @unittest.skipUnless((ROOT / "fixtures" / "corridor_full.jsonl").exists(), "Run fixture generation after N02 data build")
    def test_full_corridor_route_direction_and_along_track_position(self):
        self.assert_corridor_metrics("corridor_full")

    @unittest.skipUnless((ROOT / "fixtures" / "corridor_reverse.jsonl").exists(), "Run fixture generation after N02 data build")
    def test_full_corridor_reverse_route_direction_and_along_track_position(self):
        self.assert_corridor_metrics("corridor_reverse")

    def assert_corridor_metrics(self, scenario_name):
        from evaluate import evaluate_scenario
        manifest = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
        entry = next(e for e in manifest["scenarios"] if e["name"] == scenario_name)
        metrics = evaluate_scenario(ROOT / "fixtures", entry)
        self.assertGreater(metrics["route"]["coverage"], .90)
        self.assertGreater(metrics["route"]["accuracy_when_confirmed"], .99)
        self.assertGreater(metrics["direction"]["coverage"], .90)
        self.assertGreater(metrics["direction"]["accuracy_when_confirmed"], .99)
        self.assertLess(metrics["observed_along_track_error_m"]["p95"], 35)
        # Generous guard against accidentally unbounded graph/path traversal.
        self.assertLess(metrics["processing_ms"]["p95"], 1000)


if __name__ == "__main__":
    unittest.main()
