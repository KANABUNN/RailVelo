"""Conservative event state machine driven only by confirmed real fixes."""


class EventDetector:
    def __init__(self, network):
        self.network = network
        self.reset()

    def reset(self):
        self.previous = None
        self.outside = {}
        self.stop = None
        self.arrived = None
        self.between = False
        self.recent_motion = None
        self.moving_since = None
        self.passed = set()
        self.served = set()
        self.halted = set()
        self.pending_passes = {}

    def update(self, timestamp, route_id, measure, direction, speed, confidence):
        events = []
        previous = self.previous
        if previous and (previous[1] != route_id or timestamp - previous[0] > 10):
            self.reset()
            previous = None
        stations = self.network.route_stations.get(route_id, [])
        nearby = next((s for s in stations if abs(measure - s["measure_m"]) <= s["radius_m"]), None)
        for s in stations:
            if abs(measure - s["measure_m"]) > s["radius_m"] + 20:
                self.outside[s["station_id"]] = timestamp
                self.served.discard(s["station_id"])
                self.halted.discard(s["station_id"])
                self.passed.discard((route_id, s["station_id"], direction))
        if speed >= 2:
            self.recent_motion = timestamp
        if speed <= 0.8:
            self.moving_since = None
            if nearby:
                self.halted.add(nearby["station_id"])
                for key in list(self.pending_passes):
                    if key[1] == nearby["station_id"]:
                        del self.pending_passes[key]
            if self.stop is None or abs(measure - self.stop[1]) > 30:
                self.stop = (timestamp, measure)
            dwell = timestamp - self.stop[0]
            if (nearby and dwell >= 12 and self.arrived is None
                    and abs(measure - nearby["measure_m"]) <= min(50, nearby["radius_m"] * 0.5)
                    and nearby["station_id"] in self.outside
                    and 0 <= self.stop[0] - self.outside[nearby["station_id"]] <= 90
                    and self.recent_motion is not None and self.stop[0] - self.recent_motion <= 30):
                self.arrived = (nearby["station_id"], self.stop[1])
                self.served.add(nearby["station_id"])
                events.append(self.event("arrival", self.stop[0], nearby["station_id"], confidence))
            elif (nearby is None and dwell >= 20 and not self.between
                  and self.recent_motion is not None and self.stop[0] - self.recent_motion <= 30):
                self.between = True
                events.append(self.event("between_station_stop", self.stop[0], None, confidence))
        elif speed >= 2:
            if self.moving_since is None:
                self.moving_since = timestamp
            moving = timestamp - self.moving_since >= 3
            if moving and self.arrived and abs(measure - self.arrived[1]) >= 25:
                events.append(self.event("departure", self.moving_since, self.arrived[0], confidence))
                self.arrived = None
            if moving and self.between:
                events.append(self.event("resume", self.moving_since, None, confidence))
                self.between = False
            self.stop = None
        else:
            self.moving_since = None
            self.stop = None
        if previous and speed >= 2 and previous[3] >= 2 and direction == previous[4]:
            for s in stations:
                key = route_id, s["station_id"], direction
                a, b = previous[2], measure
                crossed = a < s["measure_m"] <= b if direction == 1 else b <= s["measure_m"] < a
                if crossed and key not in self.passed and s["station_id"] not in self.served and s["station_id"] not in self.halted and (self.arrived is None or self.arrived[0] != s["station_id"]):
                    # No passage for a station at which a dwell has just occurred.
                    if self.stop is None:
                        t = previous[0] + (timestamp - previous[0]) * abs((s["measure_m"] - a) / (b - a))
                        self.pending_passes[key] = self.event("pass", t, s["station_id"], confidence)
        # Crossing a station centre precedes many legitimate stopping positions.
        # Confirm a pass only after the train has left the envelope without a stop.
        for key, event in list(self.pending_passes.items()):
            station = next(s for s in stations if s["station_id"] == key[1])
            if key[0] != route_id or key[2] != direction:
                del self.pending_passes[key]
            elif (measure - station["measure_m"]) * direction > station["radius_m"] + 20:
                if key[1] not in self.served and key[1] not in self.halted:
                    events.append(event)
                    self.passed.add(key)
                del self.pending_passes[key]
        self.previous = timestamp, route_id, measure, speed, direction
        return events

    @staticmethod
    def event(kind, timestamp, station_id, confidence):
        return {"type": kind, "timestamp": timestamp, "station_id": station_id,
                "confidence": min(0.95, confidence)}
