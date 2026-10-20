"""Record/verify SHA-256 of canonical, staged Git file contents (not working line endings)."""
import argparse
import hashlib
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MANIFEST.sha256"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def contents():
    paths = sorted(p for p in git("ls-files", "-z").decode().split("\0") if p and p != "MANIFEST.sha256")
    rows = ["# SHA-256 of canonical Git index contents; verify with python scripts/update_manifest.py --verify"]
    for path in paths:
        rows.append(hashlib.sha256(git("show", ":" + path)).hexdigest() + "  " + path)
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    expected = contents()
    if args.verify:
        if MANIFEST.read_text(encoding="utf-8") != expected:
            raise SystemExit("Manifest differs from canonical Git contents; stage changes and regenerate.")
        print("Manifest matches all canonical tracked files.")
    else:
        MANIFEST.write_text(expected, encoding="utf-8", newline="\n")
        print("Manifest updated from staged Git contents.")
