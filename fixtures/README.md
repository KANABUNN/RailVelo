# Synthetic evaluation fixtures

All observations here are generated data, not real GPS logs. Truth is kept in
separate `.truth.jsonl` files and never passed to the matcher.

Run `python scripts/generate_fixtures.py` to regenerate deterministically (seed
42). `manifest.json` links each replay to its network and truth.
`synthetic_network.json` contains a fork, a later merge and a parallel line with
no graph connection. `corridor_full` is generated from the actual N02 network
when available, with a fix approximately every 500 m. This tests full-corridor
coverage. It does not establish real accuracy in tunnels or urban multipath.

Station envelopes are inference parameters, not surveyed platform boundaries.
Speed comes from hidden route progress. Noise, dropouts, implausible speed and
coordinate jumps affect only the sensor stream. A first fix does not establish
travel direction. Two equal-likelihood disconnected tracks intentionally leave
an uncertain result. Timing is Python CPU timing on the evaluation machine,
not an iPhone benchmark.

Replays cover ordinary movement, station stop/departure, pass-through, route
branch/merge, disconnected parallel tracks, outlier coordinates, speed spikes,
poor accuracy, short/long loss, tunnel-like reentry, reverse movement, long
between-station stop and route endpoints. Real GPS logs were not available.
