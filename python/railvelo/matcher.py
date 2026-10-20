"""Bounded directed-state HMM forward filter and short-gap dead reckoning.

Confidence is relative posterior support within the supplied graph, not a
calibrated probability of real-world correctness. No timetable is consulted.
"""
import math
from collections import defaultdict

from .events import EventDetector
from .network import angle, distance


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def logsumexp(values):
    if not values:
        return -math.inf
    m = max(values)
    if not math.isfinite(m):
        return -math.inf
    return m + math.log(sum(math.exp(x - m) for x in values))


class Matcher:
    MAX_SPEED = 60.0
    MAX_GAP = 15.0
    RESET_GAP = 30.0

    def __init__(self, network):
        self.network = network
        self.events = EventDetector(network)
        self.last_timestamp = None
        self._reset()

    def _reset(self):
        self.states = []
        self.last_fix = None
        self.last_confirmed = None
        self.origin = None
        self.accepted = 0
        self.has_moved = False
        self.events.reset()

    def _empty(self, timestamp, status, reason):
        return {"timestamp": timestamp, "status": status, "edge_id": None,
                "lat": None, "lon": None, "offset_m": None, "route_id": None,
                "direction": 0, "direction_label": None, "previous_station_id": None,
                "next_station_id": None, "distance_to_next_m": None, "progress": None,
                "confidence": 0.0, "uncertainty_m": None, "reason": reason,
                "candidates": [], "events": []}

    def update(self, observation):
        o = dict(observation)
        t = o.get("timestamp")
        if not finite(t):
            return self._empty(None, "rejected", "invalid_timestamp")
        if self.last_timestamp is not None and t <= self.last_timestamp:
            return self._empty(t, "rejected", "non_monotonic_timestamp")
        lat, lon = o.get("lat"), o.get("lon")
        if lat is None and lon is None:
            self.last_timestamp = t
            return self._gap(t, "missing_fix")
        if not finite(lat) or not finite(lon) or abs(lat) > 90 or abs(lon) > 180:
            return self._empty(t, "rejected", "invalid_coordinates")
        self.last_timestamp = t
        accuracy = o.get("horizontal_accuracy_m")
        if not finite(accuracy) or accuracy <= 0 or accuracy > 150:
            return self._gap(t, "poor_accuracy", rejected=True)
        point = lat, lon
        raw_speed = o.get("speed_mps")
        speed_accuracy = o.get("speed_accuracy_mps")
        speed = raw_speed if (finite(raw_speed) and 0 <= raw_speed <= self.MAX_SPEED
                              and finite(speed_accuracy) and 0 <= speed_accuracy <= 8) else None
        reason = "speed_ignored" if finite(raw_speed) and raw_speed > self.MAX_SPEED else "observed"
        course = o.get("course_deg")
        if not finite(course) or not 0 <= course < 360 or speed is None or speed < 3:
            course = None
        if self.last_fix and t - self.last_fix["timestamp"] > self.RESET_GAP:
            self._reset()
            reason = "reacquired"
        if self.last_fix:
            dt = t - self.last_fix["timestamp"]
            displacement = distance(self.last_fix["point"], point)
            if displacement > self.MAX_SPEED * dt + max(100, 3 * (accuracy + self.last_fix["accuracy"])):
                return self._gap(t, "coordinate_jump", rejected=True)
            expected_speed = speed if speed is not None else min(self.MAX_SPEED, displacement / dt)
            # A trusted zero speed suppresses course jitter and stationary direction flips.
        else:
            dt, displacement, expected_speed = 0, 0, speed or 0
        projections = self.network.candidates(point, min(500, max(80, 3 * accuracy)))
        if not projections:
            return self._gap(t, "off_network")
        candidates = []
        sigma = max(8, accuracy)
        for p in projections:
            edge = self.network.edges[p["edge_id"]]
            for route in sorted(set(edge["route_ids"])):
                for direction in (1, -1):
                    s = dict(p, route_id=route, direction=direction)
                    emission = -0.5 * (p["cross_m"] / sigma) ** 2
                    if course is not None:
                        emission -= 0.5 * (angle(course, (p["bearing"] + (180 if direction == -1 else 0)) % 360) / 40) ** 2
                    if self.states and self.last_fix:
                        terms = []
                        for previous in self.states:
                            transit = self._transition(previous, s, dt, expected_speed, accuracy)
                            if math.isfinite(transit):
                                terms.append(previous["logp"] + transit)
                        s["score"] = emission + logsumexp(terms)
                    else:
                        s["score"] = emission
                    if math.isfinite(s["score"]):
                        candidates.append(s)
        if not candidates:
            return self._gap(t, "unreachable_transition", rejected=True)
        candidates.sort(key=lambda s: (-s["score"], s["edge_id"], s["route_id"], -s["direction"]))
        candidates = candidates[:24]
        normalizer = logsumexp([s["score"] for s in candidates])
        for s in candidates:
            s["logp"] = s["score"] - normalizer
            s["probability"] = math.exp(s["logp"])
        self.states = candidates
        best = candidates[0]
        self.accepted += 1
        self.origin = self.origin or point
        self.has_moved = self.has_moved or distance(self.origin, point) >= 20
        self.last_fix = {"timestamp": t, "point": point, "accuracy": accuracy,
                         "speed": expected_speed, "state": best}
        route_mass = defaultdict(float)
        direction_mass = defaultdict(float)
        position_mass = 0.0
        for s in candidates:
            route_mass[s["route_id"]] += s["probability"]
            location = self.network.route_location(s)
            if location:
                direction_mass[s["route_id"], location[1]] += s["probability"]
            if distance((best["lat"], best["lon"]), (s["lat"], s["lon"])) <= 50:
                position_mass += s["probability"]
        location = self.network.route_location(best)
        dir_mass = direction_mass[best["route_id"], location[1]] if location else 0
        confidence = min(position_mass, route_mass[best["route_id"]], dir_mass)
        resolved = (location is not None and self.accepted >= 3
                    and self.has_moved
                    and route_mass[best["route_id"]] >= 0.85 and dir_mass >= 0.8
                    and position_mass >= 0.65 and best["cross_m"] <= max(50, 2 * accuracy))
        r = self._empty(t, "matched" if resolved else "uncertain", reason if resolved else "insufficient_support")
        r.update(edge_id=best["edge_id"], offset_m=best["offset_m"], lat=best["lat"], lon=best["lon"],
                 confidence=confidence, uncertainty_m=max(accuracy, best["cross_m"]),
                 candidates=[{k: s[k] for k in ("edge_id", "route_id", "direction", "offset_m", "probability")} for s in candidates])
        if resolved:
            self._decorate(r, best)
            r["events"] = self.events.update(t, best["route_id"], location[0], location[1], expected_speed, confidence)
            self.last_confirmed = {"timestamp": t, "state": dict(best), "speed": expected_speed,
                                   "accuracy": accuracy, "confidence": confidence}
        else:
            # Event continuity cannot bridge an ambiguous fix or a sensor gap.
            self.events.reset()
            self.last_confirmed = None
        return r

    def _transition(self, a, b, dt, speed, accuracy):
        ea, eb = self.network.edges[a["edge_id"]], self.network.edges[b["edge_id"]]
        penalty = 0.0
        if a["edge_id"] == b["edge_id"] and a["direction"] == b["direction"] and (b["offset_m"] - a["offset_m"]) * a["direction"] >= -20:
            d = abs(b["offset_m"] - a["offset_m"])
            if (b["offset_m"] - a["offset_m"]) * a["direction"] < 0:
                penalty += 4 if speed >= 3 else 0
        elif a["edge_id"] == b["edge_id"] and a["direction"] != b["direction"]:
            d = abs(b["offset_m"] - a["offset_m"])
            penalty += 4 if speed >= 3 else 8
        else:
            exit_node = ea["to_node"] if a["direction"] == 1 else ea["from_node"]
            entry_node = eb["from_node"] if b["direction"] == 1 else eb["to_node"]
            d = ((ea["length_m"] - a["offset_m"]) if a["direction"] == 1 else a["offset_m"])
            d += self.network.shortest(exit_node, entry_node)
            d += b["offset_m"] if b["direction"] == 1 else eb["length_m"] - b["offset_m"]
        if a["route_id"] != b["route_id"]:
            penalty += 1.5
        prev_acc = self.last_fix["accuracy"]
        if d > self.MAX_SPEED * dt + 3 * (prev_acc + accuracy) + 30:
            return -math.inf
        expected = speed * dt
        beta = max(20, 0.35 * expected + prev_acc + accuracy + 3 * dt)
        return -abs(d - expected) / beta - penalty

    def _decorate(self, result, state):
        location = self.network.route_location(state)
        if location is None:
            return
        measure, direction = location
        route = self.network.routes[state["route_id"]]
        result.update(route_id=state["route_id"], direction=direction,
                      direction_label=route["forward_label"] if direction == 1 else route["reverse_label"])
        ss = self.network.route_stations.get(state["route_id"], [])
        # The station at the current measure is the immediate next physical
        # station until its centre has been passed. Endpoints have no next beyond.
        ordered = ss if direction == 1 else list(reversed(ss))
        previous, upcoming = None, None
        for s in ordered:
            if (s["measure_m"] - measure) * direction >= -0.01:
                upcoming = s
                break
            previous = s
        result["previous_station_id"] = previous["station_id"] if previous else None
        result["next_station_id"] = upcoming["station_id"] if upcoming else None
        if upcoming:
            result["distance_to_next_m"] = max(0, (upcoming["measure_m"] - measure) * direction)
        if previous and upcoming:
            length = abs(upcoming["measure_m"] - previous["measure_m"])
            result["progress"] = max(0, min(1, abs(measure - previous["measure_m"]) / length))

    def _gap(self, t, reason, rejected=False):
        self.events.reset()
        c = self.last_confirmed
        if c is None:
            return self._empty(t, "rejected" if rejected else "lost", reason)
        elapsed = t - c["timestamp"]
        uncertainty = c["accuracy"] + 5 * elapsed + 0.5 * elapsed ** 2
        if elapsed > self.MAX_GAP or uncertainty > 120:
            return self._empty(t, "rejected" if rejected else "lost", reason)
        s = dict(c["state"])
        remaining = c["speed"] * elapsed
        # Traverse only a unique graph continuation. Do not guess at a branch.
        visited = set()
        while remaining > 0:
            e = self.network.edges[s["edge_id"]]
            available = e["length_m"] - s["offset_m"] if s["direction"] == 1 else s["offset_m"]
            if remaining <= available:
                s["offset_m"] += s["direction"] * remaining
                break
            remaining -= available
            node = e["to_node"] if s["direction"] == 1 else e["from_node"]
            options = [(n, length, eid) for n, length, eid in self.network.adjacency[node] if eid != e["id"]]
            if len(options) != 1 or e["id"] in visited:
                return self._empty(t, "rejected" if rejected else "lost", reason + ":ambiguous_continuation")
            visited.add(e["id"])
            edge = self.network.edges[options[0][2]]
            if s["route_id"] not in edge["route_ids"]:
                return self._empty(t, "lost", reason + ":route_boundary")
            s["edge_id"] = edge["id"]
            s["direction"] = 1 if edge["from_node"] == node else -1
            s["offset_m"] = 0 if s["direction"] == 1 else edge["length_m"]
        p = self.network.interpolate(s["edge_id"], s["offset_m"])
        r = self._empty(t, "predicted", reason)
        r.update(edge_id=s["edge_id"], offset_m=s["offset_m"], lat=p[0], lon=p[1],
                 uncertainty_m=uncertainty, confidence=c["confidence"] * math.exp(-elapsed / 10))
        self._decorate(r, s)
        return r
