"""Replay JSONL observations with the Python reference engine (no dependencies)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from railvelo import Matcher, Network


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("network", type=Path)
    p.add_argument("observations", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    network = Network.from_sqlite(args.network) if args.network.suffix in (".sqlite", ".db") else Network.from_json(args.network)
    matcher = Matcher(network)
    output = args.output.open("w", encoding="utf-8", newline="\n") if args.output else sys.stdout
    try:
        for line in args.observations.read_text(encoding="utf-8").splitlines():
            if line.strip():
                output.write(json.dumps(matcher.update(json.loads(line)), ensure_ascii=False, allow_nan=False) + "\n")
    finally:
        if args.output:
            output.close()


if __name__ == "__main__":
    main()
