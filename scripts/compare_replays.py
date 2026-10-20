"""Compare Python and Swift outputs from identical GPS replay inputs.

Both files must exist. This tool does not claim to have compiled or run Swift.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def compare_rows(left, right, *, distance_tolerance=2.0, probability_tolerance=.03):
    differences = []
    if not left or not right:
        differences.append("Replay output must contain at least one result")
    if len(left) != len(right):
        differences.append(f"row count: Python={len(left)}, Swift={len(right)}")
    exact = ("timestamp", "status", "edge_id", "route_id", "direction", "direction_label", "previous_station_id", "next_station_id", "reason")
    metric = ("offset_m", "distance_to_next_m", "uncertainty_m")
    for index, (a, b) in enumerate(zip(left, right)):
        for key in exact:
            if key not in a or key not in b or a[key] != b[key]:
                differences.append(f"row {index} {key}: {a.get(key)!r} != {b.get(key)!r}")
        for key in metric + ("confidence", "progress"):
            av, bv = a.get(key), b.get(key)
            tolerance = probability_tolerance if key in ("confidence", "progress") else distance_tolerance
            if av is None and bv is None:
                continue
            if av is None or bv is None or not math.isfinite(av) or not math.isfinite(bv) or abs(av - bv) > tolerance:
                differences.append(f"row {index} {key}: {av!r} != {bv!r} (tolerance {tolerance})")
        if (a.get("lat") is None) != (b.get("lat") is None) or (a.get("lon") is None) != (b.get("lon") is None):
            differences.append(f"row {index} coordinate availability differs")
        elif a.get("lat") is not None and a.get("lon") is not None:
            if not all(math.isfinite(value) for value in (a["lat"], a["lon"], b["lat"], b["lon"])):
                differences.append(f"row {index} coordinates must be finite")
            else:
                dy = (a["lat"] - b["lat"]) * 111_195
                dx = (a["lon"] - b["lon"]) * 111_195 * math.cos(math.radians(a["lat"]))
                if math.hypot(dx, dy) > distance_tolerance:
                    differences.append(f"row {index} coordinates differ by {math.hypot(dx, dy):.3f} m")
        ae, be = a.get("events", []), b.get("events", [])
        if len(ae) != len(be):
            differences.append(f"row {index} event count differs")
        else:
            for event_a, event_b in zip(ae, be):
                for key in ("type", "station_id"):
                    if event_a.get(key) != event_b.get(key):
                        differences.append(f"row {index} event {key} differs")
                at, bt = event_a.get("timestamp"), event_b.get("timestamp")
                if at is None or bt is None or not math.isfinite(at) or not math.isfinite(bt) or abs(at - bt) > 1e-5:
                    differences.append(f"row {index} event timestamp differs (tolerance 0.00001 seconds)")
                acf, bcf = event_a.get("confidence", 0), event_b.get("confidence", 0)
                if not math.isfinite(acf) or not math.isfinite(bcf) or abs(acf - bcf) > probability_tolerance:
                    differences.append(f"row {index} event confidence differs")
        # Candidate identity/order and probability are part of the public output.
        ac, bc = a.get("candidates", []), b.get("candidates", [])
        if len(ac) != len(bc):
            differences.append(f"row {index} candidate count differs")
        else:
            for candidate_a, candidate_b in zip(ac, bc):
                for key in ("edge_id", "route_id", "direction"):
                    if candidate_a.get(key) != candidate_b.get(key):
                        differences.append(f"row {index} candidate {key} differs")
                for key, tolerance in (("offset_m", distance_tolerance), ("probability", probability_tolerance)):
                    av, bv = candidate_a.get(key, 0), candidate_b.get(key, 0)
                    if not math.isfinite(av) or not math.isfinite(bv) or abs(av - bv) > tolerance:
                        differences.append(f"row {index} candidate {key} differs")
    return differences


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("python_results", type=Path)
    parser.add_argument("swift_results", type=Path)
    parser.add_argument("--distance-tolerance-m", type=float, default=2.0)
    parser.add_argument("--probability-tolerance", type=float, default=.03)
    args = parser.parse_args()
    differences = compare_rows(read_rows(args.python_results), read_rows(args.swift_results), distance_tolerance=args.distance_tolerance_m, probability_tolerance=args.probability_tolerance)
    print(json.dumps(dict(compared_rows=len(read_rows(args.python_results)), passed=not differences, differences=differences[:100], total_differences=len(differences)), ensure_ascii=False, indent=2))
    return bool(differences)


if __name__ == "__main__":
    raise SystemExit(main())
