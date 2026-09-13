#!/usr/bin/env python3
"""Summarise the collection: who painted what, when, and - for scans already on
disk - what shape they are, which is what decides their fitness as wallpapers.

Usage:
    python3 scripts/stats.py              # collection overview
    python3 scripts/stats.py --shapes     # measure pixel dimensions on disk
    python3 scripts/stats.py --top 25     # widen the ranked lists
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pomlib  # noqa: E402


def jpeg_dimensions(path: str) -> tuple[int, int] | None:
    """Read width/height straight from the JPEG SOF marker.

    Avoids a Pillow dependency: the fetch stage is stdlib-only and there is no
    reason for the reporting stage to be the thing that needs a virtualenv.
    """
    with open(path, "rb") as fh:
        data = fh.read(2)
        if data != b"\xff\xd8":
            return None
        while True:
            b = fh.read(1)
            if not b:
                return None
            if b != b"\xff":
                continue
            marker = fh.read(1)
            while marker == b"\xff":
                marker = fh.read(1)
            m = marker[0]
            if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                continue
            length_bytes = fh.read(2)
            if len(length_bytes) < 2:
                return None
            length = struct.unpack(">H", length_bytes)[0]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                payload = fh.read(7)
                h, w = struct.unpack(">HH", payload[1:5])
                return w, h
            fh.seek(length - 2, os.SEEK_CUR)


def bar(n: int, peak: int, width: int = 28) -> str:
    return "█" * max(1, round(width * n / peak)) if n else ""


def ranked(conn, column: str, top: int, label: str) -> None:
    rows = conn.execute(
        f"SELECT {column} AS k, COUNT(*) AS n FROM items "
        f"WHERE {column} IS NOT NULL AND TRIM({column}) <> '' "
        f"GROUP BY 1 ORDER BY n DESC LIMIT ?", (top,)).fetchall()
    if not rows:
        return
    peak = rows[0]["n"]
    distinct = conn.execute(
        f"SELECT COUNT(DISTINCT {column}) FROM items").fetchone()[0]
    print(f"\n{label}  ({distinct:,} distinct)")
    for r in rows:
        print(f"  {str(r['k'])[:42]:<42} {r['n']:>5}  {bar(r['n'], peak)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarise the watercolor collection.")
    ap.add_argument("--db", default=pomlib.DB_PATH)
    ap.add_argument("--originals", default=pomlib.ORIGINALS_DIR)
    ap.add_argument("--top", type=int, default=12, help="rows per ranked list")
    ap.add_argument("--shapes", action="store_true",
                    help="measure pixel dimensions of downloaded scans")
    args = ap.parse_args()

    conn = pomlib.connect(args.db)
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    scanned = conn.execute(
        "SELECT COUNT(*) FROM items WHERE scan_status='available'").fetchone()[0]
    fetched = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE verified=1").fetchone()[0]

    print("🍇 USDA Pomological Watercolor Collection")
    print(f"   {total:,} catalogued · {scanned:,} with a public scan · "
          f"{fetched:,} downloaded and checksum-verified")

    span = conn.execute(
        "SELECT MIN(year), MAX(year) FROM items WHERE year IS NOT NULL").fetchone()
    print(f"   painted {span[0]}–{span[1]}")

    ranked(conn, "common_name", args.top, "Most-painted fruit")
    ranked(conn, "artist", args.top, "Most prolific artists")
    ranked(conn, "sci_name", args.top, "Most-painted species")

    decades = conn.execute(
        "SELECT (year/10)*10 AS d, COUNT(*) n FROM items "
        "WHERE year IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()
    if decades:
        peak = max(r["n"] for r in decades)
        print("\nBy decade")
        for r in decades:
            print(f"  {r['d']}s {r['n']:>5}  {bar(r['n'], peak)}")

    if args.shapes:
        print("\nMeasuring scans on disk...")
        shapes, ratios, missing = Counter(), [], 0
        rows = conn.execute("SELECT pom_id, name FROM ia_files ORDER BY pom_id").fetchall()
        for r in rows:
            path = os.path.join(args.originals, r["name"])
            if not os.path.exists(path):
                missing += 1
                continue
            dim = jpeg_dimensions(path)
            if not dim:
                continue
            w, h = dim
            shapes["portrait" if h > w else "landscape" if w > h else "square"] += 1
            ratios.append((w / h, r["pom_id"], w, h))
        if not ratios:
            print("  no scans on disk yet")
            return 0
        print(f"  measured {len(ratios):,} scans ({missing:,} not downloaded yet)")
        for k, n in shapes.most_common():
            print(f"  {k:<10} {n:>5}  ({100*n/len(ratios):.1f}%)")
        ratios.sort()
        med = ratios[len(ratios) // 2]
        print(f"  median aspect  {med[0]:.3f}  ({med[2]}×{med[3]})")
        # A modern phone screen is roughly 0.46 wide-over-tall; the closer a
        # painting sits to that, the less it has to be cropped to fill a screen.
        PHONE = 1080 / 2340
        near = sum(1 for r in ratios if abs(r[0] - PHONE) < 0.08)
        print(f"  within 0.08 of a 1080×2340 phone screen: {near:,} "
              f"({100*near/len(ratios):.1f}%)")
        print(f"  tallest: {ratios[0][1]} {ratios[0][2]}×{ratios[0][3]} "
              f"(ratio {ratios[0][0]:.3f})")
        print(f"  widest:  {ratios[-1][1]} {ratios[-1][2]}×{ratios[-1][3]} "
              f"(ratio {ratios[-1][0]:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
