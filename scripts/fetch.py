#!/usr/bin/env python3
"""Fetch prepared plates from the mirror, rather than from the archives.

The paintings only exist at the Internet Archive and NAL, and this project is
not going to pretend otherwise -- but there is no reason for every user to pull
56 GB of full-resolution scans off a nonprofit archive to derive the same 1.3 GB
of plates. So the scans are fetched, verified and prepared once by a maintainer
(`scripts/mirror.py`), and everyone else gets the result from this repo's own
GitHub releases: CDN-backed, 2 GiB per file, no bandwidth cap.

    pom fetch                 # ~1.3 GB of plates, the index, the analysis
    pom fetch --dry-run
    pom fetch --source ia     # the 56 GB of originals, for rebuilding the mirror

Resumable and idempotent: each shard is staged as `.part`, verified against its
published SHA-256, and skipped on a re-run if the plates it carries are already
on disk.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import tarfile
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pomlib  # noqa: E402

PLATE_DIR = os.path.join(pomlib.DATA_DIR, "wallpapers")
REPO = "placeybordeaux/pomological-watercolors-lockscreen"
FORMAT = "plates-1800-v1"
STAMP = os.path.join(PLATE_DIR, ".mirror")


def base_url(repo: str, tag: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}"


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get(url: str, dest: str, expect: str | None, label: str) -> None:
    """Download to `dest`, staged as .part so an interrupted run cannot leave a
    truncated file that a later run would trust."""
    part = dest + ".part"
    if os.path.exists(dest) and (not expect or sha256(dest) == expect):
        print(f"  {label:<22} already verified")
        return
    print(f"  {label:<22} downloading…", end="", flush=True)
    data = pomlib.http_get(url)
    with open(part, "wb") as fh:
        fh.write(data)
    if expect and sha256(part) != expect:
        os.unlink(part)
        raise SystemExit(f"\n  ! {label}: checksum mismatch, refusing to use it")
    os.replace(part, dest)
    print(f"\r  {label:<22} {pomlib.human_bytes(len(data)):>10}  ok        ")


def fetch_mirror(repo: str, tag: str, dry: bool, keep_shards: bool) -> int:
    os.makedirs(PLATE_DIR, exist_ok=True)
    url = base_url(repo, tag)
    try:
        manifest = json.loads(pomlib.http_get(f"{url}/manifest.json"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"no mirror at {url}/manifest.json ({exc.code}).\n"
            f"  The release may not be published yet. You can build the data\n"
            f"  yourself instead:  pom fetch --source ia && pom prepare --all")

    total = (sum(s["bytes"] for s in manifest["shards"])
             + sum(f["bytes"] for f in manifest["files"].values()))
    have = len([f for f in os.listdir(PLATE_DIR)
                if f.endswith(".jpg") and not f.startswith("_")])
    print(f"🍅 mirror {manifest['format']} · {manifest['plates']:,} plates · "
          f"{pomlib.human_bytes(total)}  ({have:,} already on disk)")
    if dry:
        for s in manifest["shards"]:
            print(f"  would fetch {s['name']:<18} {pomlib.human_bytes(s['bytes']):>10}")
        for name, f in manifest["files"].items():
            print(f"  would fetch {name:<18} {pomlib.human_bytes(f['bytes']):>10}")
        return 0

    staging = os.path.join(pomlib.DATA_DIR, "mirror-dl")
    os.makedirs(staging, exist_ok=True)

    for name, meta in manifest["files"].items():
        dest = os.path.join(staging, name)
        get(f"{url}/{name}", dest, meta["sha256"], name)
        target = (pomlib.DB_PATH if name.startswith("pom.sqlite")
                  else os.path.join(PLATE_DIR, "_analysis.json"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with gzip.open(dest, "rb") as fi, open(target + ".part", "wb") as fo:
            shutil.copyfileobj(fi, fo)
        os.replace(target + ".part", target)

    for s in manifest["shards"]:
        dest = os.path.join(staging, s["name"])
        get(f"{url}/{s['name']}", dest, s["sha256"], s["name"])
        with tarfile.open(dest) as tf:
            tf.extractall(PLATE_DIR, filter="data")
        if not keep_shards:
            os.unlink(dest)

    if not keep_shards:
        shutil.rmtree(staging, ignore_errors=True)
    with open(STAMP, "w") as fh:
        fh.write(manifest["format"])

    n = len([f for f in os.listdir(PLATE_DIR)
             if f.endswith(".jpg") and not f.startswith("_")])
    print(f"✓ {n:,} plates in {PLATE_DIR}")
    print("  next:  pom set")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["mirror", "ia"], default="mirror",
                    help="mirror: prepared plates (~1.3 GB, the default). "
                         "ia: full-resolution originals from the Internet "
                         "Archive (~56 GB), only needed to rebuild the mirror")
    ap.add_argument("--repo", default=REPO, help="owner/name hosting the mirror")
    ap.add_argument("--tag", default=FORMAT, help="release tag to fetch")
    ap.add_argument("--keep-shards", action="store_true",
                    help="do not delete the downloaded tarballs after extracting")
    ap.add_argument("--dry-run", action="store_true")
    args, rest = ap.parse_known_args()

    if args.source == "ia":
        # The archival path, unchanged: checksum-verified, resumable, slow.
        import download_images
        sys.argv = ["pom fetch --source ia"] + rest
        return download_images.main()
    if rest:
        ap.error(f"unrecognised arguments: {' '.join(rest)}")
    return fetch_mirror(args.repo, args.tag, args.dry_run, args.keep_shards)


if __name__ == "__main__":
    raise SystemExit(main())
