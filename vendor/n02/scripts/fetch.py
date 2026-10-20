"""Fetch the latest archive linked from the official pinned N02 catalogue.

No scraping of private APIs, credentials, or third-party mirrors is used.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CATALOG = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html"
SOURCES = {
    "catalog.html": CATALOG,
    "terms.html": "https://nlftp.mlit.go.jp/ksj/other/agreement.html",
    "KS-PS-N02-v3_0.pdf": "https://nlftp.mlit.go.jp/ksj/gml/product_spec/KS-PS-N02-v3_0.pdf",
    "cc-by-4.0.html": "https://creativecommons.org/licenses/by/4.0/",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "RailMonitor-N02-research/1.0"})
    with urllib.request.urlopen(req, timeout=90) as response:
        body = response.read()
        meta = {
            "url": url, "final_url": response.url, "status": response.status,
            "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "content_type": response.headers.get("Content-Type"),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
        }
    if path.exists() and path.read_bytes() != body:
        raise RuntimeError(f"Refusing to replace different existing input: {path}; use a new --dest")
    path.write_bytes(body)
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=ROOT / "data" / "raw")
    args = parser.parse_args()
    dest = args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"catalog_checked": CATALOG, "files": {}}
    for name, url in SOURCES.items():
        manifest["files"][name] = fetch(url, dest / name)
        print(f"Fetched {name}: {manifest['files'][name]['bytes']} bytes", flush=True)
    # Read bytes as ASCII-compatible UTF-8 here: only URLs/filenames are parsed.
    html = (dest / "catalog.html").read_bytes().decode("utf-8", errors="replace")
    matches = re.findall(r"DownLd\('[^']*','(N02-(\d\d)_GML\.zip)','([^']+)'", html)
    if not matches:
        raise RuntimeError("Official catalogue no longer has the expected download links")
    name, year, rel = max(matches, key=lambda x: int(x[1]))
    url = urllib.parse.urljoin(CATALOG, rel)
    if urllib.parse.urlparse(url).hostname != "nlftp.mlit.go.jp":
        raise RuntimeError("Archive link left the official host")
    manifest["selected_year"] = 2000 + int(year)
    manifest["archive"] = name
    manifest["files"][name] = fetch(url, dest / name)
    with zipfile.ZipFile(dest / name) as z:
        if z.testzip() is not None:
            raise RuntimeError("ZIP CRC verification failed")
        manifest["zip_members"] = [
            {"name": i.filename, "bytes": i.file_size, "crc32": f"{i.CRC:08x}"}
            for i in z.infolist()
        ]
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {name}: {manifest['files'][name]['sha256']}", flush=True)


if __name__ == "__main__":
    main()
