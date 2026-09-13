#!/usr/bin/env python3
"""Build and publish the plate mirror, so nobody else has to hit the archives.

The paintings can only ever come from the Internet Archive and NAL -- that is
where they are. What this avoids is every user of this project re-downloading
56 GB of full-resolution scans from a nonprofit archive to produce the same
1.3 GB of derivatives. The scans are fetched once, prepared once, and the
result is published as release assets on this repo's own GitHub releases,
which are CDN-backed, capped at 2 GiB per file, and explicitly not
bandwidth-limited.

Consumers use `pom fetch`, which reads the manifest and pulls the shards.
Rebuilding the mirror is a maintainer job and needs the originals:

    pom fetch --source ia            # the 56 GB, once
    pom prepare --all
    scripts/mirror.py build
    scripts/mirror.py upload --dry-run
    scripts/mirror.py upload
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pomlib  # noqa: E402

PLATE_DIR = os.path.join(pomlib.DATA_DIR, "wallpapers")
BUILD_DIR = os.path.join(pomlib.DATA_DIR, "mirror")
MANIFEST = "manifest.json"

# Bumped when the derivative format changes (a different plate height, a
# different trim). `pom fetch` compares it against what is already on disk.
FORMAT = "plates-1800-v1"
DEFAULT_SHARDS = 8


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_to(src: str, dst: str) -> None:
    with open(src, "rb") as fi, gzip.open(dst, "wb", compresslevel=9) as fo:
        shutil.copyfileobj(fi, fo)


def build(shards: int, dry: bool) -> dict:
    plates = sorted(f for f in os.listdir(PLATE_DIR)
                    if f.endswith(".jpg") and not f.startswith("_"))
    if not plates:
        raise SystemExit(f"no prepared plates in {PLATE_DIR} - run `pom prepare --all`")

    total = sum(os.path.getsize(os.path.join(PLATE_DIR, p)) for p in plates)
    print(f"🍅 {len(plates):,} plates, {pomlib.human_bytes(total)} -> {shards} shards "
          f"(~{pomlib.human_bytes(total / shards)} each)")
    if dry:
        return {}

    os.makedirs(BUILD_DIR, exist_ok=True)
    manifest = {"format": FORMAT, "plates": len(plates), "shards": [], "files": {}}

    per = (len(plates) + shards - 1) // shards
    for i in range(shards):
        group = plates[i * per:(i + 1) * per]
        if not group:
            continue
        name = f"plates-{i:02d}.tar"
        path = os.path.join(BUILD_DIR, name)
        # Uncompressed tar: the payload is JPEG, which gzip cannot improve on,
        # and an uncompressed member can be extracted while still downloading.
        with tarfile.open(path, "w") as tf:
            for p in group:
                tf.add(os.path.join(PLATE_DIR, p), arcname=p)
        manifest["shards"].append({
            "name": name, "plates": len(group),
            "bytes": os.path.getsize(path), "sha256": sha256(path)})
        print(f"  {name}  {len(group):>5,} plates  "
              f"{pomlib.human_bytes(os.path.getsize(path)):>10}")

    # The index and the per-plate analysis, which compose needs and which are
    # pure text, so they do compress.
    for src, name in [(pomlib.DB_PATH, "pom.sqlite.gz"),
                      (os.path.join(PLATE_DIR, "_analysis.json"), "analysis.json.gz")]:
        if not os.path.exists(src):
            raise SystemExit(f"missing {src}")
        out = os.path.join(BUILD_DIR, name)
        gzip_to(src, out)
        manifest["files"][name] = {
            "bytes": os.path.getsize(out), "sha256": sha256(out)}
        print(f"  {name}  {pomlib.human_bytes(os.path.getsize(out)):>10}")

    with open(os.path.join(BUILD_DIR, MANIFEST), "w") as fh:
        json.dump(manifest, fh, indent=1)
    size = sum(s["bytes"] for s in manifest["shards"]) + \
        sum(f["bytes"] for f in manifest["files"].values())
    print(f"✓ {BUILD_DIR}  {pomlib.human_bytes(size)} total")
    return manifest


def upload(tag: str, repo: str | None, dry: bool) -> None:
    if not shutil.which("gh"):
        raise SystemExit("gh not found; it is what talks to the releases API")
    assets = sorted(os.path.join(BUILD_DIR, f) for f in os.listdir(BUILD_DIR))
    if not assets:
        raise SystemExit(f"nothing in {BUILD_DIR} - run `mirror.py build` first")
    total = sum(os.path.getsize(a) for a in assets)

    repo_args = ["--repo", repo] if repo else []
    exists = subprocess.run(["gh", "release", "view", tag, *repo_args],
                            capture_output=True).returncode == 0

    print(f"🍅 {len(assets)} assets, {pomlib.human_bytes(total)} -> release {tag}"
          f"{' (exists, will replace assets)' if exists else ' (new)'}")
    for a in assets:
        print(f"    {os.path.basename(a):<22} {pomlib.human_bytes(os.path.getsize(a)):>10}")
    if dry:
        print("(dry run - nothing uploaded)")
        return

    if not exists:
        subprocess.run(["gh", "release", "create", tag, *repo_args,
                        "--title", f"Plate mirror {tag}",
                        "--notes", NOTES.format(format=FORMAT)], check=True)
    # --clobber so a re-run replaces assets rather than erroring on each one.
    subprocess.run(["gh", "release", "upload", tag, *assets, "--clobber",
                    *repo_args], check=True)
    print(f"✓ uploaded")


NOTES = """Prepared plates from the USDA Pomological Watercolor Collection, so
that using this project does not mean re-downloading 56 GB of full-resolution
scans from the Internet Archive.

Format `{format}`: every catalogued painting with a public scan, trimmed out of
its copy-stand backdrop and scaled to 1800 px tall, plus the catalogue index
and the per-plate analysis.

`pom fetch` reads `manifest.json` and pulls the rest. Each shard is verified
against its SHA-256.

The paintings are public domain. U.S. Department of Agriculture Pomological
Watercolor Collection. Rare and Special Collections, National Agricultural
Library, Beltsville, MD 20705.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="tar the plates into shards + manifest")
    b.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    b.add_argument("--dry-run", action="store_true")

    u = sub.add_parser("upload", help="publish the shards as release assets")
    u.add_argument("--tag", default=FORMAT)
    u.add_argument("--repo", help="owner/name; defaults to the current checkout's")
    u.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    if args.cmd == "build":
        build(args.shards, args.dry_run)
    else:
        upload(args.tag, args.repo, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
