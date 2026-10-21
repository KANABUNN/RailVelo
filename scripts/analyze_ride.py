"""Analyze a local RailVelo export; independent references are required for accuracy claims.

Standard library only. No upload, network request, or modification of the source CSV.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import statistics
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from railvelo.network import Network, distance

CLOCK_ERRORS = {"stale_fix", "future_fix", "non_monotonic_timestamp", "invalid_timestamp", "invalid_receipt_timestamp"}
RESULT_KEYS = {"status", "reason", "edge_id", "offset_m", "route_id", "direction", "previous_station_id", "next_station_id", "lat", "lon", "confidence", "uncertainty_m"}


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def stats(values):
    values = sorted(value for value in values if value is not None and math.isfinite(value))
    return {"n": len(values), "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "p95": values[max(0, math.ceil(len(values) * .95) - 1)] if values else None,
            "maximum": values[-1] if values else None}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def timestamp(text, *, field="time_utc"):
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        if value.utcoffset() is None:
            raise ValueError("timezone required")
        result = value.timestamp()
        if not math.isfinite(result):
            raise ValueError("finite timestamp required")
        return result
    except (ValueError, TypeError, OverflowError, OSError) as error:
        raise ValueError(f"{field}: ISO 8601 with an explicit timezone is required") from error


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_rows(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
            raise ValueError("CSV is missing required columns: " + ", ".join(sorted(set(required) - set(reader.fieldnames or []))))
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Duplicate CSV column names")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV column count differs at line {reader.line_num}")
            if any(value.strip() for value in row.values()):
                yield row


@dataclass
class Sample:
    sequence: int
    time: float | None
    lat: float | None
    lon: float | None
    raw_speed_mps: float | None
    speed_kmh: float | None
    reason: str
    result: dict


def read_ride(path):
    required = {"record_type", "session_id", "mode", "unix_seconds", "latitude", "longitude",
                "raw_speed_mps", "speed_kmh", "speed_valid", "exclusion_reason", "match_json", "session_status"}
    samples, events, statuses = [], [], []
    metadata = {"diagnostics": [], "session_summary": None, "received_to_persistence_start_s": [], "observed_to_received_s": [], "timing_semantics": set()}
    identities, issues = set(), Counter()
    for sequence, row in enumerate(csv_rows(path, required)):
        identity = (row["session_id"].strip(), row["mode"].strip())
        if not identity[0] or identity[1] not in {"live", "replay"}:
            raise ValueError("Each record needs a session_id and a live/replay mode")
        identities.add(identity)
        if len(identities) > 1:
            raise ValueError("One export must contain exactly one session and one mode")
        time = finite(row["unix_seconds"])
        if row["record_type"] == "session_status":
            statuses.append({"time": time, "status": row["session_status"]})
            continue
        if row["record_type"] in {"diagnostic", "session_summary"}:
            try:
                details = json.loads(row.get("details_json", ""))
                if not isinstance(details, dict):
                    raise ValueError("details_json must be an object")
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid diagnostic/session_summary details_json") from error
            if row["record_type"] == "diagnostic":
                metadata["diagnostics"].append({key: details.get(key) for key in ("kind", "domain", "code")})
            else:
                if metadata["session_summary"] is not None:
                    issues["duplicate_session_summary"] += 1
                metadata["session_summary"] = {key: details.get(key) for key in ("started_at", "ended_at", "last_saved_at", "maximum_speed_kmh", "status", "timing_semantics")}
                if isinstance(details.get("timing_semantics"), str):
                    metadata["timing_semantics"].add(details["timing_semantics"])
            continue
        if row["record_type"] != "observation":
            raise ValueError("Unsupported CSV record_type")
        try:
            result = json.loads(row["match_json"])
            if not isinstance(result, dict) or not isinstance(result.get("events", []), list):
                raise ValueError("MatchResult must be an object with an event array")
            if not isinstance(result.get("status"), str):
                raise ValueError("MatchResult status must be a string")
            for key in ("edge_id", "route_id", "previous_station_id", "next_station_id"):
                if result.get(key) is not None and not isinstance(result[key], str):
                    raise ValueError("MatchResult identifiers must be strings or null")
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid match_json at observation {len(samples) + 1}") from error
        reason = row["exclusion_reason"].strip()
        valid = row["speed_valid"].strip().lower()
        if valid not in {"true", "false"}:
            raise ValueError("speed_valid must be true or false")
        speed = finite(row["speed_kmh"])
        if valid == "true" and (speed is None or speed < 0 or reason):
            issues["inconsistent_speed_validity"] += 1
            speed = None
        if valid == "false":
            if speed is not None:
                issues["invalid_speed_row_contains_value"] += 1
            speed = None
        if time is None:
            issues["nonfinite_or_missing_observation_timestamp"] += 1
        received, persistence_started = finite(row.get("received_unix_seconds")), finite(row.get("persistence_started_unix_seconds"))
        if received is not None and persistence_started is not None:
            metadata["timing_semantics"].add("received_to_persistence_start_excludes_sql_and_commit")
            if persistence_started >= received:
                metadata["received_to_persistence_start_s"].append(persistence_started - received)
            else:
                issues["persistence_started_before_receipt"] += 1
        if received is not None and time is not None and identity[1] == "live" and reason not in CLOCK_ERRORS:
            metadata["observed_to_received_s"].append(received - time)
        if row.get("details_json", "").strip():
            try:
                details = json.loads(row["details_json"])
                if isinstance(details, dict) and isinstance(details.get("timing_semantics"), str):
                    metadata["timing_semantics"].add(details["timing_semantics"])
            except (TypeError, ValueError):
                issues["invalid_observation_details_json"] += 1
        for event in result.get("events", []):
            if (not isinstance(event, dict) or finite(event.get("timestamp")) is None
                    or not isinstance(event.get("type"), str)
                    or event.get("station_id") is not None and not isinstance(event["station_id"], str)):
                issues["invalid_station_event"] += 1
                continue
            events.append({"time": finite(event["timestamp"]), "type": event.get("type"),
                           "station_id": event.get("station_id"), "route_id": result.get("route_id"),
                           "direction": result.get("direction"), "emitted_at_observation_time": time})
        samples.append(Sample(sequence, time, finite(row["latitude"]), finite(row["longitude"]),
                              finite(row["raw_speed_mps"]), speed, reason,
                              {key: result.get(key) for key in RESULT_KEYS}))
    if not identities:
        raise ValueError("CSV contains no recording records")
    session_id, mode = next(iter(identities))
    return samples, sorted(events, key=lambda row: row["time"]), statuses, issues, session_id, mode, metadata


def read_truth(path, default_tolerance):
    if path is None:
        return []
    references, ids = [], set()
    for row in csv_rows(path, {"reference_id", "kind", "time_utc"}):
        item = {key: value.strip() for key, value in row.items()}
        ref_id = item["reference_id"]
        if not ref_id or ref_id in ids:
            raise ValueError("Reference IDs must be nonempty and unique")
        ids.add(ref_id)
        if item["kind"] not in {"position", "event", "event_window", "outage"}:
            raise ValueError("Reference kind must be position/event/event_window/outage")
        item["time"] = timestamp(item["time_utc"])
        item["end_time"] = timestamp(item["end_time_utc"], field="end_time_utc") if item.get("end_time_utc") else None
        if item["kind"] in {"event_window", "outage"}:
            if item["end_time"] is None or item["end_time"] < item["time"]:
                raise ValueError("An outage/event_window needs an end time at or after its start")
        direction_text = item.get("direction", "")
        if direction_text and direction_text not in {"1", "+1", "-1"}:
            raise ValueError("Reference direction must be 1, -1, or blank for unknown")
        item["direction"] = int(direction_text) if direction_text else None
        item["along_track_m"] = finite(item.get("along_track_m"))
        if row.get("along_track_m", "").strip() and (item["along_track_m"] is None or item["along_track_m"] < 0):
            raise ValueError("Reference along_track_m must be finite and nonnegative")
        if (item["direction"] is not None or item["along_track_m"] is not None) and not item.get("route_id"):
            raise ValueError("Direction and along-track references require route_id")
        tolerance_text = item.get("tolerance_s", "")
        tolerance = finite(tolerance_text) if tolerance_text else default_tolerance
        if tolerance is None or tolerance < 0:
            raise ValueError("Reference tolerance_s must be finite and nonnegative")
        item["tolerance"] = tolerance
        if item["kind"] == "event" and item.get("event_type") not in {"arrival", "departure", "pass", "between_station_stop", "resume"}:
            raise ValueError("An event reference requires a supported event_type")
        references.append(item)
    return sorted(references, key=lambda row: row["time"])


def timeline(samples, issues):
    result, previous = [], None
    for sample in samples:
        if sample.time is None or sample.reason in CLOCK_ERRORS:
            continue
        if previous is not None and sample.time <= previous:
            issues["unflagged_non_monotonic_timestamp"] += 1
            continue
        result.append(sample)
        previous = sample.time
    return result


def nearest_sample(samples, times, time, tolerance):
    index = bisect.bisect_left(times, time)
    choices = samples[max(0, index - 1):index + 1]
    candidate = min(choices, key=lambda sample: (abs(sample.time - time), sample.time)) if choices else None
    return candidate if candidate is not None and abs(candidate.time - time) <= tolerance else None


def classification_outcome(metric, available, correct, reason):
    metric["eligible_references"] += 1
    if available:
        metric["correct" if correct else "wrong"] += 1
    else:
        metric["unknown"] += 1
        metric["unknown_reasons"][reason] += 1


def along_track(network, sample):
    if network is None:
        return None
    result = sample.result
    edge_id, route_id, offset = result.get("edge_id"), result.get("route_id"), finite(result.get("offset_m"))
    edge = network.edges.get(edge_id)
    if edge is None or offset is None or not 0 <= offset <= edge["length_m"] or (route_id, edge_id) not in network.route_edges:
        return None
    location = network.route_location({"edge_id": edge_id, "route_id": route_id, "offset_m": offset, "direction": 1})
    return location[0] if location else None


def evaluate_positions(samples, references, network):
    fields = {key: {"eligible_references": 0, "correct": 0, "wrong": 0, "unknown": 0, "unknown_reasons": Counter()}
              for key in ("route", "direction", "previous_station", "next_station")}
    times, errors, predicted_errors, signed_errors, offsets = [sample.time for sample in samples], [], [], [], []
    distance_eligible = 0
    distance_unknown = Counter()
    refs = [row for row in references if row["kind"] == "position"]
    aligned = 0
    for expected in refs:
        sample = nearest_sample(samples, times, expected["time"], expected["tolerance"])
        if sample is not None:
            aligned += 1
            offsets.append(sample.time - expected["time"])
        result = sample.result if sample else {}
        confirmed = sample is not None and result.get("status") == "matched"
        unknown_reason = "no_observation_within_tolerance" if sample is None else "match_not_confirmed"
        route_matches = not expected.get("route_id") or result.get("route_id") == expected["route_id"]
        for key, field in [("route", "route_id"), ("direction", "direction"), ("previous_station", "previous_station_id"), ("next_station", "next_station_id")]:
            known = expected.get(field)
            if known is None or known == "":
                continue
            actual = result.get(field)
            available = confirmed and actual not in (None, "", 0)
            classification_outcome(fields[key], available, actual == known and route_matches,
                                   unknown_reason if not confirmed else "field_not_available")
        if expected["along_track_m"] is not None:
            distance_eligible += 1
            if sample is None:
                distance_unknown["no_observation_within_tolerance"] += 1
            elif not route_matches:
                distance_unknown["different_or_unknown_route"] += 1
            elif result.get("status") not in {"matched", "predicted"}:
                distance_unknown["match_not_confirmed"] += 1
            else:
                measure = along_track(network, sample)
                if measure is None:
                    distance_unknown["network_or_edge_measure_unavailable"] += 1
                else:
                    error = measure - expected["along_track_m"]
                    if result["status"] == "matched":
                        errors.append(abs(error)); signed_errors.append(error)
                    else:
                        predicted_errors.append(abs(error))
    for metric in fields.values():
        confirmed = metric["correct"] + metric["wrong"]
        metric["confirmed_references"] = confirmed
        metric["accuracy_when_confirmed"] = ratio(metric["correct"], confirmed)
        metric["correct_fraction_of_eligible"] = ratio(metric["correct"], metric["eligible_references"])
        metric["coverage"] = ratio(confirmed, metric["eligible_references"])
        metric["unknown_reasons"] = dict(metric["unknown_reasons"])
    return {"position_references": len(refs), "aligned_references": aligned, "alignment_offset_s": stats(offsets),
            **fields, "along_track": {"eligible_references": distance_eligible,
            "observed_absolute_error_m": stats(errors), "observed_signed_error_m": stats(signed_errors),
            "predicted_absolute_error_m": stats(predicted_errors), "unknown_reasons": dict(distance_unknown)}}


def event_compatible(expected, predicted):
    return (expected["event_type"] == predicted["type"]
            and (not expected.get("station_id") or expected["station_id"] == predicted["station_id"])
            and (not expected.get("route_id") or expected["route_id"] == predicted["route_id"])
            and (expected.get("direction") is None or expected["direction"] == predicted["direction"])
            and abs(expected["time"] - predicted["time"]) <= expected["tolerance"])


def match_events(expected, predicted):
    """Maximum-cardinality, minimum-total-time-error monotonic one-to-one alignment."""
    width = len(predicted) + 1
    previous = [(0, 0.0)] * width
    actions = [bytearray(width) for _ in range(len(expected) + 1)]
    for i, truth in enumerate(expected, 1):
        current = [(0, 0.0)] * width
        for j, event in enumerate(predicted, 1):
            choices = [(previous[j], 1), (current[j - 1], 2)]
            if event_compatible(truth, event):
                count, error = previous[j - 1]
                choices.append(((count + 1, error + abs(truth["time"] - event["time"])), 3))
            current[j], actions[i][j] = max(choices, key=lambda item: (item[0][0], -item[0][1], item[1]))
        previous = current
    matched, i, j = [], len(expected), len(predicted)
    while i and j:
        action = actions[i][j]
        if action == 3:
            matched.append((i - 1, j - 1)); i -= 1; j -= 1
        elif action == 1:
            i -= 1
        else:
            j -= 1
    return list(reversed(matched))


def evaluate_events(events, references):
    expected = [row for row in references if row["kind"] == "event"]
    windows = [row for row in references if row["kind"] == "event_window"]
    pairs = match_events(expected, events)
    predicted_used = {j for _, j in pairs}
    errors = [events[j]["time"] - expected[i]["time"] for i, j in pairs]
    def in_complete_window(event):
        return any(window["time"] <= event["time"] <= window["end_time"]
                   and (not window.get("event_type") or window["event_type"] == event["type"])
                   and (not window.get("station_id") or window["station_id"] == event["station_id"])
                   and (not window.get("route_id") or window["route_id"] == event["route_id"])
                   and (window.get("direction") is None or window["direction"] == event["direction"])
                   for window in windows)
    scored_predictions = [j for j, event in enumerate(events) if in_complete_window(event)]
    true_positive_in_windows = sum(j in predicted_used for j in scored_predictions)
    false_positive = len(scored_predictions) - true_positive_in_windows if windows else None
    return {"reference_events": len(expected), "predicted_events": len(events), "matched_reference_events": len(pairs),
            "references_with_station_id": sum(bool(row.get("station_id")) for row in expected),
            "references_with_route_id": sum(bool(row.get("route_id")) for row in expected),
            "missed_reference_events": len(expected) - len(pairs), "recall_at_tolerance": ratio(len(pairs), len(expected)),
            "signed_timing_error_s": stats(errors), "absolute_timing_error_s": stats([abs(value) for value in errors]),
            "complete_annotation_windows": len(windows), "predictions_in_complete_windows": len(scored_predictions),
            "false_positives_in_complete_windows": false_positive,
            "precision_in_complete_windows": ratio(true_positive_in_windows, len(scored_predictions)) if windows else None,
            "predictions_outside_complete_windows_unscored": len(events) - len(scored_predictions),
            "algorithm_event_delay_s": stats([event["emitted_at_observation_time"] - event["time"] for event in events
                                               if event["emitted_at_observation_time"] is not None])}


def evaluate_recovery(samples, references, window_s):
    outages = [row for row in references if row["kind"] == "outage"]
    latencies, timeout, censored, missing_route = [], 0, 0, 0
    for outage in outages:
        if not outage.get("route_id"):
            missing_route += 1
            continue
        restored = outage["end_time"]
        found = next((sample for sample in samples if restored <= sample.time <= restored + window_s
                      and sample.result.get("status") == "matched" and sample.result.get("route_id") == outage["route_id"]
                      and (outage.get("direction") is None or sample.result.get("direction") == outage["direction"])), None)
        if found is not None:
            latencies.append(found.time - restored)
        elif samples and samples[-1].time >= restored + window_s:
            timeout += 1
        else:
            censored += 1
    return {"reference_outages": len(outages), "missing_reference_route": missing_route,
            "recovered": len(latencies), "timeout": timeout, "right_censored": censored,
            "search_window_s": window_s, "recovered_fraction_of_complete_windows": ratio(len(latencies), len(latencies) + timeout),
            "recovery_latency_s": stats(latencies)}


def device_measurements(path, session_id):
    empty = {"status": "not_measured", "provided_rows": 0, "cpu_percent_one_core": None,
             "resident_memory_mb": None, "battery_percent": None, "battery_drop_percentage_points": None,
             "battery_drop_percentage_points_per_hour": None, "battery_rate_reason": "no_measurement_file"}
    if path is None:
        return empty
    rows = []
    for row in csv_rows(path, {"time_utc", "cpu_percent_one_core", "resident_memory_mb", "battery_percent", "charging", "method"}):
        if row.get("session_id", "").strip() not in {"", session_id}:
            raise ValueError("Measurement session_id differs from the ride export")
        values = {field: finite(row[field]) for field in ("cpu_percent_one_core", "resident_memory_mb", "battery_percent")}
        for field, value in values.items():
            if row[field].strip() and (value is None or value < 0 or field == "battery_percent" and value > 100):
                raise ValueError("Invalid measurement value: " + field)
        charging = row["charging"].strip().lower()
        if charging not in {"true", "false", "unknown", ""}:
            raise ValueError("Measurement charging must be true/false/unknown")
        rows.append({**values, "time": timestamp(row["time_utc"]), "charging": charging, "method": row["method"].strip()})
    rows.sort(key=lambda row: row["time"])
    any_numeric = any(row[field] is not None for row in rows for field in ("cpu_percent_one_core", "resident_memory_mb", "battery_percent"))
    result = {**empty, "status": "user_supplied_measurements" if any_numeric else "not_measured", "provided_rows": len(rows),
              "methods": sorted({row["method"] for row in rows if row["method"]}),
              "rows_without_method": sum(not row["method"] for row in rows)}
    for field in ("cpu_percent_one_core", "resident_memory_mb", "battery_percent"):
        values = [row[field] for row in rows if row[field] is not None]
        result[field] = stats(values) if values else None
    battery = [row for row in rows if row["battery_percent"] is not None]
    result["battery_rate_reason"] = "at_least_two_timed_battery_readings_required"
    if len(battery) >= 2:
        first, last = battery[0], battery[-1]
        duration = last["time"] - first["time"]
        between = [row for row in rows if first["time"] <= row["time"] <= last["time"]]
        if duration <= 0:
            result["battery_rate_reason"] = "nonpositive_measurement_duration"
        elif any(row["charging"] != "false" for row in between):
            result["battery_rate_reason"] = "charging_or_unknown_charging_state"
        elif first["battery_percent"] < last["battery_percent"]:
            result["battery_rate_reason"] = "battery_increased_or_measurement_noise"
        else:
            drop = first["battery_percent"] - last["battery_percent"]
            result.update(battery_drop_percentage_points=drop, battery_drop_percentage_points_per_hour=drop / (duration / 3600), battery_rate_reason=None)
    return result


def analyze_ride(path, *, network=None, truth_path=None, measurements_path=None,
                 sample_tolerance_s=5.0, gap_threshold_s=5.0, max_recovery_s=120.0):
    for name, value in [("sample_tolerance_s", sample_tolerance_s), ("gap_threshold_s", gap_threshold_s), ("max_recovery_s", max_recovery_s)]:
        if not math.isfinite(value) or value < 0:
            raise ValueError(name + " must be finite and nonnegative")
    samples, events, statuses, issues, session_id, mode, metadata = read_ride(path)
    refs = read_truth(truth_path, sample_tolerance_s)
    ordered = timeline(samples, issues)
    intervals = [b.time - a.time for a, b in zip(ordered, ordered[1:])]
    residuals, snap_displacements = [], []
    for sample in ordered:
        if sample.result.get("status") != "matched" or sample.lat is None or sample.lon is None or not (-90 <= sample.lat <= 90 and -180 <= sample.lon <= 180):
            continue
        result = sample.result
        lat, lon = finite(result.get("lat")), finite(result.get("lon"))
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            snap_displacements.append(distance((sample.lat, sample.lon), (lat, lon)))
        edge = network.edges.get(result.get("edge_id")) if network else None
        if edge is not None:
            residuals.append(network.project(edge, (sample.lat, sample.lon))["cross_m"])
    speed_values = [sample.speed_kmh for sample in samples if sample.speed_kmh is not None]
    raw_speeds = [sample.raw_speed_mps * 3.6 for sample in samples if sample.raw_speed_mps is not None and sample.raw_speed_mps >= 0]
    complete_positions = [row for row in refs if row["kind"] == "position"]
    summary = metadata["session_summary"]
    wall_duration = None
    if summary:
        started, ended = finite(summary.get("started_at")), finite(summary.get("ended_at"))
        if started is not None and ended is not None:
            if ended >= started:
                wall_duration = ended - started
            else:
                issues["session_end_before_start"] += 1
        maximum = finite(summary.get("maximum_speed_kmh"))
        if maximum is not None and speed_values and abs(maximum - max(speed_values)) > .000001:
            issues["summary_and_observations_maximum_differ"] += 1
    report = {"schema_version": 1, "evidence_kind": "synthetic_replay" if mode == "replay" else "user_supplied_live_recording",
              "input": {"session_id": session_id, "mode": mode, "csv_sha256": sha256(path),
                        "network_document_sha256": hashlib.sha256(json.dumps(network.document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest() if network else None,
                        "truth_sha256": sha256(truth_path) if truth_path else None,
                        "measurements_sha256": sha256(measurements_path) if measurements_path else None},
              "reference_policy": {"provided_rows": len(refs), "position_reference_rows": len(complete_positions),
                                   "reference_basis_counts": dict(Counter(row.get("reference_basis") or "unspecified" for row in refs)),
                                   "alignment": "nearest observation within tolerance; no interpolation; matched-only classifications",
                                   "unknown_is_not_correct": True, "geometric_residual_is_accuracy": False},
              "recording": {"observation_rows": len(samples), "timeline_rows": len(ordered),
                            "accepted_speed_rows": len(speed_values), "accepted_speed_fraction": ratio(len(speed_values), len(samples)),
                            "maximum_accepted_speed_kmh": max(speed_values) if speed_values else None,
                            "maximum_raw_speed_kmh": max(raw_speeds) if raw_speeds else None,
                            "match_status_counts": dict(Counter(sample.result.get("status") or "unknown" for sample in samples)),
                            "exclusion_reason_counts": dict(Counter(sample.reason for sample in samples if sample.reason)),
                            "station_event_counts": dict(Counter(event["type"] or "unknown" for event in events)),
                            "status_transition_counts": dict(Counter(row["status"] for row in statuses)),
                            "observation_interval_s": stats(intervals), "long_interval_threshold_s": gap_threshold_s,
                            "long_observation_intervals": sum(value > gap_threshold_s for value in intervals),
                            "sensor_clock_span_s": ordered[-1].time - ordered[0].time if len(ordered) >= 2 else None,
                            "wall_recording_duration_s": wall_duration,
                            "has_session_summary": summary is not None},
              "geometry_diagnostics": {"raw_to_matched_edge_residual_m": stats(residuals),
                                       "raw_to_exported_snapped_point_m": stats(snap_displacements),
                                       "is_independent_position_accuracy": False},
              "positions": evaluate_positions(ordered, refs, network),
              "events": evaluate_events(events, refs),
              "recovery": evaluate_recovery(ordered, refs, max_recovery_s),
              "device_measurements": device_measurements(measurements_path, session_id),
              "processing_performance": {"processing_ms": None, "queue_delay_ms": None, "sqlite_write_ms": None,
                                         "received_to_persistence_start_s": stats(metadata["received_to_persistence_start_s"]) if metadata["received_to_persistence_start_s"] else None,
                                         "observed_to_received_s": stats(metadata["observed_to_received_s"]) if metadata["observed_to_received_s"] else None,
                                         "timing_semantics": sorted(metadata["timing_semantics"]) or ["not_specified"]},
              "application_diagnostics": {"rows": len(metadata["diagnostics"]),
                                          "kind_counts": dict(Counter(str(row["kind"] or "unknown") for row in metadata["diagnostics"])),
                                          "domain_code_counts": dict(Counter(str(row["domain"] or "unknown") + ":" + str(row["code"]) for row in metadata["diagnostics"]))},
              "data_quality_issues": dict(issues),
              "limitations": ["References are user-provided, not an independently certified ground truth.",
                              "Long observation intervals include sampling cadence and pauses; they are not proved GPS outages.",
                              "Event precision requires explicitly complete annotation windows; unannotated predictions are unscored.",
                              "Receipt-to-persistence-start elapsed time excludes SQL execution and commit and is not isolated CPU or queue time.",
                              "Without session_summary the interrupted status-event time cannot establish exact wall recording duration.",
                              "CPU, memory and battery values are reported only when supplied; replay does not prove field performance."]}
    return report


def markdown_report(report):
    recording = report["recording"]
    lines = ["# RailVelo 走行記録の解析", "", "入力区分: " + report["evidence_kind"],
             "", "この結果は入力記録の解析です。合成リプレイを実走精度として扱いません。", "",
             f"観測 {recording['observation_rows']} 件、有効速度 {recording['accepted_speed_rows']} 件。",
             "", "| 指標 | 正解 | 誤り | 不明 | 対象の正解記録 | 確定時正解率 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, label in [("route", "路線"), ("direction", "方向"), ("previous_station", "前駅"), ("next_station", "次に通る駅")]:
        metric = report["positions"][key]
        accuracy = metric["accuracy_when_confirmed"]
        text = f"{accuracy:.1%}" if accuracy is not None else "未評価"
        lines.append(f"| {label} | {metric['correct']} | {metric['wrong']} | {metric['unknown']} | {metric['eligible_references']} | {text} |")
    lines += ["", "不明は正解に含めません。位置誤差は正解の線路距離があり、路線が一致した観測だけの値です。",
              "", "CPU・メモリ・電池: " + report["device_measurements"]["status"],
              "", "詳細な分母・未知理由・時刻誤差・復帰時間・制約は同時に作成したJSONを確認してください。"]
    return "\n".join(lines) + "\n"


def write_atomic(path, text, protected):
    path = Path(path)
    if path.resolve() in {Path(value).resolve() for value in protected if value is not None}:
        raise ValueError("Output cannot overwrite an input")
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as target:
            name = target.name
            target.write(text)
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def reference_catalog(network):
    """Public map anchors help users enter IDs; they are not independent surveyed truth."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["route_id", "route_name", "forward_direction_1", "reverse_direction_minus_1", "station_id", "station_name", "sequence", "map_anchor_along_track_m", "reference_basis"])
    for route_id, stations in sorted(network.route_stations.items()):
        route = network.routes[route_id]
        for station in stations:
            writer.writerow([route_id, route["name"], route["forward_label"], route["reverse_label"], station["station_id"],
                             network.stations[station["station_id"]]["name"], station["sequence"], station["measure_m"], "N02_map_anchor_not_surveyed_truth"])
    return output.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, nargs="?")
    parser.add_argument("--network", type=Path, help="Read-only railway SQLite or interchange JSON; required for along-track errors")
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--measurements", type=Path)
    parser.add_argument("--output", type=Path, help="Local JSON destination; keep private outputs under recordings/")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--catalog-output", type=Path, help="Write route/station IDs and public N02 map anchors from --network")
    parser.add_argument("--sample-tolerance-s", type=float, default=5)
    parser.add_argument("--gap-threshold-s", type=float, default=5)
    parser.add_argument("--max-recovery-s", type=float, default=120)
    args = parser.parse_args(argv)
    try:
        if args.csv is None and args.catalog_output is None:
            raise ValueError("Supply a recording CSV or --catalog-output")
        if args.csv is not None and args.output is None:
            raise ValueError("A recording analysis requires --output")
        if args.markdown and args.output and args.markdown.resolve() == args.output.resolve():
            raise ValueError("JSON and Markdown outputs must differ")
        network = None
        if args.network:
            network = Network.from_sqlite(args.network) if args.network.suffix.lower() in {".sqlite", ".db"} else Network.from_json(args.network)
        if args.catalog_output:
            if network is None:
                raise ValueError("--catalog-output requires --network")
            write_atomic(args.catalog_output, reference_catalog(network), [args.csv, args.network, args.truth, args.measurements, args.output, args.markdown])
            if args.csv is None:
                print("Local route/station catalog written. Map anchors are not independent accuracy references.")
                return
        report = analyze_ride(args.csv, network=network, truth_path=args.truth, measurements_path=args.measurements,
                              sample_tolerance_s=args.sample_tolerance_s, gap_threshold_s=args.gap_threshold_s,
                              max_recovery_s=args.max_recovery_s)
        protected = [args.csv, args.network, args.truth, args.measurements]
        write_atomic(args.output, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", protected)
        if args.markdown:
            write_atomic(args.markdown, markdown_report(report), protected)
    except (ValueError, OSError, KeyError, csv.Error, sqlite3.Error) as error:
        parser.exit(2, "Analysis failed: " + str(error) + "\n")
    print("Local analysis written. No data was uploaded.")


if __name__ == "__main__":
    main()
