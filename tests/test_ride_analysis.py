"""Artificial exports test analysis arithmetic; they are not field GPS evidence."""
import csv
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_ride import analyze_ride, main, Network, write_atomic

BASE = 1_700_000_000.0
FIELDS = "record_type session_id mode time_utc unix_seconds time_zone latitude longitude coordinate_reference_system horizontal_accuracy_m raw_speed_mps speed_accuracy_mps course_deg speed_kmh speed_valid exclusion_reason match_status match_reason route_id direction direction_label previous_station_id next_station_id distance_to_next_m progress confidence uncertainty_m matched_latitude matched_longitude edge_id offset_m events_json match_json observation_json segment session_status".split()
TRUTH = "reference_id kind time_utc end_time_utc route_id direction station_id event_type along_track_m previous_station_id next_station_id tolerance_s notes reference_basis".split()


def iso(seconds):
    return datetime.fromtimestamp(BASE + seconds, timezone.utc).isoformat()


class RideAnalysis(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.network = Network.from_json(ROOT / "fixtures/synthetic_network.json")

    def csv(self, name, fields, rows):
        path = self.folder / name
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def row(self, seconds, *, status="matched", route="main", direction=1, speed=72,
            reason="", offset=200, events=(), mode="live", lat=None):
        point = self.network.interpolate("m0", offset)
        result = dict(status=status, reason="observed", edge_id="m0", offset_m=offset,
                      route_id=route, direction=direction, previous_station_id="main_s0", next_station_id="main_s1",
                      lat=point[0], lon=point[1], confidence=.9, uncertainty_m=8, events=list(events))
        return dict(record_type="observation", session_id="session-under-test", mode=mode,
                    time_utc=iso(seconds), unix_seconds=BASE + seconds, latitude=point[0] if lat is None else lat,
                    longitude=point[1], raw_speed_mps=20, speed_kmh="" if speed is None else speed,
                    speed_valid="false" if speed is None else "true", exclusion_reason=reason,
                    match_json=json.dumps(result), events_json=json.dumps(list(events)), session_status="")

    def reference(self, ident, seconds, **fields):
        return {"reference_id": ident, "kind": "position", "time_utc": iso(seconds), **fields}

    def analyze(self, rows, refs=None, **options):
        path = self.csv("ride.csv", FIELDS, rows)
        truth = self.csv("truth.csv", TRUTH, refs) if refs is not None else None
        return analyze_ride(path, network=self.network, truth_path=truth, **options)

    def test_no_truth_does_not_claim_accuracy_or_measured_resources(self):
        report = self.analyze([self.row(0, mode="replay"), self.row(2, mode="replay")])
        self.assertEqual(report["evidence_kind"], "synthetic_replay")
        self.assertIsNone(report["positions"]["route"]["accuracy_when_confirmed"])
        self.assertEqual(report["positions"]["route"]["eligible_references"], 0)
        self.assertIsNone(report["device_measurements"]["cpu_percent_one_core"])
        self.assertIsNone(report["device_measurements"]["resident_memory_mb"])
        self.assertIsNone(report["device_measurements"]["battery_percent"])
        self.assertIsNone(report["processing_performance"]["processing_ms"])
        self.assertIsNone(report["recording"]["wall_recording_duration_s"])
        self.assertFalse(report["geometry_diagnostics"]["is_independent_position_accuracy"])
        json.dumps(report, allow_nan=False)

    def test_unknown_and_missing_reference_fields_have_honest_denominators(self):
        rows = [self.row(0), self.row(2, route="wrong", direction=1), self.row(4, status="uncertain", route=None), self.row(6)]
        refs = [self.reference("a", 0, route_id="main", direction="1"),
                self.reference("b", 2, route_id="main", direction="1"),
                self.reference("c", 4, route_id="main", direction="1"),
                self.reference("unknown", 6)]
        report = self.analyze(rows, refs)
        for key in ("route", "direction"):
            metric = report["positions"][key]
            self.assertEqual((metric["eligible_references"], metric["correct"], metric["wrong"], metric["unknown"]), (3, 1, 1, 1))
            self.assertEqual(metric["accuracy_when_confirmed"], .5)
            self.assertAlmostEqual(metric["correct_fraction_of_eligible"], 1 / 3)
            self.assertAlmostEqual(metric["coverage"], 2 / 3)

    def test_no_interpolation_across_gaps_and_no_reuse_outside_tolerance(self):
        report = self.analyze([self.row(0), self.row(20)], [self.reference("mid", 10, route_id="main", tolerance_s="2")])
        self.assertEqual(report["positions"]["aligned_references"], 0)
        self.assertEqual(report["positions"]["route"]["unknown_reasons"], {"no_observation_within_tolerance": 1})

    def test_along_track_errors_use_route_measure_and_separate_prediction(self):
        report = self.analyze([self.row(0, offset=220), self.row(2, status="predicted", offset=240), self.row(4, route="wrong")],
                              [self.reference("actual", 0, route_id="main", along_track_m="200"),
                               self.reference("prediction", 2, route_id="main", along_track_m="210"),
                               self.reference("different_route", 4, route_id="main", along_track_m="200")])
        metric = report["positions"]["along_track"]
        self.assertEqual(metric["eligible_references"], 3)
        self.assertEqual(metric["observed_absolute_error_m"]["mean"], 20)
        self.assertEqual(metric["predicted_absolute_error_m"]["mean"], 30)
        self.assertEqual(metric["unknown_reasons"], {"different_or_unknown_route": 1})

    def test_geometry_residual_is_available_without_truth_but_not_accuracy(self):
        point = self.network.interpolate("m0", 200)
        report = self.analyze([self.row(0, lat=point[0] + .0001)])
        residual = report["geometry_diagnostics"]["raw_to_matched_edge_residual_m"]
        self.assertEqual(residual["n"], 1)
        self.assertGreater(residual["mean"], 10)
        self.assertLess(residual["mean"], 12)
        self.assertEqual(report["positions"]["along_track"]["observed_absolute_error_m"]["n"], 0)

    def test_event_matching_is_one_to_one_and_maximizes_matches(self):
        events = [dict(type="pass", timestamp=BASE - 3, station_id="s"), dict(type="pass", timestamp=BASE + 3, station_id="s")]
        refs = [self.reference("one", 0, kind="event", event_type="pass", station_id="s", tolerance_s="4"),
                self.reference("two", 4, kind="event", event_type="pass", station_id="s", tolerance_s="4")]
        report = self.analyze([self.row(10, events=events)], refs)
        self.assertEqual(report["events"]["matched_reference_events"], 2)
        self.assertEqual(report["events"]["absolute_timing_error_s"]["mean"], 2)
        self.assertIsNone(report["events"]["false_positives_in_complete_windows"])

    def test_sparse_annotation_does_not_label_unannotated_events_false(self):
        events = [dict(type="pass", timestamp=BASE + 1, station_id="s"), dict(type="arrival", timestamp=BASE + 20, station_id="other")]
        ref = self.reference("known", 1, kind="event", event_type="pass", station_id="s")
        sparse = self.analyze([self.row(30, events=events)], [ref])
        self.assertIsNone(sparse["events"]["precision_in_complete_windows"])
        self.assertEqual(sparse["events"]["predictions_outside_complete_windows_unscored"], 2)
        complete = self.reference("complete", 0, kind="event_window", end_time_utc=iso(25))
        scored = self.analyze([self.row(30, events=events)], [ref, complete])
        self.assertEqual(scored["events"]["false_positives_in_complete_windows"], 1)
        self.assertEqual(scored["events"]["precision_in_complete_windows"], .5)

    def test_recovery_counts_success_timeout_and_censoring_separately(self):
        refs = [self.reference("recovered", 0, kind="outage", end_time_utc=iso(10), route_id="main"),
                self.reference("timeout", 30, kind="outage", end_time_utc=iso(40), route_id="other"),
                self.reference("censored", 90, kind="outage", end_time_utc=iso(99), route_id="other"),
                self.reference("no_route", 0, kind="outage", end_time_utc=iso(10))]
        report = self.analyze([self.row(15), self.row(100)], refs, max_recovery_s=20)
        metric = report["recovery"]
        self.assertEqual((metric["recovered"], metric["timeout"], metric["right_censored"], metric["missing_reference_route"]), (1, 1, 1, 1))
        self.assertEqual(metric["recovery_latency_s"]["mean"], 5)
        self.assertEqual(metric["recovered_fraction_of_complete_windows"], .5)

    def test_bad_clock_rows_do_not_create_false_timeline_intervals(self):
        report = self.analyze([self.row(0), self.row(10_000, speed=None, reason="future_fix"), self.row(2)])
        self.assertEqual(report["recording"]["observation_rows"], 3)
        self.assertEqual(report["recording"]["timeline_rows"], 2)
        self.assertEqual(report["recording"]["observation_interval_s"]["maximum"], 2)
        self.assertEqual(report["recording"]["maximum_accepted_speed_kmh"], 72)

    def test_measurements_are_external_and_battery_rate_excludes_charging(self):
        fields = "session_id time_utc cpu_percent_one_core resident_memory_mb battery_percent charging method notes".split()
        rows = [dict(time_utc=iso(0), cpu_percent_one_core=10, resident_memory_mb=40, battery_percent=80, charging="false", method="manual"),
                dict(time_utc=iso(3600), cpu_percent_one_core=20, resident_memory_mb=60, battery_percent=78, charging="false", method="manual")]
        path = self.csv("measurements.csv", fields, rows)
        report = self.analyze([self.row(0)], measurements_path=path)
        metric = report["device_measurements"]
        self.assertEqual(metric["cpu_percent_one_core"]["mean"], 15)
        self.assertEqual(metric["resident_memory_mb"]["maximum"], 60)
        self.assertEqual(metric["battery_drop_percentage_points_per_hour"], 2)
        rows[1]["charging"] = "unknown"
        self.csv("measurements.csv", fields, rows)
        metric = self.analyze([self.row(0)], measurements_path=path)["device_measurements"]
        self.assertIsNone(metric["battery_drop_percentage_points_per_hour"])
        self.assertEqual(metric["battery_rate_reason"], "charging_or_unknown_charging_state")

    def test_mixed_sessions_and_naive_truth_timestamps_are_rejected(self):
        other = self.row(2); other["session_id"] = "other-session"
        with self.assertRaisesRegex(ValueError, "exactly one session"):
            self.analyze([self.row(0), other])
        bad = self.reference("bad", 0, route_id="main"); bad["time_utc"] = "2026-10-21T12:00:00"
        with self.assertRaisesRegex(ValueError, "explicit timezone"):
            self.analyze([self.row(0)], [bad])

    def test_csv_quotes_and_no_source_overwrite(self):
        row = self.row(0, speed=None, reason='test, "quote"\n日本語')
        report = self.analyze([row])
        self.assertEqual(report["recording"]["exclusion_reason_counts"], {'test, "quote"\n日本語': 1})
        path = self.folder / "ride.csv"
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            write_atomic(path, "replacement", [path])
        self.assertEqual(path.read_bytes(), before)

    def test_cli_writes_local_json_and_markdown_without_raw_coordinates(self):
        path = self.csv("ride.csv", FIELDS, [self.row(0, mode="replay")])
        output, markdown = self.folder / "analysis.json", self.folder / "analysis.md"
        main([str(path), "--output", str(output), "--markdown", str(markdown)])
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["recording"]["observation_rows"], 1)
        self.assertIn("実走精度", markdown.read_text(encoding="utf-8"))
        self.assertNotIn('"latitude"', output.read_text(encoding="utf-8"))

    def test_extended_export_has_diagnostics_summary_and_limited_timing_semantics(self):
        fields = FIELDS + ["received_unix_seconds", "persistence_started_unix_seconds", "details_json"]
        observation = self.row(0)
        observation.update(received_unix_seconds=BASE + .5, persistence_started_unix_seconds=BASE + .75)
        diagnostic = dict(record_type="diagnostic", session_id="session-under-test", mode="live",
                          details_json=json.dumps(dict(kind="location_error", domain="kCLErrorDomain", code=0, detail="PRIVATE_DETAIL_DO_NOT_COPY")))
        summary = dict(record_type="session_summary", session_id="session-under-test", mode="live",
                       details_json=json.dumps(dict(started_at=BASE, ended_at=BASE + 10, last_saved_at=BASE + .75, maximum_speed_kmh=72, status="completed")))
        path = self.csv("extended.csv", fields, [observation, diagnostic, summary])
        report = analyze_ride(path)
        timing = report["processing_performance"]
        self.assertEqual(timing["received_to_persistence_start_s"]["mean"], .25)
        self.assertEqual(timing["observed_to_received_s"]["mean"], .5)
        self.assertIsNone(timing["sqlite_write_ms"])
        self.assertIsNone(timing["queue_delay_ms"])
        self.assertEqual(report["recording"]["wall_recording_duration_s"], 10)
        self.assertEqual(report["application_diagnostics"]["kind_counts"], {"location_error": 1})
        self.assertNotIn("PRIVATE_DETAIL_DO_NOT_COPY", json.dumps(report))

    def test_replay_clock_is_not_compared_to_wall_receipt_clock(self):
        fields = FIELDS + ["received_unix_seconds", "persistence_started_unix_seconds", "details_json"]
        row = self.row(0, mode="replay")
        row.update(received_unix_seconds=BASE + 1_000_000, persistence_started_unix_seconds=BASE + 1_000_001)
        report = analyze_ride(self.csv("replay.csv", fields, [row]))
        self.assertIsNone(report["processing_performance"]["observed_to_received_s"])
        self.assertEqual(report["processing_performance"]["received_to_persistence_start_s"]["mean"], 1)

    def test_public_station_catalog_does_not_claim_surveyed_truth(self):
        output = self.folder / "catalog.csv"
        main(["--network", str(ROOT / "fixtures/synthetic_network.json"), "--catalog-output", str(output)])
        with output.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertTrue(rows)
        self.assertIn("station_id", rows[0])
        self.assertEqual(rows[0]["reference_basis"], "N02_map_anchor_not_surveyed_truth")
        self.assertNotIn("latitude", rows[0])


if __name__ == "__main__":
    unittest.main()
