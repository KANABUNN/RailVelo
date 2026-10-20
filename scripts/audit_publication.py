"""Offline publication audit. Findings never include matched secret values.

Scans tracked working files and every reachable Git blob, including old revisions.
This is a focused detector, not a guarantee that arbitrary secrets are absent.
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sqlite3
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    "github_token": rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{40,})",
    "aws_access_key": rb"(?:AKIA|ASIA)[A-Z0-9]{16}",
    "google_api_key": rb"AIza[0-9A-Za-z_-]{35}",
    "openai_key": rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}",
    "slack_token": rb"xox[baprs]-[A-Za-z0-9-]{20,}",
    "credential_url": rb"https?://[^\s/:]+:[^\s/@]+@",
    "assigned_secret": rb'''(?i)(?:password|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[=:]\s*["'][A-Za-z0-9+/_.=-]{16,}["']''',
    "user_absolute_path": rb"(?:[A-Za-z]:\\Users\\[A-Za-z0-9_.-][^\s\"<>]*|/Users/[A-Za-z0-9_.-][^\s\"<>]*)",
}
SECRET_NAMES = re.compile(r"(?:^|/)(?:\.env(?:\..+)?|id_rsa|id_ed25519|credentials|secrets?\.json)$|\.(?:p8|p12|pfx|mobileprovision|ipa)$", re.I)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def audit() -> dict:
    findings: list[dict] = []
    scanned: set[tuple[str, str, str, int]] = set()

    def scan(path: str, data: bytes, revision: str) -> None:
        if SECRET_NAMES.search(path) and not path.endswith(".env.example"):
            findings.append({"category": "sensitive_filename", "path": path, "revision": revision})
        for category, pattern in PATTERNS.items():
            for match in re.finditer(pattern, data):
                # Source of public data contains third-party filenames, not user files.
                line = data.count(b"\n", 0, match.start()) + 1
                key = (category, path, revision, line)
                if key not in scanned:
                    scanned.add(key)
                    findings.append({"category": category, "path": path, "revision": revision, "line": line})

    tracked = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    tracked = [path for path in tracked if path]
    for path in tracked:
        source = ROOT / path
        if source.is_file():
            scan(path, source.read_bytes(), "working_tree")
    # --batch handles binary data without decoding or printing it.
    objects = []
    for line in git("rev-list", "--objects", "--all").decode("utf-8").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            objects.append((sha, path))
    payload = b"" if not objects else subprocess.check_output(
        ["git", "cat-file", "--batch"], cwd=ROOT,
        input="".join(sha + "\n" for sha, _ in objects).encode(), stderr=subprocess.PIPE)
    stream = io.BytesIO(payload)
    blob_count = 0
    for _, path in objects:
        header = stream.readline().decode().strip().split()
        if len(header) != 3:
            raise RuntimeError("Unexpected Git object response")
        sha, kind, length = header
        content = stream.read(int(length)); stream.read(1)
        if kind == "blob":
            scan(path, content, sha[:12]); blob_count += 1

    commits = git("log", "--all", "--format=%H%x09%ae%x09%ce").decode().splitlines()
    author_privacy = []
    for line in commits:
        commit, author, committer = line.split("\t")
        if any(not mail.endswith("@users.noreply.github.com") for mail in (author, committer)):
            author_privacy.append({"commit": commit[:12], "category": "non_noreply_commit_email"})

    databases, archives = [], []
    for path in tracked:
        file = ROOT / path
        if path.endswith(".sqlite"):
            with sqlite3.connect(file.resolve().as_uri() + "?mode=ro", uri=True) as db:
                tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
                # Only known public railway tables should be committed.
                private_tables = [table for table in tables if re.search(r"session|samples|gps|rides|events|users|password|token|credential", table, re.I)]
                counts = {table: db.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in private_tables}
                databases.append({"path": path, "integrity": integrity, "tables": tables, "private_table_row_counts": counts})
        if path.endswith(".zip"):
            with zipfile.ZipFile(file) as archive:
                names = archive.namelist()
                suspect = [name for name in names if SECRET_NAMES.search(name)]
                archives.append({"path": path, "entries": len(names), "sensitive_filename_candidates": suspect})
    return {"head": git("rev-parse", "HEAD").decode().strip(), "tracked_files": len(tracked),
            "reachable_commits": len(commits), "historical_blobs_scanned": blob_count,
            "findings": findings, "commit_metadata_privacy": author_privacy,
            "databases": databases, "archives": archives,
            "limitations": "Pattern-based offline audit; manual provenance and personal-data review also required."}


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
